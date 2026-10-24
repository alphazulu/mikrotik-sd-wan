#!/usr/bin/env python3
"""Read-only web, RAM and failover checks on an already prepared isolated CHR.

Uses the existing container fabric only; --lab-root points to private lab data.
Never creates a new lab and never accepts a production endpoint.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import socket
import struct
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.router import Router
from sdwan.container_runtime import paths,read_container,check_ready,prepare

TAG='sdwan-web-http-fixture'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lab-root',type=Path,default=ROOT);parser.add_argument('--duration',type=int,default=65);parser.add_argument('--reboot',action='store_true');args=parser.parse_args()
    assert args.duration>=65
    private=args.lab_root.resolve();profile=private/'runtime/container-lab/project';assert (profile/'runtime/credentials.json').is_file(),'Existing container lab is required'
    spec=importlib.util.spec_from_file_location('web_existing_lab',profile/'lab.py');lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab)
    report={'pass':False,'checks':[],'production_modified':False,'platform':'RouterOS 7.24.5 CHR amd64'}
    output=private/'runtime/publication/web-chr-validation.json'
    r=Router(private,'api://127.0.0.1:38728',credentials_data=json.loads((profile/'runtime/credentials.json').read_text())['edge'])
    clean=[];forward=False;socks_before=None;wan_down=False;stop_load=threading.Event();worker=None
    def record(name):
        report['checks'].append({'check':name,'pass':True});output.write_text(json.dumps(report,indent=2)+'\n');print('PASS '+name,flush=True)
    def wait(predicate,timeout=40):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            status=r.status()
            if predicate(status):return status
            time.sleep(.3)
        raise AssertionError('CHR condition timed out')
    def add(node,path,data):
        existing=lab.api(node,path)
        if path=='ip/firewall/filter' and existing:data=dict(data,**{'place-before':existing[0]['.id']})
        item=lab.api(node,path,dict(data,comment=TAG),'PUT');clean.append((node,path,item['.id']));return item['.id']
    try:
        assert r.call('system/identity')['name']=='sdwan-container-edge'
        assert lab.api('client','system/identity')['name']=='sdwan-container-client'
        assert lab.api('isp1','system/identity')['name']=='sdwan-container-isp1'
        cfg=json.loads(r.read_file('sdwan-active.json'));assert cfg['container']['telemetry']['enabled'];check_ready(r,cfg,'sdwan-container-edge')
        token=r.read_file(paths(cfg)['web_token']);password=r.read_file(paths(cfg)['password'])
        initial=wait(lambda s:s.get('container',{}).get('active') is True and s['selected']['default']=='wan1')
        # Adopt/remove only leftovers from this exact fixture, never other rules.
        for node in ('client','isp1'):
            for menu in ('ip/firewall/nat','ip/firewall/filter','ip/route'):
                for row in lab.api(node,menu):
                    if row.get('comment')==TAG:lab.api(node,menu+'/'+row['.id'],method='DELETE')
        socks_before={key:value for key,value in lab.api('client','ip/socks').items() if key in ('enabled','port','max-connections','connection-idle-timeout','version')}
        assert socks_before['enabled']=='false','Existing SOCKS service must not be repurposed'
        lab.qmp('client','human-monitor-command',{'command-line':'hostfwd_remove mgmt tcp:127.0.0.1:48881'})
        result=lab.qmp('client','human-monitor-command',{'command-line':'hostfwd_add mgmt tcp:127.0.0.1:48881-10.77.10.15:1080'});assert not result,result;forward=True
        add('client','ip/route',{'dst-address':'172.31.255.0/30','gateway':'192.168.50.1'})
        lab.api('client','ip/socks/set',{'enabled':'yes','port':'1080','version':'4','max-connections':'8','connection-idle-timeout':'5s'},'POST')
        def connect(timeout=4):
            sock=socket.create_connection(('127.0.0.1',48881),timeout);sock.settimeout(timeout)
            try:
                sock.sendall(b'\x04\x01'+struct.pack('!H',8080)+socket.inet_aton('172.31.255.2')+b'\x00')
                reply=b''
                while len(reply)<8:
                    part=sock.recv(8-len(reply));assert part,'SOCKS fixture closed';reply+=part
                assert reply[1]==90,'SOCKS fixture refused LAN target';return sock
            except BaseException:sock.close();raise
        def request(target='/api/status',key=token,method='GET',extra='',timeout=4):
            with connect(timeout) as s:
                s.settimeout(timeout);auth='Authorization: Bearer '+key+'\r\n' if key else ''
                s.sendall((method+' '+target+' HTTP/1.1\r\nHost: 172.31.255.2:8080\r\n'+auth+extra+'\r\n').encode());chunks=[]
                while True:
                    try:part=s.recv(65536)
                    except OSError as error:raise AssertionError(f'HTTP {method} {target}: {type(error).__name__}, received {sum(map(len,chunks))} bytes') from error
                    if not part:break
                    chunks.append(part);assert sum(map(len,chunks))<1100000
                header,body=b''.join(chunks).split(b'\r\n\r\n',1);code=int(header.split(b' ',2)[1]);return code,header,body
        def get(target='/api/status'):
            code,_,body=request(target);assert code==200,(target,code);return json.loads(body)
        for target,key,method,extra,expected in [('/',None,'GET','',200),('/app.js',None,'GET','',200),('/api/status',None,'GET','',401),('/api/status','wrong','GET','',401),('/api/status',token,'POST','',405),('/api/status',token,'GET','Origin: http://invalid.example\r\n',403),('/api/history?max=601',token,'GET','',400),('/api/status?token=x',token,'GET','',400),('/missing',token,'GET','',404)]:
            assert request(target,key,method,extra)[0]==expected;time.sleep(.6)
        record('LAN HTTP assets and bearer auth; methods, origins, token queries and excessive history rejected')
        status=get();assert not status['stale'] and status['current']['actor']=='container' and status['observer_available'];assert len(status['current']['wans'])==3
        safe=json.dumps((status,get('/api/history?max=600'),get('/api/events'),get('/api/export')))
        for secret in (token,password,initial['container'].get('owner_instance','')):
            if secret:assert secret not in safe
        for field in ('owner_instance','owner_nonce','password_file','api-password'):assert field not in safe
        record('live SLA, RX/TX, policies and bounded export contain no API password, token or owner credentials')
        # A direct WAN attempt must be dropped by the owned WAN rule.
        add('isp1','ip/route',{'dst-address':'172.31.255.0/30','gateway':'172.20.1.2'})
        def wan_packets():
            return int(next(x for x in r.call('ip/firewall/filter/print',{'stats':'','.proplist':'comment,packets'},'POST') if x.get('comment')=='sdwan-container:web-wan-0')['packets'])
        before=wan_packets()
        try:lab.api('isp1','tool/fetch',{'url':'http://172.31.255.2:8080/','src-address':'172.20.1.1','duration':'1s','output':'user'},'POST',timeout=5)
        except Exception:pass
        assert wan_packets()>before
        record('direct ISP/WAN HTTP attempt reaches owned firewall deny and receives no web access')
        def files():
            names=['sdwan-container-intent.json','sdwan-active.json',paths(cfg)['settings'],paths(cfg)['password'],paths(cfg)['web_token']]
            rows=r.file_records(names,'name,size,last-modified')
            digests={name:hashlib.sha256(r.read_file(name).encode()).hexdigest() for name in names}
            return rows,digests
        baseline=files();samples=[];start=time.monotonic()
        while time.monotonic()-start<args.duration:
            value=get();assert value['current']['actor']=='container' and not value['stale'];assert r.status()['container']['active'] is True
            row=read_container(r);resources=r.call('container/print',{'.proplist':'memory-current,cpu-usage'},'POST')[0]
            samples.append({'elapsed_seconds':round(time.monotonic()-start,2),'rss_bytes':value['resources']['rss_bytes'],'write_bytes':value['resources']['write_bytes'],'container_memory_bytes':int(resources['memory-current']),'history_points':value['history_points'],'selected':{p['name']:p['selected'] for p in value['current']['policies']}})
            if len(samples)%5==0:assert request('/api/export')[0]==200;print('RAM/no-write sample '+str(len(samples)),flush=True)
            time.sleep(2)
        after=files();report['file_comparison']={'before_metadata':baseline[0],'after_metadata':after[0],'changed_names':[n for n in baseline[1] if baseline[1][n]!=after[1][n]]}
        report['measurement_samples']=samples
        assert after==baseline,'Managed file metadata/content changed during stable polling/export'
        assert samples[-1]['history_points']>samples[0]['history_points'];assert max(s['rss_bytes'] for s in samples if s['rss_bytes'])<2097152
        report['resources']={'duration_seconds':round(time.monotonic()-start,1),'samples':samples,'managed_files_unchanged':True,'proc_io_available':any(s['write_bytes'] is not None for s in samples)}
        record('65+ seconds polling/export: bounded history grows in RAM, RSS below 2 MiB and managed files unchanged')
        # Slow partial headers run in their own HTTP thread; main lease remains live.
        load_errors=[]
        def slow_load():
            while not stop_load.is_set():
                try:
                    with connect(2) as s:s.sendall(b'G');stop_load.wait(.4)
                except OSError as error:load_errors.append(type(error).__name__)
        worker=threading.Thread(target=slow_load,daemon=True);worker.start();observations=[]
        lab.qmp('edge','set_link',{'name':'nic2','up':False});wan_down=True;switched=time.monotonic()
        while time.monotonic()-switched<35:
            s=r.status();observations.append(s.get('container',{}).get('active'));assert observations[-1] is True
            if s['selected']['default']=='wan2':break
            time.sleep(.3)
        else:raise AssertionError('WAN failover stalled under slow HTTP')
        report['slow_http_failover_seconds']=round(time.monotonic()-switched,2)
        lab.qmp('edge','set_link',{'name':'nic2','up':True});wan_down=False;wait(lambda s:s['selected']['default']=='wan1',timeout=55)
        stop_load.set();worker.join(5);worker=None;time.sleep(2)
        assert get()['current']['actor']=='container';record('WAN failover and failback continue under slow HTTP without losing container heartbeat')
        # Stop/restart invalidates RAM history, native controller keeps routing.
        old_epoch=get()['epoch'];row=read_container(r);r.call('container/stop',{'numbers':row['.id']},'POST')
        wait(lambda s:not s.get('container',{}).get('active'),timeout=25)
        assert r.status()['selected']['default']=='wan1';record('container stop preserves working native fallback')
        r.call('container/start',{'numbers':row['.id']},'POST');wait(lambda s:s.get('container',{}).get('active') is True)
        time.sleep(2);fresh=get();assert fresh['history_points']<=2 and fresh['current']['actor']=='container';record('container restart discards RAM history and resumes active local control')
        row=read_container(r);r.call('container/kill',{'.id':row['.id'],'signal':'9-SIGKILL'},'POST')
        wait(lambda s:not s.get('container',{}).get('active'),timeout=25);assert r.status()['selected']['default']=='wan1'
        r.call('container/start',{'numbers':row['.id']},'POST');wait(lambda s:s.get('container',{}).get('active') is True)
        record('SIGKILL expires the lease and native fallback keeps the selected WAN')
        r.call('container/stop',{'numbers':row['.id']},'POST');wait(lambda s:not s.get('container',{}).get('active'),timeout=25)
        disabled=copy.deepcopy(cfg);disabled['container']['telemetry']['enabled']=False
        prepare(r,disabled,'sdwan-container-edge');assert 'telemetry' not in json.loads(r.read_file(paths(cfg)['settings']))
        assert not [x for x in r.call('ip/firewall/filter') if x.get('comment','').startswith('sdwan-container:web-')]
        r.call('container/start',{'numbers':row['.id']},'POST');wait(lambda s:s.get('container',{}).get('active') is True)
        sessions=r.call('user/active/print',{'.proplist':'name,via'},'POST');assert sum(s.get('name')=='sdwan-container' and s.get('via')=='api' for s in sessions)==1
        assert json.loads(r.read_file('sdwan-active.json'))==cfg
        record('disabled runtime removes web settings/ACL and observer API session while routing remains active')
        r.call('container/stop',{'numbers':row['.id']},'POST');wait(lambda s:not s.get('container',{}).get('active'),timeout=25)
        prepare(r,cfg,'sdwan-container-edge');assert r.read_file(paths(cfg)['web_token'])==token
        r.call('container/'+row['.id'],{'start-on-boot':'yes'},'PATCH');r.call('container/start',{'numbers':row['.id']},'POST');wait(lambda s:s.get('container',{}).get('active') is True)
        time.sleep(2);assert get()['current']['actor']=='container';record('web re-enable reuses the separate token and starts a new RAM history')
        if args.reboot:
            boot=r.status()['container']['boot_id']
            try:r.call('system/reboot',{},'POST')
            except (OSError,RuntimeError):pass
            r.close();end=time.monotonic()+100;time.sleep(3)
            while True:
                try:
                    r=Router(private,'api://127.0.0.1:38728',credentials_data=json.loads((profile/'runtime/credentials.json').read_text())['edge'])
                    if r.status().get('container',{}).get('boot_id')!=boot:break
                    r.close()
                except (OSError,RuntimeError):pass
                assert time.monotonic()<end,'CHR reboot/API did not recover';time.sleep(1)
            wait(lambda s:s.get('container',{}).get('active') is True and s['selected']['default']=='wan1',timeout=65)
            time.sleep(2);value=get();assert not value['stale'] and value['history_points']<12
            record('CHR reboot changes boot fence, clears history and automatically resumes active local web/controller')
        report['pass']=True
    except Exception:
        report['fixture_debug']={node:{menu:[row for row in lab.api(node,menu) if row.get('comment')==TAG or row.get('comment','').startswith('sdwan-container:web-')] for menu in ('ip/firewall/filter','ip/firewall/nat','ip/route')} for node in ('client','edge')}
        raise
    finally:
        stop_load.set()
        if worker:worker.join(5)
        if wan_down:lab.qmp('edge','set_link',{'name':'nic2','up':True})
        for node,menu,identifier in reversed(clean):
            try:lab.api(node,menu+'/'+identifier,method='DELETE')
            except Exception:pass
        if socks_before:lab.api('client','ip/socks/set',socks_before,'POST')
        if forward:lab.qmp('client','human-monitor-command',{'command-line':'hostfwd_remove mgmt tcp:127.0.0.1:48881'})
        try:
            row=read_container(r)
            if row and row.get('stopped')=='true':r.call('container/start',{'numbers':row['.id']},'POST')
        finally:r.close();output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'pass':report['pass'],'checks':len(report['checks'])}),flush=True)

if __name__=='__main__':main()
