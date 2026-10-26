#!/usr/bin/env python3
"""Compare routing/NAT, native RSC and the pinned CI container in the owned L6 lab.

Only fixed loopback QMP/API endpoints are accepted. Saves a recovery journal
before replacing owned VM processes and restores the original topology on exit.
"""
import argparse
import contextlib
import copy
from datetime import datetime,timezone
import fcntl
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import threading
import time

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
from tools import perf_guest as guest
from sdwan.config import load,validate
from sdwan.router import Router

IMAGE='a98ff28196c2ac187d89a285c511f99faa128c3279fe0fd6ef06d219231e677e'
TAG='sdwan-perf-fixture'


def wait_until(predicate,timeout=90):
    end=time.monotonic()+timeout;last=None
    while time.monotonic()<end:
        try:
            value=predicate()
            if value:return value
        except (OSError,RuntimeError,ValueError) as error:last=error
        time.sleep(.5)
    raise TimeoutError('Benchmark wait expired: '+str(last))


def launch(args):
    subprocess.run(['sg','kvm','-c',shlex.join(args)],check=True,capture_output=True,text=True)


def stop_vm(port,name):
    try:guest.qmp(port,name,'quit')
    except ConnectionRefusedError:return
    def gone():
        try:
            with socket.create_connection(('127.0.0.1',port),.3):return False
        except OSError:return True
    wait_until(gone,15)


def shutdown_dut(router):
    """Let RouterOS flush its configuration before replacing its QEMU process."""
    guest.qmp(24400,'sdwan-x86-lte')
    try:router.call('system/shutdown',{},'POST')
    except (OSError,RuntimeError):pass
    def gone():
        try:
            with socket.create_connection(('127.0.0.1',24400),.3):return False
        except OSError:return True
    wait_until(gone,60)


def read_command(path):
    value=json.loads(path.read_text());return value['command'] if isinstance(value,dict) else value


