#!/usr/bin/env python3
"""Actual USB RNDIS/LTE SD-WAN acceptance on the explicitly owned x86 L6 lab.

No inventory substitution. Fixed loopback endpoints and QMP identity guards
prevent this driver from targeting a production router or another lab.
"""
import argparse
import contextlib
import copy
import fcntl
import http.server
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import threading
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from sdwan.config import load,validate
from sdwan.router import Router
from vpn_traffic import Flow,same_path,tcp_stream

PREFIX='lte-rndis-acceptance'
PROFILE='sdwan-test-rndis'
BASE_IMAGE='a98ff28196c2ac187d89a285c511f99faa128c3279fe0fd6ef06d219231e677e'


def qmp(port,name,command='query-name',arguments=None):
    with socket.create_connection(('127.0.0.1',port),3) as sock:
        sock.settimeout(3);stream=sock.makefile('rwb');stream.readline()
        result=None
        for operation in [{'execute':'qmp_capabilities'},{'execute':'query-name'}]+([] if command=='query-name' else [{'execute':command,'arguments':arguments or {}}]):
            stream.write(json.dumps(operation).encode()+b'\n');stream.flush()
            while True:
                value=json.loads(stream.readline())
                if 'event' not in value:break
            assert 'error' not in value,value
            result=value['return']
            if operation['execute']=='query-name':assert result['name']==name
        return result


