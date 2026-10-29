"""Disposable, owned QEMU DUT with three WAN peers and loopback-only management."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
from .namespace_tap import open_tap
from .runtime import atomic_json,checked,check_ports
from .usb_repro import qmp

SOURCES=tuple('192.168.50.'+str(i) for i in range(110,238))


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def wait(predicate,seconds=120):
    deadline=time.monotonic()+seconds;last=''
    while time.monotonic()<deadline:
        try:
            result=predicate()
            if result:return result
        except (OSError,RuntimeError) as error:last=str(error)
        time.sleep(.2)
    raise TimeoutError('Owned DUT readiness expired: '+last)


def load_config(path):
    path=Path(path).resolve();value=json.loads(path.read_text())
    required={'source','base_disk','base_sha256','credentials','identity','artifacts','variants'}
    allowed=required|{'port_base','vcpu','memory_mib','tools','calibration_tcpudp','calibration_cps','data_nic'}
    if not isinstance(value,dict) or required-set(value) or set(value)-allowed:raise ValueError('Unknown or missing owned-DUT configuration fields')
    value=dict(value,port_base=value.get('port_base',25800),vcpu=value.get('vcpu',1),memory_mib=value.get('memory_mib',1024))
    for key,lo,hi in [('port_base',1024,65531),('vcpu',1,8),('memory_mib',512,4096)]:
        if type(value[key]) is not int or not lo<=value[key]<=hi:raise ValueError('Invalid DUT '+key)
    if not isinstance(value['base_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',value['base_sha256']):raise ValueError('Pin the stopped base disk SHA256')
    if not isinstance(value['identity'],str) or not 1<=len(value['identity'])<=100 or any(ord(c)<32 for c in value['identity']):raise ValueError('Invalid expected DUT identity')
    for key in ['source','base_disk','credentials','artifacts','variants','calibration_tcpudp','calibration_cps']:
        if key in value:
            if not isinstance(value[key],str) or not value[key]:raise ValueError('Invalid DUT path '+key)
            item=Path(value[key]);value[key]=(path.parent/item).resolve() if not item.is_absolute() else item.resolve()
    value['data_nic']=value.get('data_nic','virtio-net-pci')
    if value['data_nic'] not in ('e1000','virtio-net-pci'):raise ValueError('Unsupported owned data NIC model')
    tools={'qemu':'qemu-system-x86_64','qemu_img':'qemu-img','iperf3':'iperf3','cc':'cc'}
    supplied=value.get('tools',{})
    if not isinstance(supplied,dict) or set(supplied)-set(tools):raise ValueError('Invalid DUT tools')
    tools.update(supplied)
    for key,tool in tools.items():
        if not isinstance(tool,str) or not tool or '\0' in tool:raise ValueError('Invalid executable')
        if '/' in tool and not Path(tool).is_absolute():tools[key]=str((path.parent/tool).resolve())
    value['tools']=tools;value['config_path']=path
    return value


def topology_config(config):
    """This fixture deliberately supports one explicit synthetic lab topology."""
    expected=[('wan'+str(i),'172.20.'+str(i)+'.2','172.20.'+str(i)+'.1') for i in range(1,4)]
    actual=[(w.get('interface'),w.get('address'),w.get('gateway')) for w in config['wans']]
    if any(w.get('kind','static')!='static' for w in config['wans']):raise ValueError('This benchmark fixture uses static WANs only')
    if actual!=expected:raise ValueError('Owned fixture requires WAN interfaces wan1..3 with 172.20.i.2 -> .1')
    if '192.168.50.0/24' not in config['local_networks']:raise ValueError('Unexpected client network')
    policies={p['name']:p for p in config['policies']}
    if policies.get('client101',{}).get('source')!='192.168.50.101/32' or policies.get('client102',{}).get('source')!='192.168.50.102/32':raise ValueError('Fixture needs explicit affected/pinned client policies')
    if policies['client101']['wans'][:2]!=['wan1','wan2'] or policies['client102']['wans'][0]!='wan2':raise ValueError('Fixture policy order changed')
    for i,wan in enumerate(config['wans'],1):
        if wan.get('icmp_target')!=f'10.77.{i}.2' or [(p.get('host'),p.get('port')) for p in wan['probes']]!=[(f'10.77.{i}.2',port) for port in (28081,28082,28083)]:raise ValueError('Fixture SLA destinations changed')
    return config


class Fixture:
    def __init__(self,config,run):
        self.config=config;self.run=run;self.router=None;self.child=None;self.fds=[];self.boots=0;self.mode=None;self.active_config=None;self.names=None;self.baseline=None
        self.source=config['source'];sys.path.insert(0,str(self.source))
        from sdwan.router import Router
        self.Router=Router
        spec=importlib.util.spec_from_file_location('sdwan_owned_dut_cli',self.source/'sdwan.py');self.cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.cli)

    @property
    def api_url(self):return 'api://127.0.0.1:'+str(self.config['port_base']+4)

    def connect(self):
        router=self.Router(self.run.folder,self.api_url,credentials=self.config['credentials'])
        try:
            if router.call('system/identity')['name']!=self.config['identity']:raise ValueError('Owned DUT identity mismatch')
            return router
        except BaseException:router.close();raise

    def ns_argv(self,index,args):return ['ip','netns','exec',self.names[index],'env','PYTHONPATH='+str(self.source/'labtools')]+list(map(str,args))
    def ns(self,index,args):return checked(self.ns_argv(index,args))

    def backing_chain(self):
        # Do not use -U: a live writable base must fail the normal image lock.
        rows=json.loads(checked([self.config['tools']['qemu_img'],'info','--backing-chain','--output=json',self.config['base_disk']]).stdout)
        return [{'path':str(Path(r['filename']).resolve()),'sha256':sha(r['filename'])} for r in rows]

    def prepare(self):
        base=self.config['port_base'];check_ports([base,base+1,base+2,base+4]);chain=self.backing_chain()
        if chain[0]['sha256']!=self.config['base_sha256']:raise ValueError('Stopped base disk changed')
        snapshot={'backing_chain':chain,'scope':'new-disposable-overlay','config_sha256':sha(self.config['config_path']),'vm_name':'sdwan-dut-'+self.run.data['token'][:12]}
        # Save before allocating resources so recovery knows what must be intact.
        atomic_json(self.run.folder/'dut-snapshot.json',snapshot)
        self.names=[self.run.namespace('a'),self.run.namespace('b')]
        for i in range(2):self.ns(i,['ip','link','set','lo','up'])
        for i in range(4):
            side=1 if i<3 else 0;name='wan'+str(i+1) if i<3 else 'lan'
            fd=open_tap(self.run,self.names[side],name);self.fds.append(fd)
            self.ns(side,['sysctl','-qw','net.ipv6.conf.'+name+'.disable_ipv6=1'])
            self.ns(side,['ip','link','set',name,'up']);self.ns(side,['ethtool','-K',name,'tso','off','gso','off','gro','off'])
            self.ns(side,['ip','addr','add',f'172.20.{i+1}.1/24' if i<3 else '192.168.50.101/24','dev',name])
        self.ns(0,['ip','addr','add','192.168.50.102/24','dev','lan'])
        for address in SOURCES:self.ns(0,['ip','addr','add',address+'/32','dev','lan'])
        self.ns(0,['ip','route','add','default','via','192.168.50.1'])
        for address in ['198.18.79.1/32']+[f'10.77.{i}.2/32' for i in range(1,4)]:self.ns(1,['ip','addr','add',address,'dev','lo'])
        for field in ['rp_filter','arp_ignore','arp_announce']:self.ns(1,['sysctl','-qw','net.ipv4.conf.all.'+field+'=0'])
        self.run.spawn(self.ns_argv(1,[sys.executable,'-m','sdwan_lab.continuity','serve','--listen','198.18.79.1','--port','25351']),'dut-echo')
        self.run.spawn(self.ns_argv(1,[sys.executable,'-m','sdwan_lab.dut_peer']),'dut-sla')
        self.run.spawn(self.ns_argv(1,[sys.executable,'-m','sdwan_lab.continuity','serve','--listen','198.18.79.1','--port','25352']),'dut-pinned-echo')
        wait(lambda:'ready' in (self.run.folder/'dut-pinned-echo.stdout').read_text(),10);wait(lambda:'ready' in (self.run.folder/'dut-echo.stdout').read_text(),10);wait(lambda:'ready' in (self.run.folder/'dut-sla.stdout').read_text(),10)
        self.boot(snapshot,'before');return snapshot

    def boot(self,snapshot,label):
        disk=self.run.folder/('dut-'+label+'.qcow2');checked([self.config['tools']['qemu_img'],'create','-f','qcow2','-F','qcow2','-b',self.config['base_disk'],disk])
        base=self.config['port_base'];command=[self.config['tools']['qemu'],'-name',snapshot['vm_name'],'-machine','pc','-accel','kvm','-cpu','host','-m',str(self.config['memory_mib']),'-smp',str(self.config['vcpu']),'-display','none','-drive',f'file={disk},format=qcow2,bus=0,unit=0,media=disk','-qmp',f'tcp:127.0.0.1:{base},server=on,wait=off','-serial',f'tcp:127.0.0.1:{base+1},server=on,wait=off','-netdev',f'user,id=mgmt,net=10.89.0.0/24,dhcpstart=10.89.0.15,ipv6=off,hostfwd=tcp:127.0.0.1:{base+2}-10.89.0.15:80,hostfwd=tcp:127.0.0.1:{base+4}-10.89.0.15:8728','-device','e1000,netdev=mgmt,mac=52:54:00:89:00:01']
        for i,fd in enumerate(self.fds):command+=['-netdev',f'tap,id=data{i},fd={fd}','-device',f'{self.config["data_nic"]},netdev=data{i},mac=52:54:00:89:00:{i+2:02x}']
        self.child=self.run.spawn(command,'dut-'+label,pass_fds=tuple(self.fds));atomic_json(self.run.folder/('dut-'+label+'-command.json'),command)
        wait(lambda:qmp(base,'query-name')['name']==snapshot['vm_name'],15);self.router=wait(self.connect,150)
        resource=self.router.call('system/resource');license=self.router.call('system/license/print',{'.proplist':'nlevel'},'POST')
        if resource['version'].split()[0]!='7.24.5' or license[0].get('nlevel')!='6':raise ValueError('Fixture requires measured RouterOS7.24.5 x86 L6')
        modes=self.router.call('system/device-mode/print',{'.proplist':'scheduler,fetch,container,flagged'},'POST')[0]
        if any(modes.get(k)!='true' for k in ['scheduler','fetch','container']) or modes.get('flagged')!='false':raise ValueError('Prepare base packages/device-mode before using this fixture')
        self.configure_baseline();self.mode='baseline-before' if label=='before' else 'baseline-after';self.active_config=None
        projection=self.baseline_projection()
        if self.baseline is None:self.baseline=projection;atomic_json(self.run.folder/'dut-baseline.json',projection)
        elif projection!=self.baseline:raise ValueError('Rebuilt baseline differs from the initial projection')

    def configure_baseline(self):
        r=self.router;items=r.call('interface/ethernet/print',{'.proplist':'.id,name,mac-address'},'POST');desired={f'52:54:00:89:00:{i+2:02X}':('wan'+str(i+1) if i<3 else 'lan') for i in range(4)}
        if len([i for i in items if i['mac-address'].upper() in desired])!=4:raise ValueError('Owned data NIC identities not found')
        for item in items:
            if item['mac-address'].upper() in desired:r.call('interface/ethernet/set',{'numbers':item['.id'],'name':'tmp'+item['.id'].replace('*','')},'POST')
        for item in items:
            if (name:=desired.get(item['mac-address'].upper())):
                r.call('interface/ethernet/set',{'numbers':item['.id'],'name':name,'disabled':'no'},'POST')
                r.call('ip/address/add',{'address':f'172.20.{int(name[-1])}.2/24' if name.startswith('wan') else '192.168.50.1/24','interface':name},'POST')
        for route in r.call('ip/route/print',{'.proplist':'.id,dst-address,gateway'},'POST'):
            if route.get('dst-address')=='0.0.0.0/0' and route.get('gateway')=='10.89.0.2':r.call('ip/route/remove',{'numbers':route['.id']},'POST')
        for i in range(1,4):r.call('ip/route/add',{'dst-address':'0.0.0.0/0','gateway':f'172.20.{i}.1','distance':str(i),'comment':'baseline-wan'+str(i)},'POST')
        r.call('routing/table/add',{'name':'prefer-wan2','fib':'yes'},'POST');r.call('ip/route/add',{'dst-address':'0.0.0.0/0','gateway':'172.20.2.1','routing-table':'prefer-wan2','comment':'baseline-pinned'},'POST')
        r.call('routing/rule/add',{'src-address':'192.168.50.102/32','action':'lookup-only-in-table','table':'prefer-wan2','comment':'baseline-pinned'},'POST')
        r.call('ip/firewall/nat/add',{'chain':'srcnat','src-address':'192.168.50.0/24','action':'masquerade','comment':'owned baseline fixture'},'POST')

    def baseline_projection(self):
        result={}
        for menu,fields in [('ip/address',['address','interface','disabled']),('ip/route',['dst-address','gateway','routing-table','distance','disabled','comment']),('routing/rule',['src-address','action','table','disabled','comment']),('ip/firewall/nat',['chain','src-address','action','disabled','comment'])]:
            rows=self.router.call(menu+'/print',{'.proplist':','.join(fields)+',dynamic'},'POST')
            rows=[{k:v for k,v in row.items() if k in fields} for row in rows if row.get('dynamic')!='true']
            result[menu]=sorted(rows,key=lambda row:json.dumps(row,sort_keys=True))
        return result

    def shutdown(self):
        if self.router is not None:
            try:self.router.call('system/shutdown',{},'POST')
            except (OSError,RuntimeError):pass
            finally:self.router.close();self.router=None
        if self.child is not None:wait(lambda:self.child.poll() is not None,90)

    def observed(self,mode):
        if self.mode!=mode:raise ValueError('Wrong requested DUT stage')
        state=self.router.status()
        if mode.startswith('baseline-'):
            if state.get('enabled') or self.baseline_projection()!=self.baseline:raise ValueError('Baseline forwarding/controller state changed')
        else:
            backend=state.get('backend','routeros')
            if backend!=('routeros' if mode=='routeros' else 'container') or 'error' in state:raise ValueError('Wrong observed controller backend')
            if mode!='routeros' and not state.get('container',{}).get('active'):raise ValueError('Container controller is not active')
        return state

    def stopped_container(self,identifier,seconds=15):
        from sdwan.container_runtime import read_container
        def stopped():
            row=read_container(self.router)
            if not row or row.get('.id')!=identifier or row.get('comment')!='sdwan-container:controller':raise ValueError('Owned container identity changed while stopping')
            return row if row.get('stopped')=='true' else None
        return wait(stopped,seconds)

    def set_mode(self,mode,plan,snapshot):
        if mode not in ('baseline-before','routeros','container','container-web','baseline-after'):raise ValueError('Invalid comparison mode')
        if mode=='baseline-before':self.mode=mode;self.observed(mode);return
        if mode=='baseline-after':
            if self.active_config:self.cli.rollback(self.router,self.config['identity'])
            self.shutdown();self.boot(snapshot,'after');self.observed(mode);return
        cfg=json.loads((self.config['variants']/(mode+'.json')).read_text());topology_config(cfg)
        if mode!='routeros':
            from sdwan import container_runtime
            from sdwan.provisioning import prepare_container
            old=container_runtime.read_container(self.router)
            if old:
                self.cli.rollback(self.router,self.config['identity']);old=self.stopped_container(old['.id'])
                atomic_json(self.run.folder/('stopped-before-'+mode+'.json'),old)
                old_paths=container_runtime.paths(self.active_config)
                self.router.call('container/'+old['.id'],method='DELETE')
                for row in self.router.call('container/mounts'):
                    if row.get('list')=='sdwan-controller':
                        if row.get('src','').strip('/') not in (old_paths['config'],old_paths['secrets']):raise ValueError('Unexpected mount in owned container list')
                        self.router.call('container/mounts/'+row['.id'],method='DELETE')
            # Separate stopped image roots avoid replacing an imported filesystem.
            sdk=self.run.folder/'sdk';(sdk/'config').mkdir(parents=True,exist_ok=True);(sdk/'dist/container').mkdir(parents=True,exist_ok=True)
            (sdk/'config/container-images.json').write_bytes((self.source/'config/container-images.json').read_bytes())
            archive=cfg['container']['image_file'];link=sdk/'dist/container'/archive
            if not link.exists():link.symlink_to(self.config['artifacts']/archive)
            prepare_container(self.router,cfg,self.config['identity'],root=sdk)
        self.cli.apply(self.router,cfg,self.config['identity']);self.mode=mode;self.active_config=cfg
        def ready():
            state=self.observed(mode)
            return state if state.get('selected',{}).get('client101')=='wan1' and state.get('selected',{}).get('client102')=='wan2' else None
        state=wait(ready,75);atomic_json(self.run.folder/('mode-'+mode+'.json'),state)

    def restore(self,snapshot):
        if self.router is not None:
            try:self.shutdown()
            except (OSError,RuntimeError):self.run.stop(self.child.pid)
        elif self.child is not None:self.run.stop(self.child.pid)
        # In recovery this instance has no live handles; the journal owns any
        # surviving QEMU and namespace processes. The parent is never writable.
        cleaned=self.run.cleanup()
        for fd in self.fds:os.close(fd)
        self.fds=[]
        current=[dict(row,actual_sha256=sha(row['path'])) for row in snapshot['backing_chain']]
        unchanged=all(row['sha256']==row['actual_sha256'] for row in current)
        return {'pass':cleaned and unchanged,'verified':cleaned and unchanged,'kind':'owned disposable overlay discard','backing_chain_unchanged':unchanged,'resources_released':cleaned,'backing_chain':current}
