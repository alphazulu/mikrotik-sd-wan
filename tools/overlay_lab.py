#!/usr/bin/env python3
"""Isolated five-CHR, dual-CGNAT overlay fixture. Never uses production exports."""
import argparse
import base64
import contextlib
import importlib.util
import fcntl
import grp
import hashlib
import http.server
import json
import os
import pwd
from pathlib import Path
import re
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import threading
import types
import urllib.request

SOURCE_ROOT=Path(__file__).resolve().parents[1]
NODES={'hub':0,'sitea':1,'siteb':2,'nata':3,'natb':4}
LINKS={'nata':[(2,53101),(3,53111),(4,53112),(5,53102)],'natb':[(2,53102),(3,53121),(4,53122)],'hub':[(2,53101)],'sitea':[(2,53111),(3,53121)],'siteb':[(2,53112),(3,53122)]}
PROBE_PORTS=(58081,58082,58083)

class Lab:
    def __init__(self,project_root):
        self.project_root=Path(project_root).resolve();self.root=self.project_root/'runtime/overlay-lab';self.run=self.root/'runtime';self.images=self.root/'images'
        # Reuse only the serial bootstrap parser and QMP codec, in a separate
        # module namespace with explicit ports. Original lab files stay intact.
        source=(SOURCE_ROOT/'lab.py').read_text().replace('25100','55100').replace('24100','54100')
        module=types.ModuleType('sdwan_overlay_bootstrap');module.__file__=str(self.root/'lab.py');exec(compile(source,str(SOURCE_ROOT/'lab.py'),'exec'),module.__dict__)
        module.ROOT=self.root;module.RUN=self.run;module.IMG=self.images;module.NODES={name:(idx,55080+idx,52222+idx,55291+idx,512 if name.startswith('nat') else 768) for name,idx in NODES.items()}
        self.bootstrap=module
    def qmp(self,node,command,args=None):return self.bootstrap.qmp(node,command,args)
    def running(self,node):
        try:
            name=self.qmp(node,'query-name').get('name')
            if name!='sdwan-overlay-'+node:raise RuntimeError('Unexpected QMP endpoint owner: '+str(name))
            return self.qmp(node,'query-status')['status']
        except (ConnectionRefusedError,TimeoutError,socket.timeout):return None
    def prepare(self):
        self.run.mkdir(parents=True,exist_ok=True);self.images.mkdir(exist_ok=True)
        backing=self.project_root/'images/chr-7.24.5.img';manifest=self.project_root/'images/manifest.json'
        assert backing.is_file() and manifest.is_file(),'Prepare the original pinned CHR image first'
        digest=hashlib.sha256(backing.read_bytes()).hexdigest();assert json.loads(manifest.read_text())['sha256'][backing.name]==digest,'Pinned base image changed'
        target=self.root/'profile.json';profile={'version':1,'base_sha256':digest,'nodes':NODES,'links':LINKS,'production_access':False}
        if target.exists():assert json.loads(target.read_text())==json.loads(json.dumps(profile)),'Overlay profile changed; inspect existing disks before migration'
        else:target.write_text(json.dumps(profile,indent=2)+'\n')
        for node in NODES:
            disk=self.images/(node+'.qcow2')
            if not disk.exists():subprocess.run(['qemu-img','create','-f','qcow2','-F','raw','-b',str(backing),str(disk),'512M'],check=True,stdout=subprocess.DEVNULL)
        credentials=self.run/'credentials.json'
        if not credentials.exists():
            credentials.write_text(json.dumps({n:{'username':'admin','password':secrets.token_urlsafe(24)} for n in NODES},indent=2)+'\n');credentials.chmod(0o600)
    def api(self,node,menu,data=None,method=None):
        credentials=json.loads((self.run/'credentials.json').read_text())[node]
        auth=base64.b64encode((credentials['username']+':'+credentials['password']).encode()).decode()
        request=urllib.request.Request(f'http://127.0.0.1:{55080+NODES[node]}/rest/'+menu,data=None if data is None else json.dumps(data).encode(),method=method,headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request,timeout=10) as response:
            body=response.read();return json.loads(body) if body else None
    def command(self,node,accel):
        idx=NODES[node];args=['qemu-system-x86_64','-name','sdwan-overlay-'+node,'-machine','q35','-accel',accel,'-cpu','host' if accel=='kvm' else 'max','-m',str(512 if node.startswith('nat') else 768),'-smp','1','-display','none','-drive',f'file={self.images/(node+".qcow2")},format=qcow2,if=virtio','-serial',f'tcp:127.0.0.1:{55100+idx},server=on,wait=off','-qmp',f'tcp:127.0.0.1:{54100+idx},server=on,wait=off','-pidfile',str(self.run/(node+'.pid')),'-daemonize','-D',str(self.run/(node+'.qemu.log'))]
        def nic(number,backend):
            args.extend(['-netdev',backend+f',id=n{number}','-device',f'virtio-net-pci,netdev=n{number},mac=52:54:00:78:{idx:02x}:{number:02x}'])
        nic(1,f'user,net=10.78.{idx}.0/24,dhcpstart=10.78.{idx}.15,ipv6=off,hostfwd=tcp:127.0.0.1:{55080+idx}-10.78.{idx}.15:80,hostfwd=tcp:127.0.0.1:{55728+idx}-10.78.{idx}.15:8728,hostfwd=tcp:127.0.0.1:{45728+idx}-10.78.{idx}.15:8728,hostfwd=tcp:127.0.0.1:{52222+idx}-10.78.{idx}.15:22,hostfwd=tcp:127.0.0.1:{55291+idx}-10.78.{idx}.15:8291')
        for number,port in LINKS[node]:nic(number,f'socket,{"listen" if node.startswith("nat") and not (node=="natb" and number==2) else "connect"}=127.0.0.1:{port}')
        if node.startswith('site'):nic(4,f'user,net=10.201.{idx}.0/24,dhcpstart=10.201.{idx}.15,ipv6=off')
        return args
    def config(self,node):
        idx=NODES[node];cmds=[f'/system identity set name=sdwan-overlay-{node}','/ip dhcp-client remove [find]',f'/ip address add address=10.78.{idx}.15/24 interface=ether1 comment=overlay-lab-management','/ip service disable [find where dynamic=no]']
        for service in ('www','api','ssh','winbox'):cmds.append(f'/ip service set [find where name={service} and dynamic=no] disabled=no')
        cmds+=['/tool mac-server set allowed-interface-list=none','/tool mac-server mac-winbox set allowed-interface-list=none','/ip neighbor discovery-settings set discover-interface-list=none','/interface list add name=WAN','/interface list add name=LAN','/ip firewall filter add chain=input connection-state=established,related action=accept','/ip firewall filter add chain=input connection-state=invalid action=drop','/ip firewall filter add chain=input in-interface=ether1 action=accept comment=overlay-lab-management','/ip firewall filter add chain=input protocol=icmp action=accept','/ip firewall filter add chain=input action=drop','/ip firewall filter add chain=forward connection-state=established,related action=accept','/ip firewall filter add chain=forward connection-state=invalid action=drop']
        if node.startswith('nat'):
            a=node=='nata';public=100 if a else 200;space='100.64' if a else '100.65'
            cmds += [f'/ip address add address=198.18.{public}.2/30 interface=ether2',f'/ip address add address={space}.10.1/30 interface=ether3',f'/ip address add address={space}.20.1/30 interface=ether4','/interface bridge add name=probe-loopback',f'/ip address add address=198.19.{public}.1/32 interface=probe-loopback']
            if a:
                cmds += ['/ip address add address=198.18.200.1/30 interface=ether5','/ip firewall filter add chain=forward in-interface=ether5 out-interface=ether2 src-address=198.18.200.2 action=accept comment=emulated-internet-transit']
            else:cmds.append('/ip route add dst-address=0.0.0.0/0 gateway=198.18.200.1 comment=emulated-internet-uplink')
            for inside in ('ether3','ether4'):cmds.append(f'/ip firewall filter add chain=forward in-interface={inside} out-interface=ether2 action=accept comment=cgnat-outbound-only')
            cmds += [f'/ip firewall nat add chain=srcnat src-address={space}.0.0/16 out-interface=ether2 action=masquerade comment=cgnat-shared-public-address',f'/ip firewall nat add chain=dstnat dst-address=198.19.{public}.1 protocol=tcp dst-port=58081-58083 action=dst-nat to-addresses=10.78.{idx}.2 comment=overlay-lab-probes',f'/ip firewall filter add chain=forward dst-address=10.78.{idx}.2 protocol=tcp dst-port=58081-58083 action=accept comment=overlay-lab-probes','/ip firewall nat add chain=srcnat out-interface=ether1 action=masquerade comment=overlay-lab-probes']
        else:
            if node=='hub':addresses=['198.18.100.1/30'];gateways=['198.18.100.2']
            else:
                subnet=10 if node=='sitea' else 20;addresses=[f'100.64.{subnet}.2/30',f'100.65.{subnet}.2/30'];gateways=[f'100.64.{subnet}.1',f'100.65.{subnet}.1']
            for number,(address,gateway) in enumerate(zip(addresses,gateways),1):
                iface='ether'+str(number+1);cmds += [f'/ip address add address={address} interface={iface}',f'/interface list member add list=WAN interface={iface}',f'/ip route add dst-address=0.0.0.0/0 gateway={gateway} distance={number} comment=baseline-wan{number}',f'/ip firewall nat add chain=srcnat out-interface={iface} action=masquerade']
            if node.startswith('site'):
                cmds += [f'/ip address add address=10.201.{idx}.1/24 interface=ether4','/interface list member add list=LAN interface=ether4','/ip firewall filter add chain=input in-interface=ether4 action=accept place-before=[find chain=input action=drop]','/ip firewall filter add chain=forward in-interface=ether4 out-interface-list=WAN action=accept']
        cmds.append('/ip firewall filter add chain=forward action=drop')
        return cmds
    def up(self,accel):
        self.prepare();lock=(self.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        available=int(next(x.split()[1] for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:')))*1024
        if not all(self.running(n) for n in NODES) and available<5*1024**3:raise RuntimeError('Insufficient host memory for separate overlay lab')
        group=grp.getgrnam('kvm');member=group.gr_gid in os.getgroups() or pwd.getpwuid(os.getuid()).pw_name in group.gr_mem
        if accel=='auto':accel='kvm' if os.access('/dev/kvm',os.R_OK|os.W_OK) or member else 'tcg'
        credentials=json.loads((self.run/'credentials.json').read_text())
        for node in ('nata','natb','hub','sitea','siteb'):
            idx=NODES[node]
            if not self.running(node):
                ports=[55080+idx,55728+idx,52222+idx,55291+idx,54100+idx,55100+idx]+([port for number,port in LINKS[node] if not (node=='natb' and number==2)] if node.startswith('nat') else [])
                for port in ports:
                    with socket.socket() as test:test.bind(('127.0.0.1',port))
                args=self.command(node,accel)
                if accel=='kvm' and group.gr_gid not in os.getgroups():args=['sg','kvm','-c',shlex.join(args)]
                subprocess.run(args,check=True)
            marker=self.run/(node+'.configured')
            if not marker.exists():self.bootstrap.Console(node).configure(self.config(node),credentials[node]['password'])
            info=self.api(node,'system/resource');assert info['version'].split()[0]=='7.24.5'
            assert self.api(node,'system/identity')['name']=='sdwan-overlay-'+node
            marker.write_text('7.24.5\n');print(node+' ready: API127.0.0.1:'+str(55728+idx),flush=True)
        self.probes_start();lock.close()
    def sdwan_config(self,node):
        assert node in ('hub','sitea','siteb')
        idx=NODES[node];hub=node=='hub';subnet=10 if node=='sitea' else 20
        addresses=['198.18.100.1'] if hub else [f'100.64.{subnet}.2',f'100.65.{subnet}.2']
        gateways=['198.18.100.2'] if hub else [f'100.64.{subnet}.1',f'100.65.{subnet}.1']
        wans=[]
        for number,(address,gateway) in enumerate(zip(addresses,gateways),1):
            target='198.19.'+('100' if number==1 else '200')+'.1'
            wans.append({'name':'wan'+str(number),'interface':'ether'+str(number+1),'address':address,'gateway':gateway,'probe_table':'sdwan-probe-wan'+str(number),'icmp_target':target,'probes':[{'name':name,'type':'http-get','host':target,'port':port} for name,port in zip(('a','b','c'),PROBE_PORTS)]})
        return {'schema_version':1,'revision':'overlay-lab-underlay-v1','health':{'interval_seconds':2,'timeout_ms':500,'packet_count':5,'packet_interval_ms':50,'quorum':2,'fail_windows':2,'recover_windows':3,'hold_down_seconds':6,'stale_seconds':10},'sla_profiles':{'default':{'rtt_ms':150,'jitter_ms':100,'loss_percent':20}},'wans':wans,'local_networks':[f'10.78.{idx}.0/24']+([] if hub else [f'10.201.{idx}.0/24']),'policies':[{'name':'default','source':'','table':'main','profile':'default','mode':'prefer','wans':[w['name'] for w in wans],'allow_degraded':False}],'takeover_route_comments':['baseline-'+w['name'] for w in wans],'takeover_rule':{'src-address':'','table':''}}
    def baseline(self):
        sys.path.insert(0,str(SOURCE_ROOT))
        from sdwan.router import Router
        spec=importlib.util.spec_from_file_location('sdwan_overlay_cli',SOURCE_ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        credentials=json.loads((self.run/'credentials.json').read_text());lock=(self.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for node in ('hub','sitea','siteb'):
            assert self.running(node)=='running'
            router=Router(self.root,'api://127.0.0.1:'+str(55728+NODES[node]),credentials_data=credentials[node])
            try:
                assert router.call('system/identity')['name']=='sdwan-overlay-'+node
                with (self.run/'baseline-deploy.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(router,self.sdwan_config(node),'sdwan-overlay-'+node)
                status=router.status();assert status['selected']['default']=='wan1';assert not status.get('error')
                print(node+' native SD-WAN underlay ready',flush=True)
            finally:router.close()
        lock.close()
    def keys(self):
        sys.path.insert(0,str(SOURCE_ROOT))
        from sdwan.router import Router
        from sdwan.overlay_runtime import prepare_keys
        credentials=json.loads((self.run/'credentials.json').read_text());lock=(self.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result={}
        for node in ('hub','sitea','siteb'):
            requests=[{'name':site+'-wan'+str(wan),'listen_port':51820+i*2+wan} for i,site in enumerate(('sitea','siteb')) for wan in (1,2)] if node=='hub' else [{'name':'hub-wan'+str(wan),'listen_port':51820+wan} for wan in (1,2)]
            router=Router(self.root,'api://127.0.0.1:'+str(55728+NODES[node]),credentials_data=credentials[node])
            try:result[node]=prepare_keys(router,requests,'sdwan-overlay-'+node)
            finally:router.close()
            print(node+' public WireGuard identities prepared; interfaces remain disabled',flush=True)
        (self.run/'overlay-public-keys.json').write_text(json.dumps(result,indent=2)+'\n');lock.close()
    def configs(self):
        sys.path.insert(0,str(SOURCE_ROOT))
        from sdwan.config import validate
        keys=json.loads((self.run/'overlay-public-keys.json').read_text())
        keys={node:{entry['name']:entry for entry in values} for node,values in keys.items()}
        result={node:self.sdwan_config(node) for node in ('hub','sitea','siteb')}
        for node,cfg in result.items():
            site=node!='hub';idx=NODES[node]
            cfg['revision']='overlay-lab-v1'
            cfg['overlay']={'enabled':True,'role':'site' if site else 'hub','router_id':f'10.202.0.{idx if site else 254}','local_prefixes':[f'10.201.{idx}.0/24'] if site else [],'remote_prefixes':[f'10.201.{2 if node=="sitea" else 1}.0/24'] if site else ['10.201.1.0/24','10.201.2.0/24'],'mtu':1380,'mss_clamp':True,'health':{'jitter_ms':250},'tunnels':[]}
        for site_index,site in enumerate(('sitea','siteb')):
            for wan in (1,2):
                link=site_index*2+wan;site_name='hub-wan'+str(wan);hub_name=site+'-wan'+str(wan)
                local=keys[site][site_name];remote=keys['hub'][hub_name]
                common={'cost':wan*10,'peer_prefixes':[f'10.201.{2 if site=="sitea" else 1}.0/24']}
                result[site]['overlay']['tunnels'].append(dict(common,name=site_name,wan='wan'+str(wan),listen_port=local['listen_port'],address=f'10.203.{link}.0/31',peer_address=f'10.203.{link}.1',local_public_key=local['public_key'],peer_public_key=remote['public_key'],endpoint='198.18.100.1',endpoint_port=remote['listen_port']))
                result['hub']['overlay']['tunnels'].append(dict(name=hub_name,wan='wan1',listen_port=remote['listen_port'],address=f'10.203.{link}.1/31',peer_address=f'10.203.{link}.0',local_public_key=remote['public_key'],peer_public_key=local['public_key'],peer_prefixes=[f'10.201.{site_index+1}.0/24'],cost=wan*10))
        target=self.root/'config';target.mkdir(exist_ok=True)
        for node,cfg in result.items():
            validate(cfg);(target/('overlay-'+node+'.json')).write_text(json.dumps(cfg,indent=2)+'\n');print(node+' overlay config generated (public identities only)',flush=True)
        return result
    def probes_start(self):
        pidfile=self.run/'probes.pid'
        if pidfile.exists():
            try:
                command=Path('/proc/'+pidfile.read_text().strip()+'/cmdline').read_bytes()
                if b'overlay_lab.py' in command and b'_serve' in command:return
            except OSError:pass
        for port in PROBE_PORTS:
            with socket.socket() as test:test.bind(('127.0.0.1',port))
        with (self.run/'probes.log').open('ab') as log:
            proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'_serve','--project-root',str(self.project_root)],stdout=log,stderr=log,start_new_session=True)
        pidfile.write_text(str(proc.pid)+'\n')
    def down(self):
        for node in NODES:
            if self.running(node):self.qmp(node,'quit')
        pidfile=self.run/'probes.pid'
        if pidfile.exists():
            try:
                pid=int(pidfile.read_text());command=Path(f'/proc/{pid}/cmdline').read_bytes()
                if b'overlay_lab.py' in command and b'_serve' in command:os.kill(pid,signal.SIGTERM)
            except (OSError,ValueError):pass
    def windows_api(self):
        # Hyper-V can reserve dynamic Windows ports around55728, preventing WSL
        # localhost forwarding. Add fixed low-range loopback aliases to the SAME
        # running NIC, without a guest change, VM restart or duplicate fabric.
        with (self.run/'lab.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            for node,idx in NODES.items():
                if self.running(node)!='running':raise RuntimeError('Start the existing overlay lab first: '+node)
                port=45728+idx;pattern=rf'127\.0\.0\.1\s+{port}\s+10\.78\.{idx}\.15\s+8728\b'
                info=self.qmp(node,'human-monitor-command',{'command-line':'info usernet'})
                if not re.search(pattern,info):
                    with socket.socket() as probe:probe.bind(('127.0.0.1',port))
                    reply=self.qmp(node,'human-monitor-command',{'command-line':f'hostfwd_add n1 tcp:127.0.0.1:{port}-10.78.{idx}.15:8728'})
                    info=self.qmp(node,'human-monitor-command',{'command-line':'info usernet'})
                    if not re.search(pattern,info):raise RuntimeError('Could not add loopback API alias: '+reply)
                print(node+' Windows API: api://127.0.0.1:'+str(port),flush=True)
    def status(self):
        print(json.dumps({n:{'state':self.running(n),'api':'api://127.0.0.1:'+str(55728+i),'api_windows':'api://127.0.0.1:'+str(45728+i)} for n,i in NODES.items()},indent=2))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','up','status','down','baseline','keys','configs','windows-api','_serve']);p.add_argument('--project-root',type=Path,default=SOURCE_ROOT);p.add_argument('--accel',choices=['auto','kvm','tcg'],default='auto');args=p.parse_args();lab=Lab(args.project_root)
    if args.command=='_serve':
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body=b'healthy\n';self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*a):pass
        for port in PROBE_PORTS:
            server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;threading.Thread(target=server.serve_forever,daemon=True).start()
        threading.Event().wait()
    elif args.command=='up':lab.up(args.accel)
    else:getattr(lab,args.command.replace('-','_'))()

if __name__=='__main__':main()