class Fixture:
    def __init__(self,root):
        self.root=root;self.run=root/'runtime/x86-lte-lab/runtime'
        self.created=[];self.restore=[];self.servers=[];self.flows=[];self.remotes={};self.hostforwards=[]
        self.stop=threading.Event();self.routers={};self.applied=False;self.cleanup_armed=False
        self.report={'pass':False,'inventory_adapter':False,'production_modified':False,'checks':[],
                     'adapter_source_sha256':hashlib.sha256((ROOT/'sdwan/container_backend.py').read_bytes()).hexdigest(),
                     'native_sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'native').glob('*.rsc'))}}
    def record(self,name,**evidence):
        self.report['checks'].append({'check':name,'pass':True,**evidence})
        print('PASS '+name,flush=True)
    def add(self,r,menu,values):
        data=dict(values)
        if menu not in ('interface/lte/apn',):data['comment']=PREFIX
        row=r.call(menu,data,'PUT');self.created.append((r,menu,row['.id']))
        if menu in ('ip/firewall/nat','ip/firewall/mangle'):
            deadline=time.monotonic()+15
            while row.get('invalid') in (True,'true','yes','1'):
                if time.monotonic()>deadline:raise AssertionError({'invalid_fixture_rule':row})
                time.sleep(.1);row=r.call(menu+'/'+row['.id'])
        return row['.id']
    def change(self,r,menu,row,values):
        previous={key:row[key] if key in row else r.call(menu+'/get',{'number':row['.id'],'value-name':key},'POST')['ret'] for key in values}
        self.restore.append((r,menu,row['.id'],previous))
        r.call(menu+'/'+row['.id'],values,'PATCH')
    def gate(self,state):
        request=urllib.request.Request('http://127.0.0.1:24321/lte',data=json.dumps({'registration_status':state}).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(request,timeout=3) as reply:result=json.load(reply)
        assert result['registration_status']==state and result['gate'] is True
        assert result['forwarding']==(state in ('registered','roaming')),'Emulator did not apply the requested data-plane fault'
        return result
    def connect(self):
        self.lock=(self.run/'lab.lock').open('a');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for node,qport,port,name,identity in [('x86',24400,24404,'sdwan-x86-lte','MikroTik'),('isp',24410,24414,'sdwan-lte-isp','sdwan-lte-isp'),('chr',24420,24424,'sdwan-lte-chr','sdwan-lte-chr')]:
            qmp(qport,name)
            file='credentials.json' if node=='x86' else node+'-credentials.json'
            r=Router(self.root/'runtime/x86-lte-lab','api://127.0.0.1:'+str(port),credentials_data=json.loads((self.run/file).read_text()))
            assert r.call('system/identity')['name']==identity
            self.routers[node]=r
        self.a=self.routers['x86'];self.n=self.routers['isp'];self.c=self.routers['chr']
        assert self.a.call('system/license')[0]['nlevel']=='6'
        assert not self.a.call('system/scheduler?name=sdwan-controller'),'Existing controller must be restored before this isolated test'
        assert not self.a.file_entry('sdwan-backup.json'),'Existing SD-WAN baseline must not be adopted by this test'
        self.before_files={row['name'] for row in self.a.call('file/print',{'.proplist':'name'},'POST')}
        assert not any(row.get('name')==PROFILE for row in self.a.call('interface/lte/apn'))
        self.cleanup_armed=True
        self.gate('registered')
        self.record('owned QMP names, loopback API identities and unchanged x86 L6 license verified')
    def prepare(self):
        # Keep the image's unrelated lte2/default profile untouched. APN and DNS
        # preparation are explicit fixture setup, not hidden product mutation.
        dns=self.a.call('ip/dns');dns=dns[0] if isinstance(dns,list) else dns
        original=dns.get('servers','')
        self.restore.append((self.a,'ip/dns',None,{'servers':original}))
        self.a.call('ip/dns/set',{'servers':'10.79.0.3'},'POST')
        self.add(self.a,'interface/lte/apn',{'name':PROFILE,'apn':'internet','add-default-route':'true','default-route-distance':'13','use-peer-dns':'false','use-network-apn':'false','ip-type':'ipv4'})
        radio=next(row for row in self.a.call('interface/lte') if row['name']=='lte1')
        self.change(self.a,'interface/lte',radio,{'apn-profiles':PROFILE})
        client=next(row for row in self.a.call('ip/dhcp-client') if row['interface']=='ether3')
        self.change(self.a,'ip/dhcp-client',client,{'add-default-route':'no'})
        # Earlier standalone emulator proof routes must not mask SD-WAN probes.
        for row in self.a.call('ip/route'):
            if row.get('comment')=='lte-emulator-test':self.change(self.a,'ip/route',row,{'disabled':'true'})
        self.add(self.n,'ip/firewall/nat',{'chain':'dstnat','dst-address':'198.18.79.0/30','protocol':'tcp','dst-port':'24440-24459','action':'dst-nat','to-addresses':'10.80.0.2'})
        self.server(24440);self.server(24441);self.server(24442)
        spec=importlib.util.spec_from_file_location('lte_rndis_cli',ROOT/'sdwan.py');self.cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.cli)
        self.cfg=load(ROOT/'config/sdwan.json');self.cfg['revision']='real-rndis-lte'
        self.cfg['wans']=[]
        for name,iface,extra in [('lte','lte1',{'kind':'lte','apn_profile':PROFILE}),('wan2','ether4',{'address':'192.0.3.2','gateway':'192.0.3.1'})]:
            self.cfg['wans'].append(dict(name=name,interface=iface,probe_table='sdwan-probe-'+name,icmp_target='198.18.79.1',probes=[{'name':label,'type':'http-get','host':'198.18.79.1','port':24440+i} for i,label in enumerate('abc')],masquerade=True,allow_selected_forward=True,**extra))
        self.cfg['local_networks']=['192.168.79.0/24','10.79.0.0/24','172.31.255.0/30']
        self.cfg['sla_profiles']={'default':{'rtt_ms':150,'jitter_ms':100,'loss_percent':2}}
        self.cfg['policies']=[{'name':name,'source':source,'table':table,'profile':'default','mode':mode,'wans':wans,'allow_degraded':False} for name,source,table,mode,wans in [('default','','main','prefer',['lte','wan2']),('client','192.168.79.2/32','sdwan-client','prefer',['lte','wan2']),('fixed','192.168.79.3/32','sdwan-fixed','strict',['wan2'])]]
        self.cfg['takeover_route_comments']=[];self.cfg['takeover_rule']={'src-address':'','table':''}
        validate(self.cfg)
    def server(self,port,stats=None):
        owner=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if stats is None:
                    self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok');return
                stats['requests']+=1;stats['active']+=1
                try:
                    self.send_response(200);self.send_header('Content-Length','100000000');self.end_headers()
                    while not owner.stop.wait(.2):self.wfile.write(b'x'*256);self.wfile.flush()
                except (OSError,ConnectionError):pass
                finally:stats['active']-=1
        server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
        self.servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
    def resolver(self):
        # The production library is imported byte for byte, without adapters.
        name=PREFIX+'-resolver.rsc';result=PREFIX+'-result.json'
        self.a.upload(result,'{}')
        source=(ROOT/'native/sdwan-links.rsc').read_text()+'\n:local specs [:deserialize from=json options=json.no-string-conversion value='+json.dumps(json.dumps(self.cfg['wans']))+']\n:local result [$sdwanResolveWANs wans=$specs]\n/file/set [/file/find where name="'+result+'"] contents=[:serialize to=json value=$result options=json.no-string-conversion]\n'
        self.a.upload(name,source)
        apn=next(row for row in self.a.call('interface/lte/apn') if row['name']==PROFILE)
        try:
            self.a.call('interface/lte/apn/'+apn['.id'],{'add-default-route':'false'},'PATCH')
            deadline=time.monotonic()+85
            while True:
                self.a.call('import',{'file-name':name},'POST')
                rows=json.loads(self.a.read_file(result));lte=next(row for row in rows if row['name']=='lte')
                if lte['ready']:break
                if time.monotonic()>deadline:
                    self.report['lease_diagnostic']=self.a.call('ip/dhcp-client/print',{'.proplist':'interface,dynamic,status,address,gateway'},'POST')
                    self.report['address_diagnostic']=self.a.call('ip/address/print',{'.proplist':'interface,address,dynamic,invalid,disabled'},'POST')
                    raise AssertionError(rows)
                time.sleep(1)
            assert lte['gateway']=='192.0.2.1' and lte['route_gateway']=='192.0.2.1%lte1@main',rows
            self.record('unmodified native resolver reads actual RouterOS-owned RNDIS lease gateway',result=rows)
        finally:self.a.call('interface/lte/apn/'+apn['.id'],{'add-default-route':'true'},'PATCH')
    def wait(self,predicate,timeout=85):
        deadline=time.monotonic()+timeout;state={}
        while time.monotonic()<deadline:
            state=self.a.status()
            if predicate(state):return state
            time.sleep(.3)
        raise AssertionError({'timeout_state':state})
    def selected_settled(self,wan):
        since=None;last=None
        def stable(s):
            nonlocal since,last
            eligible=s.get('selected',{}).get('client')==wan and s.get('selected',{}).get('default')==wan
            signature=json.dumps({'selected':s.get('selected'),'cleanup':s.get('last_cleanup')},sort_keys=True)
            if not eligible or signature!=last:since=time.monotonic();last=signature
            return eligible and since is not None and time.monotonic()-since>=6
        return self.wait(stable)
    def apply(self,backend):
        cfg=copy.deepcopy(self.cfg)
        if backend=='container':
            template=json.loads((self.run/'sdwan-container-test-config.json').read_text())
            cfg.update(controller_backend='container',container=template['container'])
            row=next(row for row in self.a.call('container') if row['name']=='sdwan-container-controller')
            assert row.get('image-id','').removeprefix('sha256:')==BASE_IMAGE,row.get('image-id')
            self.report['container_image_id']=BASE_IMAGE
        self.applied=True
        with contextlib.redirect_stdout(io.StringIO()):self.cli.apply(self.a,cfg,'MikroTik')
        with tempfile.TemporaryDirectory(prefix='rndis-source-proof-') as directory:
            payload=self.cli.bundle(cfg,Path(directory));digests={}
            for name in ('sdwan-controller.rsc','sdwan-install.rsc','sdwan-deploy-watchdog.rsc'):
                actual=self.a.read_file(name);expected=(payload/name).read_text()
                assert actual==expected,'Installed runtime differs from tested source: '+name
                digests[name]=hashlib.sha256(actual.encode()).hexdigest()
            self.report.setdefault('generated_sources',{})[backend]=digests
            scripts=self.a.call('system/script/print',{'.proplist':'name,source','.query':['name=sdwan-controller']},'POST')
            assert len(scripts)==1 and scripts[0]['source']==(payload/'sdwan-controller.rsc').read_text(),'Active controller script differs from uploaded source'
        if backend=='container':
            row=next(row for row in self.a.call('container') if row['name']=='sdwan-container-controller')
            if row.get('running')!='true':self.a.call('container/start',{'numbers':row['.id']},'POST')
        # APN reassignment restarts the real USB data session asynchronously.
        # A first admitted sample is not proof that installation has settled;
        # do not launch the continuity stream inside a legitimate warmup switch.
        since=None;last=None
        def settled(s):
            nonlocal since,last
            eligible=s.get('selected',{}).get('client')=='lte' and s.get('selected',{}).get('fixed')=='wan2' and (backend!='container' or s.get('container',{}).get('active') is True) and bool(s.get('states')) and all(row.get('state')=='healthy' for row in s['states'].values())
            signature=json.dumps({'selected':s.get('selected'),'cleanup':s.get('last_cleanup')},sort_keys=True)
            if not eligible or signature!=last:since=time.monotonic();last=signature
            return eligible and since is not None and time.monotonic()-since>=6
        state=self.wait(settled,120)
        sample=state['samples']['lte'];assert sample['gateway']=='192.0.2.1' and sample['link_ready']
        active=json.loads(self.a.read_file('sdwan-active.json'));wan=active['wans'][0];assert 'address' not in wan and 'gateway' not in wan
        self.record(backend+' install admits LTE after fresh SLA, using lease gateway without saving a lease snapshot',selected=state['selected'])
    def ingress(self):
        lte_address=next(row['address'].split('/')[0] for row in self.a.call('ip/address') if row['interface']=='lte1')
        for wan,address,interface,port in [('lte',lte_address,'ether2',24460),('wan2','192.0.3.2','ether3',24461)]:
            with socket.socket() as sock:sock.bind(('127.0.0.1',port))
            rule=f'tcp:127.0.0.1:{port}-10.80.0.15:{port}'
            result=qmp(24410,'sdwan-lte-isp','human-monitor-command',{'command-line':'hostfwd_add mgmt '+rule});assert not result,result
            self.hostforwards.append(port)
            self.add(self.n,'ip/firewall/nat',{'chain':'dstnat','in-interface':'ether1','protocol':'tcp','dst-port':str(port),'action':'dst-nat','to-addresses':address,'to-ports':'8728'})
            self.add(self.n,'ip/firewall/nat',{'chain':'srcnat','out-interface':interface,'dst-address':address,'protocol':'tcp','dst-port':'8728','action':'src-nat','to-addresses':'198.18.79.1'})
            counter=self.add(self.n,'ip/firewall/mangle',{'chain':'prerouting','in-interface':interface,'src-address':address,'dst-address':'198.18.79.1','protocol':'tcp','src-port':'8728','action':'passthrough'})
            deadline=time.monotonic()+15;stable=None
            while True:
                invalid=[]
                for menu in ('ip/firewall/nat','ip/firewall/mangle'):
                    invalid += [row for row in self.n.call(menu+'/print',{'.proplist':'.id,invalid,comment'},'POST') if row.get('comment')==PREFIX and row.get('invalid') in (True,'true','yes','1')]
                now=time.monotonic()
                if invalid:stable=None
                elif stable is None:stable=now
                elif now-stable>=1:break
                if now>deadline:raise AssertionError({'fixture_rules_not_ready':invalid})
                time.sleep(.1)
            remote=Router(self.root/'runtime/x86-lte-lab','api://127.0.0.1:'+str(port),credentials_data=self.a._credentials)
            self.remotes[wan]=remote;assert remote.call('system/identity')['name']=='MikroTik'
            # The API session can answer before its conntrack row is published
            # to another API reader. Require the real tuple, not a fixed sleep.
            deadline=time.monotonic()+10
            while True:
                rows=[row for row in self.connections() if row.get('src-address')=='198.18.79.1' and row.get('dst-address')==address and row.get('dst-port')=='8728' and row.get('connection-mark')=='sdwan-in-'+wan and row.get('tcp-state')=='established' and row.get('seen-reply')=='true']
                if len(rows)==1:break
                if time.monotonic()>deadline:break
                assert remote.call('system/identity')['name']=='MikroTik'
                time.sleep(.1)
            if len(rows)!=1:
                self.report['ingress_diagnostic']={'wan':wan,'endpoint':remote.base_url,'peer':remote.native.sock.getpeername(),'local':remote.native.sock.getsockname(),
                    'dut_tcp':self.a.call('ip/firewall/connection/print',{'.query':['protocol=tcp']},'POST'),
                    'isp_tcp':self.n.call('ip/firewall/connection/print',{'.query':['protocol=tcp']},'POST'),
                    'isp_nat':self.n.call('ip/firewall/nat/print',{'stats':''},'POST'),
                    'dut_rules':self.a.call('ip/firewall/mangle/print',{'stats':''},'POST'),
                    'state':self.a.status(),
                    'logins':[row for row in self.a.call('log') if 'logged in' in row.get('message','')][-5:]}
            assert len(rows)==1 and rows[0]['seen-reply']=='true',rows
            counter_row=next(row for row in self.n.call('ip/firewall/mangle/print',{'stats':'','.proplist':'.id,packets'},'POST') if row['.id']==counter)
            assert int(counter_row['packets'])>0,'API replies did not arrive on their actual WAN interface'
            if wan=='wan2':self.incoming_backup=dict(rows[0])
        self.record('real incoming API via both WAN IPs replies on matching physical interfaces despite LTE outbound preference')
    def connections(self):
        return self.a.call('ip/firewall/connection/print',{'.proplist':'.id,src-address,src-port,dst-address,dst-port,reply-src-address,reply-src-port,reply-dst-address,reply-dst-port,connection-mark,tcp-state,seen-reply,orig-bytes,repl-bytes'},'POST')
    def stream(self,port,source,mark):
        stats={'requests':0,'active':0};self.server(port,stats)
        name=PREFIX+'-'+str(port)
        script=self.add(self.c,'system/script',{'name':name,'source':f':execute {{ /tool/fetch url="http://198.18.79.2:{port}/stream" src-address={source} output=none idle-timeout=60s }}','policy':'read,write,policy,test'})
        self.flows.append(name);self.c.call('system/script/run',{'number':script},'POST')
        end=time.monotonic()+25;rows=[];history=[]
        while time.monotonic()<end:
            all_rows=self.connections();port_rows=[row for row in all_rows if row.get('dst-port')==str(port)]
            brief=[{key:row.get(key) for key in ('src-address','connection-mark','tcp-state','seen-reply','reply-dst-address')} for row in port_rows]
            if not history or brief!=history[-1]:history.append(brief)
            rows=[row for row in port_rows if row.get('src-address')==source]
            matched=[row for row in rows if row.get('tcp-state')=='established' and row.get('seen-reply')=='true' and row.get('connection-mark')==mark]
            if len(matched)==1 and stats['requests']==1 and stats['active']==1:return Flow(matched[0],stats)
            time.sleep(.2)
        diagnostic=[row for row in self.a.call('ip/firewall/connection') if str(port) in json.dumps(row)]
        self.report['stream_diagnostic']={'raw_port_rows':diagnostic,'observed_paths':history,'state':self.a.status()}
        raise AssertionError({'flows':rows,'raw_port_rows':diagnostic,'stats':dict(stats),'expected':mark})
    def continuity(self,retired,retained):
        end=time.monotonic()+20;before=int(retained.last['repl-bytes'])
        before_incoming=int(self.incoming_backup['repl-bytes'])
        assert self.remotes['wan2'].call('system/identity')['name']=='MikroTik'
        while time.monotonic()<end:
            rows=self.connections();current=tcp_stream(retained.last,rows)
            incoming=tcp_stream(self.incoming_backup,rows)
            assert retained.http['requests']==1 and retained.http['active']==1
            if not any(same_path(retired,row) for row in rows) and int(current['repl-bytes'])>before and int(incoming['repl-bytes'])>before_incoming:
                retained.last=dict(current);self.incoming_backup=dict(incoming);return
            time.sleep(.2)
        raise AssertionError('Affected tuple was not retired, or unrelated TCP stopped growing')
    def traffic(self,backend,offset):
        first=self.stream(24443+offset,'192.168.79.2','sdwan-out-client:lte')
        fixed=self.stream(24444+offset,'192.168.79.3','sdwan-out-fixed:wan2')
        assert first.snapshot['reply-dst-address'].startswith('192.0.2.') and fixed.snapshot['reply-dst-address']=='192.0.3.2'
        closed=self.gate('searching')
        self.wait(lambda s:s.get('selected',{}).get('client')=='wan2' and s.get('selected',{}).get('default')=='wan2')
        self.continuity(first,fixed)
        self.selected_settled('wan2')
        fallback=self.stream(24445+offset,'192.168.79.2','sdwan-out-client:wan2')
        assert fallback.snapshot['reply-dst-address']=='192.0.3.2'
        with urllib.request.urlopen('http://127.0.0.1:24321/lte',timeout=3) as reply:blocked=json.load(reply)
        assert blocked['forwarding'] is False and blocked['counters']['dropped']>closed['counters']['dropped']
        self.record(backend+' LTE data blackhole switches real TCP/NAT to backup; only affected tuple retires',emulator_dropped_frames=blocked['counters']['dropped']-closed['counters']['dropped'])
        self.gate('registered')
        self.wait(lambda s:s.get('selected',{}).get('client')=='lte' and s.get('selected',{}).get('default')=='lte')
        self.continuity(fallback,fixed)
        self.selected_settled('lte')
        restored=self.stream(24446+offset,'192.168.79.2','sdwan-out-client:lte')
        assert restored.snapshot['reply-dst-address'].startswith('192.0.2.')
        self.remotes['lte'].close();remote=self.remotes['lte'].fresh();self.remotes['lte']=remote
        assert remote.call('system/identity')['name']=='MikroTik'
        self.record(backend+' fresh-SLA failback restores LTE TCP/NAT and incoming API; strict backup TCP/HTTP and original incoming backup API survive')
    def rollback(self):
        if self.applied:
            forwarding_errors=[]
            for remote in self.remotes.values():remote.close()
            self.remotes={}
            for port in self.hostforwards:
                try:
                    result=qmp(24410,'sdwan-lte-isp','human-monitor-command',{'command-line':f'hostfwd_remove mgmt tcp:127.0.0.1:{port}'})
                    assert not result or ('host forwarding rule' in result and 'removed' in result),result
                except Exception as error:forwarding_errors.append(str(error))
            self.hostforwards=[]
            with contextlib.redirect_stdout(io.StringIO()):self.cli.rollback(self.a,'MikroTik')
            self.applied=False
            apn=next(row for row in self.a.call('interface/lte/apn') if row['name']==PROFILE)
            assert apn['add-default-route']=='true' and apn['default-route-distance']=='13' and apn['use-peer-dns']=='false'
            self.record('protected baseline rollback restores actual APN automatic default and distance')
            # Each backend starts from this fixture's original empty install.
            # A retained, already-restored APN baseline is not an active lease
            # of ownership for the next independent installation.
            for name in ('sdwan-backup.json','sdwan-active.json'):
                if name not in self.before_files:
                    entry=self.a.file_entry(name)
                    if entry:self.a.call('file/'+entry['.id'],method='DELETE')
            if forwarding_errors:raise RuntimeError('Routing restored; temporary API forwarding cleanup failed: '+str(forwarding_errors))
    def close(self):
        errors=[]
        def attempt(fn):
            try:fn()
            except Exception as error:errors.append(type(error).__name__+': '+str(error))
        if not self.cleanup_armed:
            for router in self.routers.values():router.close()
            if hasattr(self,'lock'):self.lock.close()
            self.report['cleanup']={'pass':True,'errors':[],'mutation_started':False}
            return
        attempt(lambda:self.gate('registered'))
        attempt(self.rollback)
        self.stop.set()
        if self.routers:
            for job in self.c.call('system/script/job/print',{'.proplist':'.id,trace'},'POST'):
                if any('/script:'+name+'/' in job.get('trace','') for name in self.flows):attempt(lambda job=job:self.c.call('system/script/job/'+job['.id'],method='DELETE'))
        if self.applied:
            # A failed protected rollback must retain its baseline, APN and
            # payload for recovery. Never delete those under a live controller.
            for server in self.servers:server.shutdown();server.server_close()
            for router in self.routers.values():router.close()
            self.lock.close();self.report['pass']=False
            self.report['cleanup']={'pass':False,'errors':errors,'recovery_required':True,'baseline_preserved':True}
            return
        for r,menu,id,previous in reversed(self.restore):
            attempt(lambda r=r,menu=menu,id=id,previous=previous:r.call(menu+'/'+id,previous,'PATCH') if id else r.call(menu+'/set',previous,'POST'))
        for r,menu,id in reversed(self.created):attempt(lambda r=r,menu=menu,id=id:r.call(menu+'/'+id,method='DELETE'))
        if hasattr(self,'before_files'):
            names={PREFIX+'-resolver.rsc',PREFIX+'-result.json','sdwan-backup.json','sdwan-active.json'}
            for row in self.a.call('file/print',{'.proplist':'.id,name'},'POST'):
                if row['name'] in names and row['name'] not in self.before_files:attempt(lambda row=row:self.a.call('file/'+row['.id'],method='DELETE'))
            # rollback leaves its disabled scheduler as an operator convenience;
            # this dedicated lab began without one, so restore that absence.
            for menu in ('system/scheduler','system/script'):
                for row in self.a.call(menu+'?name=sdwan-controller'):attempt(lambda menu=menu,row=row:self.a.call(menu+'/'+row['.id'],method='DELETE'))
        for server in self.servers:server.shutdown();server.server_close()
        for router in self.routers.values():router.close()
        if hasattr(self,'lock'):self.lock.close()
        self.report['cleanup']={'pass':not errors,'errors':errors}
        if errors:self.report['pass']=False


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lab-root',type=Path,required=True);parser.add_argument('--phase',choices=['resolver','native','container','all'],default='resolver');args=parser.parse_args()
    fixture=Fixture(args.lab_root.resolve());failure=None
    try:
        fixture.connect();fixture.prepare();fixture.resolver()
        if args.phase!='resolver':
            modes=['native','container'] if args.phase=='all' else [args.phase]
            for i,backend in enumerate(modes):
                fixture.apply(backend);fixture.ingress();fixture.traffic(backend,i*4);fixture.rollback()
        fixture.report['pass']=True
    except Exception as error:
        failure=error;fixture.report['error']=type(error).__name__+': '+str(error)
    finally:
        fixture.close();payload=json.dumps(fixture.report,indent=2)+'\n'
        (fixture.run/('sdwan-'+args.phase+'-'+str(time.time_ns())+'.json')).write_text(payload)
        (fixture.run/('sdwan-'+args.phase+'-validation.json')).write_text(payload)
    if failure:raise failure
    assert fixture.report['pass'],fixture.report['cleanup']
    print(json.dumps(fixture.report),flush=True)


if __name__=='__main__':main()