class Benchmark:
    def __init__(self,root,seconds=10,repeats=2):
        self.root=root.resolve();self.lte=self.root/'runtime/x86-lte-lab';self.run=self.root/'runtime/performance-lab/runtime'
        self.run.mkdir(parents=True,exist_ok=True);self.seconds=seconds;self.repeats=repeats
        self.run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        self.a=None;self.created=[];self.changed=[];self.applied=False;self.topology_changed=False;self.before_files=set()
        self.report={'pass':False,'run_id':self.run_id,'production_modified':False,'environment':'WSL2/QEMU/KVM x86 L6; not physical ARM capacity',
                     'seconds':seconds,'repeats':repeats,'runs':[],'stages':[],
                     'native_sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (SOURCE/'native').glob('*.rsc')}}
    def record(self,name,**data):
        self.report['stages'].append({'name':name,**data});self.save();print(name,flush=True)
    def save(self):
        target=self.run/'comparison.json';temp=target.with_suffix('.tmp');temp.write_text(json.dumps(self.report,indent=2)+'\n');temp.replace(target)
        (self.run/('comparison-'+self.run_id+'.json')).write_text(json.dumps(self.report,indent=2)+'\n')
    def router(self):
        guest.qmp(24400,'sdwan-x86-lte')
        r=Router(self.lte,'api://127.0.0.1:24404',credentials_data=json.loads((self.lte/'runtime/credentials.json').read_text()))
        try:
            if r.call('system/identity')['name']!='MikroTik' or r.call('system/license')[0]['nlevel']!='6':raise ValueError('DUT identity/license mismatch')
        except Exception:r.close();raise
        return r
    def connect(self):
        self.lock=(self.lte/'runtime/lab.lock').open('a');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.perf_lock=(self.run/'lab.lock').open('a');fcntl.flock(self.perf_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if (self.run/'recovery.json').exists():raise RuntimeError('Existing recovery journal: restore before starting another benchmark')
        self.a=self.router()
        if self.a.call('system/scheduler?name=sdwan-controller') or self.a.file_entry('sdwan-backup.json'):raise RuntimeError('DUT still managed: restore existing test first')
        for menu in ('ip/address','ip/route','ip/firewall/nat','routing/rule'):
            if any(r.get('comment','').startswith(TAG) for r in self.a.call(menu+'/print',{'.proplist':'comment'},'POST')):raise RuntimeError('Previous benchmark fixtures remain: '+menu)
        if any(r.get('name')=='perf-wan2' for r in self.a.call('routing/table')):raise RuntimeError('Previous benchmark table remains')
        guest.qmp(24420,'sdwan-lte-chr');guest.qmp(24500,'sdwan-perf-client')
        try:
            guest.qmp(24510,'sdwan-perf-server')
        except ConnectionRefusedError:pass
        else:raise RuntimeError('Existing server: refuse duplicate benchmark')
        self.original={'dut':read_command(self.lte/'runtime/launch.json'),'chr':read_command(self.lte/'runtime/chr-launch.json'),
                       'client':read_command(self.run/'client-launch.json')}
        drive=self.original['dut'][self.original['dut'].index('-drive')+1]
        expected=str(self.lte/'images/routeros-x86-l6.qcow2')
        if drive!='file='+expected+',format=qcow2,bus=0,unit=0,media=disk':raise ValueError('License-sensitive IDE geometry mismatch')
        self.report['platform']=self.a.call('system/resource');self.before_files={r['name'] for r in self.a.call('file/print',{'.proplist':'name'},'POST')}
        self.report['baseline']={'apn':self.a.call('interface/lte/apn/print',{'.proplist':'name,add-default-route,default-route-distance,use-peer-dns'},'POST'),
                                 'lte':self.a.call('interface/lte/print',{'.proplist':'name,disabled,apn-profiles'},'POST')}
        self.record('owned idle x86 L6, CHR and generator verified')
    def topology(self):
        images=self.run.parent/'images';guest.iso_boot_files(images/guest.ISO_NAME,images)
        self.report['initramfs']=guest.build_initrd(images)
        (self.run/'recovery.json').write_text(json.dumps({'original':self.original,'stage':'before-topology-mutation'},indent=2)+'\n')
        self.topology_changed=True
        shutdown_dut(self.a);self.a.close();self.a=None
        stop_vm(24500,'sdwan-perf-client');stop_vm(24420,'sdwan-lte-chr')
        server=guest.launch_args(self.run.parent,'server');launch(server)
        wait_until(lambda:guest.checked('server','test -d /sys/class/net/eth3 && echo shell-ready',3),30)
        dut=self.original['dut']+['-netdev','socket,id=perfwan1,connect=127.0.0.1:24532','-device','e1000,netdev=perfwan1,mac=52:54:00:79:10:01',
                                  '-netdev','socket,id=perfwan2,connect=127.0.0.1:24540','-device','e1000,netdev=perfwan2,mac=52:54:00:79:10:02']
        launch(dut)
        def ready():
            self.a=self.router();return True
        wait_until(ready,100)
        client=guest.launch_args(self.run.parent,'client');launch(client)
        wait_until(lambda:guest.checked('client','test -d /sys/class/net/eth2 && echo shell-ready',3),30)
        self.report['endpoints']={node:guest.bootstrap(node) for node in ('server','client')}
        guest.checked('server','ip link set eth1 up; ip address replace 192.0.5.1/24 dev eth1\nip link set eth2 up; ip address replace 198.19.80.1/24 dev eth2\nip link set eth3 up; ip address replace 192.0.6.1/24 dev eth3\nip address replace 198.18.79.1/32 dev lo\nip address replace 198.18.79.2/32 dev lo\niperf3 -s -B 198.18.79.1 -D --pidfile /run/iperf.pid\niperf3 -s -B 198.19.80.1 -D --pidfile /run/direct-iperf.pid')
        guest.checked('client','ip link set eth1 up; ip address replace 192.168.79.2/24 dev eth1; ip address replace 192.168.79.3/24 dev eth1\nip link set eth2 up; ip address replace 198.19.80.2/24 dev eth2\nip route replace 198.18.79.0/30 via 192.168.79.1 dev eth1\nping -c 2 -W 2 198.19.80.1')
        # TCP probes are external to the DUT; listeners and all package state are RAM only.
        for port in (24440,24441,24442):guest.checked('server',f'nc -ll -p {port} -e /bin/true >/tmp/nc-{port}.log 2>&1 & echo $!')
        self.ifaces={r['mac-address'].lower():r['name'] for r in self.a.call('interface/ethernet/print',{'.proplist':'name,mac-address'},'POST')}
        self.wan1=self.ifaces['52:54:00:79:10:01'];self.wan2=self.ifaces['52:54:00:79:10:02']
        self.record('diskless generators booted; direct L2 ping and unchanged x86 L6 verified',wans=[self.wan1,self.wan2])
    def add(self,menu,data):
        data=dict(data);data['comment']=TAG
        row=self.a.call(menu,data,'PUT');self.created.append((menu,row['.id']));return row
    def change(self,menu,row,data):
        old={key:row[key] if key in row else self.a.call(menu+'/get',{'number':row['.id'],'value-name':key},'POST')['ret'] for key in data}
        self.changed.append((menu,row['.id'],old));self.a.call(menu+'/'+row['.id'],data,'PATCH')
    def routing(self):
        lte=next(r for r in self.a.call('interface/lte') if r['name']=='lte1');self.change('interface/lte',lte,{'disabled':'true'})
        dhcp=next(r for r in self.a.call('ip/dhcp-client') if r['interface']=='ether3');self.change('ip/dhcp-client',dhcp,{'add-default-route':'no'})
        for row in self.a.call('ip/route'):
            if row.get('comment')=='lte-emulator-test':self.change('ip/route',row,{'disabled':'true'})
        for iface,net in [(self.wan1,5),(self.wan2,6)]:
            self.add('ip/address',{'address':f'192.0.{net}.2/24','interface':iface})
            self.add('ip/firewall/nat',{'chain':'srcnat','src-address':'192.168.79.0/24','out-interface':iface,'action':'masquerade'})
        # Distinct comments are deliberate guarded adoption selectors.
        for i in (1,2):
            row=self.a.call('ip/route',{'dst-address':'0.0.0.0/0','gateway':f'192.0.{4+i}.1','distance':str(i),'comment':TAG+'-wan'+str(i)},'PUT');self.created.append(('ip/route',row['.id']))
        row=self.a.call('routing/table',{'name':'perf-wan2','fib':'true'},'PUT');self.created.append(('routing/table',row['.id']))
        self.add('ip/route',{'dst-address':'0.0.0.0/0','gateway':'192.0.6.1','routing-table':'perf-wan2'})
        self.add('routing/rule',{'src-address':'192.168.79.3/32','action':'lookup-only-in-table','table':'perf-wan2'})
        self.cfg=load(SOURCE/'config/sdwan.json');self.cfg['revision']='external-load-comparison';self.cfg['wans']=[]
        for i,iface in [(1,self.wan1),(2,self.wan2)]:
            self.cfg['wans'].append({'name':'wan'+str(i),'interface':iface,'address':f'192.0.{4+i}.2','gateway':f'192.0.{4+i}.1','probe_table':'sdwan-probe-wan'+str(i),
              'icmp_target':'198.18.79.1','probes':[{'name':label,'type':'tcp-conn','host':'198.18.79.1','port':24440+n} for n,label in enumerate('abc')]})
        self.cfg['local_networks']=['192.168.79.0/24','10.79.0.0/24','172.31.255.0/30']
        self.cfg['sla_profiles']={'default':{'rtt_ms':150,'jitter_ms':100,'loss_percent':2}}
        self.cfg['policies']=[{'name':name,'source':src,'table':table,'mode':mode,'wans':wans,'profile':'default','allow_degraded':False} for name,src,table,mode,wans in
                             [('default','','main','prefer',['wan1','wan2']),('client','192.168.79.2/32','sdwan-client','prefer',['wan1','wan2']),('fixed','192.168.79.3/32','sdwan-fixed','strict',['wan2'])]]
        self.cfg['takeover_route_comments']=[TAG+'-wan1',TAG+'-wan2'];self.cfg['takeover_rule']={'src-address':'192.168.79.3/32','table':'perf-wan2'};validate(self.cfg)
        spec=importlib.util.spec_from_file_location('sdwan_perf_cli',SOURCE/'sdwan.py');self.cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.cli)
        guest.checked('client','ping -c 2 -W 2 198.18.79.1')
        for target,source in [('198.19.80.1','198.19.80.2'),('198.18.79.1','192.168.79.2')]:
            result=json.loads(guest.checked('client',f'iperf3 -c {target} -B {source} -u -l 64 -b 1M -t 1 -J --connect-timeout 5000',15))
            if result.get('error') or not result.get('end',{}).get('sum',{}).get('bytes'):raise RuntimeError('UDP handshake/data precheck failed')
        self.report['config']=self.cfg;self.record('equivalent two-WAN NAT and three client policies prepared')
    def apply(self,backend):
        cfg=copy.deepcopy(self.cfg)
        if backend=='container':
            cfg.update(controller_backend='container',container=json.loads((self.lte/'runtime/sdwan-container-test-config.json').read_text())['container'])
            row=next(r for r in self.a.call('container') if r['name']=='sdwan-container-controller')
            if row.get('image-id','').removeprefix('sha256:')!=IMAGE:raise ValueError('Container is not the pinned CI image')
            self.report['container_image_id']=IMAGE
        self.applied=True
        with contextlib.redirect_stdout(io.StringIO()):self.cli.apply(self.a,cfg,'MikroTik')
        if backend=='container':
            row=next(r for r in self.a.call('container') if r['name']=='sdwan-container-controller')
            if row.get('running')!='true':self.a.call('container/start',{'numbers':row['.id']},'POST')
        since=None
        def settled():
            nonlocal since
            state=self.a.status()
            eligible=state.get('selected',{}).get('client')=='wan1' and state.get('selected',{}).get('fixed')=='wan2' and state.get('states') and all(r.get('state')=='healthy' for r in state['states'].values())
            if backend=='container':eligible=eligible and state.get('container',{}).get('active') is True
            if not eligible:since=None;return False
            if since is None:since=time.monotonic()
            return state if time.monotonic()-since>=6 else False
        state=wait_until(settled,100)
        self.record(backend+' admitted both WANs with fresh SLA',selected=state['selected'])
    def rollback(self):
        if not self.applied:return
        with contextlib.redirect_stdout(io.StringIO()):self.cli.rollback(self.a,'MikroTik')
        self.applied=False
        for name in ('sdwan-backup.json','sdwan-active.json'):
            if name not in self.before_files:
                row=self.a.file_entry(name)
                if row:self.a.call('file/'+row['.id'],method='DELETE')
        self.record('protected rollback restored benchmark baseline')
    def measure(self,mode,label,flags,*,direct=False,source='192.168.79.2'):
        target='198.19.80.1' if direct else '198.18.79.1';source='198.19.80.2' if direct else source
        stop=threading.Event();samples=[];sampler_errors=[]
        def sample():
            r=self.a.fresh()
            try:
                while not stop.is_set():
                    start=time.monotonic();row={'elapsed':round(start-started,3),'resource':r.call('system/resource'),
                      'cpu':r.call('system/resource/cpu/print',{'.proplist':'cpu,load,irq,disk'},'POST'),
                      'conntrack_count':r.call('ip/firewall/connection/print',{'count-only':''},'POST')}
                    if mode=='container':row['container']=r.call('container/print',{'.proplist':'name,running,memory-current,cpu-usage'},'POST')
                    if mode in ('native','container'):row['sdwan']=r.status()
                    samples.append(row);stop.wait(max(.05,1-(time.monotonic()-start)))
            except Exception as error:sampler_errors.append(str(error))
            finally:r.close()
        started=time.monotonic();worker=threading.Thread(target=sample,daemon=True);worker.start()
        code=shlex.join(['iperf3','-c',target,'-B',source,'-t',str(self.seconds),'-O','2','-i','0','-J','--connect-timeout','5000']+flags)
        result={'mode':mode,'label':label,'command':code,'router_samples':samples,'sampler_errors':sampler_errors}
        try:
            rc,output=guest.command('client',code+' 2>/tmp/sdwan-iperf-stderr',self.seconds+40)
            result['exit_status']=rc;result['raw_output']=output
            result['stderr']=guest.checked('client','cat /tmp/sdwan-iperf-stderr')
            try:result['iperf']=json.loads(output)
            except json.JSONDecodeError as error:raise RuntimeError('iperf did not return JSON: '+output[-2000:]) from error
            if rc or result['iperf'].get('error'):raise RuntimeError('iperf error: '+str(result['iperf'].get('error',rc)))
            if not samples or sampler_errors:raise RuntimeError('Incomplete DUT telemetry: '+str(sampler_errors))
            end=result['iperf'].get('end',{})
            if not end.get('streams'):raise RuntimeError('No completed traffic streams')
            result['measurement_complete']=True
        except Exception as error:
            if hasattr(error,'guest_transcript'):result['transport_transcript']=error.guest_transcript.decode('utf-8',errors='replace')
            raise
        finally:
            stop.set();worker.join(15);result['elapsed_seconds']=round(time.monotonic()-started,3)
            self.report['runs'].append(result);self.save()
        rate=end.get('sum_received',end.get('sum',{})).get('bits_per_second')
        print(json.dumps({'mode':mode,'test':label,'received_mbit_s':None if rate is None else round(rate/1e6,3)}),flush=True)
    def matrix(self,mode,smoke=False):
        if smoke:
            self.measure(mode,'tcp-forward-smoke',[]);return
        workloads=[('tcp-forward',[]),('tcp-reverse',['-R']),('tcp-bidir',['--bidir']),('tcp-parallel4',['-P','4'])]
        for length in (64,512,1472):
            for rate in ('5M','20M','50M'):workloads.append((f'udp-{length}-{rate}',['-u','-l',str(length),'-b',rate]))
        for repeat in range(self.repeats):
            for label,flags in workloads:self.measure(mode,label+'-'+str(repeat+1),flags)
        self.measure(mode,'strict-wan2-tcp',[],source='192.168.79.3')
    def failover(self,backend):
        """Blackhole WAN1 during real TCP load; unrelated WAN2 tuple must survive."""
        guest.checked('server','iperf3 -s -p 5202 -D --pidfile /run/strict-server.pid')
        guest.checked('server','iperf3 -s -p 5203 -D --pidfile /run/primary-server.pid')
        guest.checked('client','iperf3 -c 198.18.79.1 -B 192.168.79.3 -p 5202 -b 20M -t 180 -J >/tmp/strict.json 2>&1 & echo $! >/run/strict.pid\niperf3 -c 198.18.79.1 -B 192.168.79.2 -p 5203 -b 50M -t 180 -J >/tmp/primary.json 2>&1 & echo $! >/run/primary.pid')
        fields='protocol,src-address,src-port,dst-address,dst-port,reply-src-address,reply-src-port,reply-dst-address,reply-dst-port,connection-mark,tcp-state,orig-bytes,repl-bytes'
        keys=fields.split(',')[:9]
        def connections():return self.a.call('ip/firewall/connection/print',{'.proplist':fields},'POST')
        def strict():
            rows=[r for r in connections() if r.get('src-address')=='192.168.79.3' and r.get('dst-port')=='5202' and r.get('connection-mark')=='sdwan-out-fixed:wan2' and r.get('tcp-state')=='established' and int(r.get('orig-bytes',0))>100000]
            return rows[0] if len(rows)==1 else False
        baseline=wait_until(strict,15);identity={k:baseline.get(k) for k in keys}
        def primary():
            rows=[r for r in connections() if r.get('src-address')=='192.168.79.2' and r.get('dst-port')=='5203' and r.get('connection-mark')=='sdwan-out-client:wan1' and r.get('tcp-state')=='established' and int(r.get('orig-bytes',0))>100000]
            return rows[0] if len(rows)==1 else False
        original_primary=wait_until(primary,15)
        def preserved():
            rows=[r for r in connections() if all(r.get(k)==v for k,v in identity.items()) and r.get('tcp-state')=='established']
            if len(rows)!=1 or int(rows[0].get('orig-bytes',0))<=int(baseline['orig-bytes']):raise AssertionError('Original strict WAN2 TCP tuple did not survive/grow')
            return rows[0]
        def selected(wan):
            s=self.a.status()
            return s if s.get('selected',{}).get('default')==wan and s.get('selected',{}).get('client')==wan and s.get('selected',{}).get('fixed')=='wan2' else False
        def fresh_data(wan):
            output=guest.checked('client','iperf3 -c 198.18.79.1 -B 192.168.79.2 -t 3 -b 20M -J --connect-timeout 5000',15)
            result=json.loads(output)
            if result.get('error') or result.get('end',{}).get('sum_received',{}).get('bytes',0)<100000:raise AssertionError('No recovered client TCP data')
            rows=[r for r in connections() if r.get('src-address')=='192.168.79.2' and r.get('connection-mark')=='sdwan-out-client:'+wan and r.get('dst-port')=='5201']
            if not rows:raise AssertionError('Recovered data lacks expected SD-WAN mark')
            return result
        evidence={'backend':backend,'strict_original':baseline,'primary_original':original_primary};self.report.setdefault('failover_load',[]).append(evidence)
        try:
            started=time.monotonic();guest.checked('server','ip link set eth1 down')
            state=wait_until(lambda:selected('wan2'),75);evidence['failure_selection_seconds']=round(time.monotonic()-started,3)
            evidence['failure_selected']=state['selected'];evidence['strict_during_failure']=preserved()
            evidence['fallback_traffic']=fresh_data('wan2');evidence['failure_new_tcp_complete_seconds']=round(time.monotonic()-started,3)
            recovered=time.monotonic();guest.checked('server','ip link set eth1 up')
            state=wait_until(lambda:selected('wan1'),75);evidence['recovery_selection_seconds']=round(time.monotonic()-recovered,3)
            # Failback performs scoped retirement too; wait for a settled window.
            time.sleep(6)
            evidence['recovered_traffic']=fresh_data('wan1');evidence['recovery_new_tcp_complete_seconds']=round(time.monotonic()-recovered,3)
            evidence['strict_after_recovery']=preserved();evidence['pass']=True
            self.record(backend+' WAN blackhole/fresh-SLA recovery under load; original strict WAN2 TCP preserved')
        finally:
            guest.checked('server','ip link set eth1 up')
            guest.checked('client','for file in /run/primary.pid /run/strict.pid; do read flow_pid < "$file"; kill -INT "$flow_pid" 2>/dev/null || :; done')
            guest.checked('server','for file in /run/primary-server.pid /run/strict-server.pid; do read flow_pid < "$file"; kill -INT "$flow_pid" 2>/dev/null || :; done')
            self.save()
    def close(self):
        errors=[]
        def attempt(fn):
            try:fn();return True
            except Exception as error:errors.append(type(error).__name__+': '+str(error));return False
        if self.applied:attempt(self.rollback)
        if self.applied:
            self.report['cleanup']={'pass':False,'recovery_required':True,'baseline_preserved':True,'errors':errors};self.report['pass']=False;self.save()
            if self.a:self.a.close()
            for key in ('lock','perf_lock'):
                if hasattr(self,key):getattr(self,key).close()
            return
        if self.a:
            for menu,id,old in reversed(self.changed):attempt(lambda menu=menu,id=id,old=old:self.a.call(menu+'/'+id,old,'PATCH'))
            for menu,id in reversed(self.created):
                def remove(menu=menu,id=id):
                    rows=self.a.call(menu+'/print',{'.proplist':'.id'},'POST')
                    if any(row['.id']==id for row in rows):self.a.call(menu+'/'+id,method='DELETE')
                attempt(remove)
            if self.created or self.changed or self.topology_changed:
                for menu in ('ip/address','ip/route','ip/firewall/nat','routing/rule'):
                    remaining=self.a.call(menu+'/print',{'.proplist':'.id,comment'},'POST')
                    if any(row.get('comment','').startswith(TAG) for row in remaining):errors.append('Benchmark fixture cleanup incomplete: '+menu)
            if self.topology_changed:
                for menu in ('system/scheduler','system/script'):
                    for row in self.a.call(menu+'?name=sdwan-controller'):attempt(lambda menu=menu,row=row:self.a.call(menu+'/'+row['.id'],method='DELETE'))
            if 'baseline' in self.report:
                current=self.a.call('interface/lte/apn/print',{'.proplist':'name,add-default-route,default-route-distance,use-peer-dns'},'POST')
                if current!=self.report['baseline']['apn']:errors.append('APN routing changed unexpectedly')
            self.a.close();self.a=None
        if self.topology_changed and not errors:
            def stop_dut():
                try:guest.qmp(24400,'sdwan-x86-lte')
                except ConnectionRefusedError:return
                r=self.router()
                try:shutdown_dut(r)
                finally:r.close()
            attempt(stop_dut)
            attempt(lambda:stop_vm(24500,'sdwan-perf-client'));attempt(lambda:stop_vm(24510,'sdwan-perf-server'))
            if not errors:
                attempt(lambda:launch(self.original['dut']))
                def restored():
                    r=self.router()
                    try:
                        self.report['restored_license']=r.call('system/license')[0]['nlevel']
                        for menu in ('ip/address','ip/route','ip/firewall/nat','routing/rule'):
                            if any(row.get('comment','').startswith(TAG) for row in r.call(menu+'/print',{'.proplist':'comment'},'POST')):raise ValueError('Fixture reappeared after restart: '+menu)
                        if any(row.get('name')=='perf-wan2' for row in r.call('routing/table')):raise ValueError('Benchmark table reappeared after restart')
                        return True
                    finally:r.close()
                attempt(lambda:wait_until(restored,100))
                attempt(lambda:launch(self.original['chr']));attempt(lambda:launch(self.original['client']))
                if not errors:(self.run/'recovery.json').unlink()
        for key in ('lock','perf_lock'):
            if hasattr(self,key):getattr(self,key).close()
        self.report['cleanup']={'pass':not errors,'errors':errors}
        if errors:self.report['pass']=False
        self.save()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lab-root',type=Path,required=True);parser.add_argument('--seconds',type=int,default=10);parser.add_argument('--repeats',type=int,default=2);parser.add_argument('--smoke',action='store_true');args=parser.parse_args()
    if not 5<=args.seconds<=30 or not 1<=args.repeats<=3:parser.error('Expected 5..30 seconds, 1..3 repeats')
    bench=Benchmark(args.lab_root,args.seconds,args.repeats);failure=None
    try:
        bench.connect();bench.topology();bench.routing()
        bench.measure('direct','endpoint-headroom-forward',[],direct=True);bench.measure('direct','endpoint-headroom-reverse',['-R'],direct=True)
        bench.matrix('baseline-before',args.smoke)
        for backend in ('native','container'):
            bench.apply(backend);bench.matrix(backend,args.smoke)
            if not args.smoke:bench.failover(backend)
            bench.rollback()
        bench.matrix('baseline-after',args.smoke)
        if not args.smoke:
            bench.measure('direct-after','endpoint-headroom-forward',[],direct=True);bench.measure('direct-after','endpoint-headroom-reverse',['-R'],direct=True)
        bench.report['pass']=True
    except Exception as error:
        bench.report['error']=type(error).__name__+': '+str(error);failure=error;print(bench.report['error'],flush=True)
    finally:bench.close()
    if failure or not bench.report.get('cleanup',{}).get('pass'):return 1
    print('Comparison complete; owned topology restored',flush=True);return 0


if __name__=='__main__':raise SystemExit(main())
