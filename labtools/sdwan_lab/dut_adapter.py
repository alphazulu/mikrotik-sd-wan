"""Concrete comparison adapter. Every mutation targets its newly owned QEMU guest."""
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import time
from .cps_pool import build,reserve,validate_result
from .dut_fixture import Fixture,SOURCES,load_config,sha,topology_config,wait
from .dut_metrics import GeneratorSampler,RouterSampler,receiver_metrics,summarize
from .runtime import atomic_json,boot_id,checked


def source_bindings(config,plan):
    bindings=plan['bindings'];source=config['source']
    for name,digest in bindings['native_sources'].items():
        if sha(source/'native'/name)!=digest:raise ValueError('Native source changed after preparation')
    for group in ('lab_sources','sdk_sources'):
        if not bindings.get(group):raise ValueError('Plan lacks operational source bindings; prepare it again')
        for name,digest in bindings[group].items():
            path=(source/name).resolve()
            if not path.is_relative_to(source) or sha(path)!=digest:raise ValueError('Operational source changed after preparation: '+name)
    sys.path.insert(0,str(source));from tools.container_checks import source_digest
    if source_digest(source)!=bindings['controller_source_sha256']:raise ValueError('Covered controller source changed')
    for profile,item in bindings['images'].items():
        if sha(config['artifacts']/item['file'])!=item['sha256']:raise ValueError('Pinned '+profile+' image changed')
    for mode,digest in plan['variant_sha256'].items():
        file=config['variants']/(mode+'.json')
        if sha(file)!=digest:raise ValueError('Mode configuration changed')
        topology_config(json.loads(file.read_text()))


def calibration(config,plan):
    if not all(name in config for name in ('calibration_tcpudp','calibration_cps')):raise ValueError('Provide both generator calibration reports')
    tcp=json.loads(config['calibration_tcpudp'].read_text());cps=json.loads(config['calibration_cps'].read_text())
    for label,report in [('TCP/UDP',tcp),('CPS',cps)]:
        if report.get('status')!='completed' or report.get('pass') is not True or report.get('cleanup_pass') is not True:raise ValueError(label+' calibration not passed/clean')
        journal=json.loads((config['calibration_tcpudp' if label=='TCP/UDP' else 'calibration_cps'].parent/'journal.json').read_text())
        if not journal['resources'] or any(r.get('boot_id')!=boot_id() for r in journal['resources'] if r.get('kind') in ('process','namespace')):raise ValueError('Calibration is from another host boot')
    if cps['build']['source_sha256']!=sha(Path(__file__).with_name('cps_pool.c')):raise ValueError('CPS calibration source differs')
    needed=next(w for w in plan['workloads'] if w['kind']=='cps');rows=cps['runs']
    if len(rows)<3 or any(r.get('pass') is not True or r['offered_cps']<needed['rate'] or r['spec']['warmup']<plan['warmup_seconds'] or r['spec']['seconds']<plan['seconds'] or len(r['spec']['sources'])!=len(SOURCES) for r in rows):raise ValueError('Long CPS pool calibration does not cover this plan')
    if not tcp.get('tool_versions') or not any('iperf 3.19.1' in v for v in tcp['tool_versions'].values()):raise ValueError('Pinned iperf3 calibration missing')
    current=checked([config['tools']['iperf3'],'--version']).stdout.strip()
    if current not in tcp['tool_versions'].values():raise ValueError('iperf3 build/version changed since calibration')
    for workload in plan['workloads']:
        if workload['kind']=='cps':continue
        matches=[(i,w) for i,w in enumerate(tcp['config']['workloads']) if w['kind']==workload['kind'] and w['direction']==workload['direction'] and (w['kind']=='tcp' or w['payload_bytes']==workload['payload_bytes'])]
        if not matches:raise ValueError('Missing generator workload calibration')
        index,w=matches[0];key='offered_bps' if w['kind']=='tcp' else 'offered_pps'
        if w[key]<workload[key]*2 or len([r for r in tcp['runs'] if r['case']==index and r['pass']])<3:raise ValueError('Insufficient generator calibration reserve/repeats')
    return {'tcpudp_report_sha256':sha(config['calibration_tcpudp']),'cps_report_sha256':sha(config['calibration_cps']),'host_boot_id':boot_id(),'scope':'direct isolated generator reserve; DUT NAT is checked separately by actual cases'}


class Adapter:
    def __init__(self,path,plan_path):self.config=load_config(path);self.plan_path=Path(plan_path);self.fixture=None;self.binary=None;self.web=None;self.sequence=0
    def preflight(self,plan,run):
        if os.geteuid():raise ValueError('Use root only on the dedicated Linux lab')
        source_bindings(self.config,plan);proof=calibration(self.config,plan)
        if sha(self.config['base_disk'])!=self.config['base_sha256']:raise ValueError('Stopped base changed')
        if not self.config['credentials'].is_file():raise ValueError('Prepared private credentials are missing')
        for tool in self.config['tools'].values():checked([tool,'--version'],timeout=5)
        return {'pass':True,'scope':'owned-isolated-lab','source_matches_plan':True,'generator_calibration_pass':True,'cps_source_pool_validated':True,'calibration':proof,'dut_vcpu':self.config['vcpu'],'dut_memory_mib':self.config['memory_mib'],'data_nic':self.config['data_nic'],'DUT_capacity_validated':False}
    def snapshot(self,plan,run):
        self.fixture=Fixture(self.config,run)
        try:
            snapshot=self.fixture.prepare();self.binary=build(run,self.config['tools']['cc'])
            compiled=json.loads((run.folder/'cps-pool-build.json').read_text());calibrated=json.loads(self.config['calibration_cps'].read_text())['build']
            if compiled!=calibrated:raise ValueError('CPS executable differs from the calibrated binary')
            return snapshot
        except BaseException:
            path=run.folder/'dut-snapshot.json'
            if path.exists():
                recovery=self.fixture.restore(json.loads(path.read_text()));atomic_json(run.folder/'snapshot-failure-restoration.json',recovery)
                if not recovery.get('verified'):
                    run.data['pending'].append({'kind':'dut-base-integrity','name':'snapshot restoration unverified'});run.save()
            raise
    def stop_web(self,run,strict=True):
        if self.web is not None:
            run.stop(self.web.pid);self.web=None
            rows=(run.folder/'web-reader.stdout').read_text().splitlines();report=json.loads(rows[-1]);atomic_json(run.folder/'web-reader-summary.json',report)
            if strict and report.get('errors'):raise ValueError('Dashboard reader observed failed requests')
    def set_mode(self,mode,plan,run,snapshot):
        source_bindings(self.config,plan);self.stop_web(run);self.fixture.set_mode(mode,plan,snapshot)
        if mode=='container-web':
            from sdwan.container_config import addresses,telemetry
            from sdwan.container_runtime import paths
            cfg=self.fixture.active_config;token=self.fixture.router.read_file(paths(cfg)['web_token']);file=run.folder/'web-reader-token.secret';file.write_text(token);file.chmod(0o600)
            url='http://'+addresses(cfg)[2]+':'+str(telemetry(cfg)['port'])
            self.web=run.spawn(self.fixture.ns_argv(0,[sys.executable,'-m','sdwan_lab.web_reader','--url',url,'--token-file',file]),'web-reader')
            wait(lambda:'ready' in (run.folder/'web-reader.stdout').read_text() or self.web.poll() is not None,10)
            if self.web.poll() is not None:raise ValueError('Optional dashboard reader could not start')
    def measure(self,mode,case,repeat,plan,run,snapshot):
        self.fixture.observed(mode);self.sequence+=1;label=f'{self.sequence:03d}-{mode}-{case["id"]}-{repeat}';host='198.18.79.1';warmup=plan['warmup_seconds'];seconds=plan['seconds'];f=self.fixture
        gen=GeneratorSampler();router=RouterSampler(f)
        try:
            with gen,router:
                if self.web is not None:gen.add(self.web.pid,'web-reader')
                for item in run.data['resources']:
                    if item.get('kind')=='process' and item.get('name') in ('dut-sla','dut-echo','dut-pinned-echo') and not item['deleted']:gen.add(item['pid'],item['name'])
                if case['kind']=='cps':
                    spec=reserve(run,SOURCES,rate=case['rate'],warmup=warmup,seconds=seconds,concurrency=case['concurrency'])
                    server=run.spawn(f.ns_argv(1,spec.server_argv(self.binary,host)),label+'-server');gen.add(server.pid,'server');wait(lambda:'ready' in (run.folder/(label+'-server.stdout')).read_text(),10)
                    child=run.spawn(f.ns_argv(0,spec.client_argv(self.binary,host)),label+'-client');gen.add(child.pid,'client')
                    if child.wait(timeout=warmup+seconds+20):raise ValueError('CPS client failed')
                    run.stop(server.pid);value=json.loads((run.folder/(label+'-client.stdout')).read_text());peer=json.loads((run.folder/(label+'-server.stdout')).read_text().splitlines()[-1]);validated=validate_result(value,peer,spec)
                    metrics={'receiver_rate':value['successful_cps'],'rate_unit':'cps','cps':validated};origin=value['origin_monotonic_seconds']+warmup
                else:
                    port=5201;tool=self.config['tools']['iperf3'];server=run.spawn(f.ns_argv(1,[tool,'-s','-1','-B',host,'-p',port,'-J']),label+'-server');gen.add(server.pid,'server')
                    wait(lambda:':5201' in f.ns(1,['ss','-H','-ltn']).stdout and server.poll() is None,10)
                    argv=[tool,'-c',host,'-B','192.168.50.101','-p',str(port),'-t',str(seconds),'-O',str(warmup),'--json-stream','--forceflush','--get-server-output']
                    if case['direction']=='reverse':argv.append('-R')
                    if case['direction']=='bidir':argv.append('--bidir')
                    if case['kind']=='udp':argv+=['-u','-l',str(case['payload_bytes']),'-b',str(case['offered_pps']*case['payload_bytes']*8)]
                    else:argv+=['-b',str(case['offered_bps'])]
                    stem=run.folder/(label+'-iperf');child=run.spawn(f.ns_argv(0,[sys.executable,'-m','sdwan_lab.iperf_runner','--output',stem,'--']+argv),label+'-client')
                    gen.add(child.pid,'iperf-json-collector');meta=stem.with_suffix('.process.json');wait(lambda:meta.exists(),10);process=json.loads(meta.read_text())
                    if process['group']!=child.pid or os.getpgid(process['pid'])!=child.pid:raise ValueError('iperf subprocess does not belong to owned wrapper')
                    gen.add(process['pid'],'client')
                    if child.wait(timeout=warmup+seconds+25) or server.wait(timeout=5):raise ValueError('iperf endpoint failed')
                    value=json.loads(stem.with_suffix('.json').read_text())
                    if value.get('error'):raise ValueError(value['error'])
                    settings=value['start']['test_start']
                    if settings['omit']!=warmup or settings['duration']!=seconds:raise ValueError('iperf measurement window differs from plan')
                    if not value['start'].get('connected') or any(row.get('local_host')!='192.168.50.101' or row.get('remote_host')!=host for row in value['start']['connected']):raise ValueError('iperf source/peer tuple differs from the selected client')
                    metrics=receiver_metrics(value,case);origin=value['measurement_origin_monotonic']
                    metrics['resource_window_alignment_deviation_seconds']=value['measurement_alignment_max_deviation_seconds']
        finally:
            atomic_json(run.folder/(label+'-generator.json'),gen.rows);atomic_json(run.folder/(label+'-router.json'),router.rows)
        metrics.update(summarize(gen,router,origin,seconds,mode));self.fixture.observed(mode);metrics.update(**{'pass':True,'observed_mode':mode,'raw_prefix':label,'client_policy':'default' if case['kind']=='cps' else 'client101'})
        if self.web is not None and self.web.poll() is not None:raise ValueError('Dashboard reader exited during measurement')
        return metrics
    def switching(self,mode,plan,run,snapshot):
        f=self.fixture;f.observed(mode);observers=[];markers={};captures=[];result={'pass':False,'pinned_flow_preserved':False,'observer':'sdwan_lab.continuity'}
        label='switch-'+mode
        try:
            for index in (1,2):
                file=run.folder/(label+'-wan'+str(index)+'.pcap');tag=label+'-capture'+str(index)
                capture=run.spawn(f.ns_argv(1,['tcpdump','-n','-U','-i','wan'+str(index),'-s','96','-w',file,'host','198.18.79.1','and','port','25351']),tag)
                wait(lambda:'listening on' in (run.folder/(tag+'.stderr')).read_text(),10);captures.append((capture,file,tag))
            for address,name,port in [('192.168.50.101','affected',25351),('192.168.50.102','pinned',25352)]:
                file=run.folder/(label+'-'+name+'.json');child=run.spawn(f.ns_argv(0,[sys.executable,'-m','sdwan_lab.continuity','measure','--host','198.18.79.1','--port',str(port),'--source-address',address,'--seconds','70','--interval-ms',str(plan['switching']['interval_ms']),'--output',file]),label+'-'+name);observers.append((child,file,name))
            wait(lambda:all(address in f.ns(0,['ss','-Hnt','state','established','dst','198.18.79.1']).stdout for address in ['192.168.50.101','192.168.50.102']),10);time.sleep(3)
            f.ns(1,['tc','qdisc','replace','dev','wan1','root','netem','loss','100%']);markers['drop']=time.monotonic_ns()
            def selected(a):
                state=f.router.status();return state if state.get('selected',{}).get('client101')==a and state.get('selected',{}).get('client102')=='wan2' else None
            result['failover_status']=wait(lambda:selected('wan2'),20);time.sleep(3);f.ns(1,['tc','qdisc','del','dev','wan1','root']);markers['restore']=time.monotonic_ns();result['failback_status']=wait(lambda:selected('wan1'),25)
            observations={}
            for child,file,name in observers:
                if child.wait(timeout=80):raise ValueError('Continuity observer failed')
                value=json.loads(file.read_text());observations[name]=value['protocols'];after=markers['restore']-value['origin_monotonic_ns']
                if not all(any(e['protocol']==protocol and e['event']=='received' and e['ns']>after for e in value['events']) for protocol in ('udp','tcp')):raise ValueError('No observed application recovery after WAN restoration')
            pinned=observations['pinned'];affected=observations['affected']
            preserved=pinned['udp']['unanswered']==0 and pinned['tcp']['established_sessions']==1 and pinned['tcp']['disconnects']==0
            if not preserved or affected['udp']['unanswered']<=0 or affected['tcp']['established_sessions']<2:raise ValueError('Affected/pinned flow expectations failed')
            wire={}
            for child,file,tag in captures:
                run.stop(child.pid);text=(run.folder/(tag+'.stderr')).read_text();match=re.search(r'(\d+) packets dropped by kernel',text)
                if not match or int(match[1]):raise ValueError('Incomplete packet capture')
                wire[tag]=pcap_count(file)
                if not wire[tag]:raise ValueError('Affected traffic was not observed on each required WAN')
            result.update(**{'pass':True,'pinned_flow_preserved':True,'observations':observations,'wire_packets':wire,'markers_monotonic_ns':markers,'scope':'application observations plus per-WAN capture; echo gaps include probe interval, RTT and scheduling'})
            return result
        finally:
            try:f.ns(1,['tc','qdisc','del','dev','wan1','root'])
            except Exception:pass
            for child,_,_ in captures:
                if child.poll() is None:run.stop(child.pid)
            for child,_,_ in observers:
                if child.poll() is None:run.stop(child.pid)
    def restore(self,plan,run,snapshot):
        self.stop_web(run,strict=False)
        if self.fixture is None:self.fixture=Fixture(self.config,run)
        return self.fixture.restore(snapshot)


def pcap_count(path):
    count=0
    with Path(path).open('rb') as stream:
        header=stream.read(24)
        if len(header)!=24 or header[:4] not in (b'\xd4\xc3\xb2\xa1',b'M<\xb2\xa1') or struct.unpack('<I',header[20:24])[0]!=1:raise ValueError('Expected little-endian Ethernet pcap')
        while record:=stream.read(16):
            if len(record)!=16:raise ValueError('Truncated packet record')
            _,_,size,original=struct.unpack('<IIII',record)
            if size>65535 or size>original or len(stream.read(size))!=size:raise ValueError('Invalid captured frame')
            count+=1
    return count
