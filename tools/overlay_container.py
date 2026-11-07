#!/usr/bin/env python3
"""Install the pinned container package on the EXISTING overlay site-A CHR only.

This does not prepare or start a controller. Original native/container fabrics
remain separate. The existing site VM may reboot or power-cycle for device mode.
"""
import argparse,copy,fcntl,functools,hashlib,http.server,json,os,shlex,subprocess,sys,threading,time,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from vpn_lab import VPNLab
from sdwan.deployment import read_state,TERMINAL
from sdwan.overlay_runtime import inventory

class Quiet(http.server.SimpleHTTPRequestHandler):
 def log_message(self,*args):pass

def prepare_fixture(v):
 from sdwan.config import validate
 from sdwan.container_runtime import prepare,read_container
 r=v.routers['sitea'];before=json.loads(r.read_file('sdwan-active.json'));cfg=copy.deepcopy(before);cfg['controller_backend']='container';cfg['revision']='overlay-container-lab-v1'
 if '172.31.255.0/30' not in cfg['local_networks']:cfg['local_networks'].append('172.31.255.0/30')
 cfg['container']={'image_file':'sdwan-controller-web-network-amd64.tar','telemetry':{'enabled':True,'sample_seconds':5,'history_points':12,'port':8080,'allowed_sources':['10.78.1.0/24'],'allowed_interfaces':['ether1']}};validate(cfg)
 # Prepare the complete WAN firewall scope while stopped, before any protected
 # runtime adoption. Later priority tests keep the same VPN interface identities.
 cfg['vpn_egress']={'enabled':True,'masquerade':True,'allow_selected_forward':True}
 cfg['wans']=[w for w in cfg['wans'] if w['name'] not in ('vpn1','vpn2')];cfg['policies']=[p for p in cfg['policies'] if p['name']!='vpn-targets']
 for i,kind in enumerate(('wireguard','sstp'),1):
  w=copy.deepcopy(cfg['wans'][0]);w.pop('address',None);w.pop('gateway',None);w.update(v.state['links'][kind]);w.update(name='vpn'+str(i),kind='vpn',probe_table='sdwan-probe-vpn'+str(i));cfg['wans'].append(w)
 cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',destination_list='network-container-future-list',priority=10,wans=['vpn1','vpn2','wan1','wan2'],table='sdwan-vpn-targets',profile='default',mode='prefer',allow_degraded=False));validate(cfg)
 image=ROOT/'dist/container/sdwan-controller-web-amd64.tar';reports=json.loads((image.parent/'build-report.json').read_text());built=next(x for x in reports if x['profile']=='web' and x['architecture']=='amd64');assert image.is_file() and hashlib.sha256(image.read_bytes()).hexdigest()==built['tar_sha256'],'Test the exact newly built archive'
 current=read_container(r)
 if current:assert current.get('file')==cfg['container']['image_file'] and current.get('image-id','').removeprefix('sha256:')==built['image_config_sha256'],'Existing container differs; inspect it before reimporting'
 elif not r.file_entry(cfg['container']['image_file']):
  server=http.server.ThreadingHTTPServer(('127.0.0.1',58090),functools.partial(Quiet,directory=str(image.parent)));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
  try:r.call('tool/fetch',{'url':'http://10.78.1.2:58090/'+image.name,'dst-path':cfg['container']['image_file'],'keep-result':'yes'},'POST')
  finally:server.shutdown();server.server_close();worker.join()
 result=prepare(r,cfg,'sdwan-overlay-sitea');row=read_container(r);assert row.get('image-id','').removeprefix('sha256:')==built['image_config_sha256'] and row['stopped']=='true';assert json.loads(r.read_file('sdwan-active.json'))==before
 (v.root/'config/overlay-sitea-container.json').write_text(json.dumps(cfg,indent=2)+'\n');print('PASS exact new scratch web image imported and prepared as stopped on the existing overlay CHR; active routing unchanged',flush=True)
 return {'pass':True,'production_access':False,'existing_vm_only':True,'image_id':built['image_config_sha256'],'tar_sha256':built['tar_sha256'],'stopped':True,'active_configuration_unchanged':True,'prepare':result}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',nargs='?',default='package',choices=['package','prepare']);p.add_argument('--project-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.project_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];report={'pass':False,'production_access':False,'existing_vm_only':True};path=v.run/('overlay-container-'+args.command+'-validation.json')
 def wait(fn,timeout=120):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   try:
    value=fn()
    if value:return value
   except (OSError,RuntimeError,ConnectionError):r.close()
   time.sleep(.5)
  raise AssertionError('Existing overlay CHR recovery timed out')
 def ready():
  return r.call('system/identity')['name']=='sdwan-overlay-sitea' and r.call('system/resource')['version'].split()[0]=='7.24.5'
 def update_mode():
  # The sentence API streams countdown rows, so an idle socket timeout is not
  # an absolute deadline. Reuse the lab's bounded REST request: headers wait for
  # physical confirmation and time out, while the local pending update remains.
  try:v.lab.api('sitea','system/device-mode/update',{'container':'yes'},'POST')
  except urllib.error.HTTPError:raise
  except (OSError,ConnectionError):pass
  finally:r.close()
 try:
  assert v.lab.running('sitea')=='running';state=read_state(r);assert not state or state.get('phase') in TERMINAL,'Wait for the existing protected deployment'
  if args.command=='prepare':report=prepare_fixture(v);return
  before=r.read_file('sdwan-active.json');keys={row['name']:row['public-key'] for row in inventory(r)};package=args.project_root/'runtime/container-packages/container-7.24.5.npk';expected=json.loads((args.project_root/'runtime/container-package-validation.json').read_text())['package_sha256'];assert package.is_file() and hashlib.sha256(package.read_bytes()).hexdigest()==expected,'Pinned private lab package changed'
  packages=r.call('system/package/print',{'.proplist':'name,version'},'POST')
  if not any(x['name']=='container' for x in packages):
   assert not r.file_entry(package.name),'Inspect the existing pending package before reusing its filename'
   server=http.server.ThreadingHTTPServer(('127.0.0.1',58090),functools.partial(Quiet,directory=str(package.parent)));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
   try:r.call('tool/fetch',{'url':'http://10.78.1.2:58090/'+package.name,'dst-path':package.name,'keep-result':'yes'},'POST')
   finally:server.shutdown();server.server_close();worker.join()
   try:r.call('system/reboot',{},'POST')
   except (OSError,ConnectionError):pass
   r.close();time.sleep(3);wait(ready);print('PASS pinned container package installed on the existing CHR site VM',flush=True)
  packages=r.call('system/package/print',{'.proplist':'name,version'},'POST');assert next(x for x in packages if x['name']=='container')['version']=='7.24.5'
  mode=r.call('system/device-mode/print',{'.proplist':'container'},'POST')[0]
  if mode.get('container')!='true':
   accel='kvm' if v.lab.qmp('sitea','query-kvm')['enabled'] else 'tcg';update_mode();time.sleep(3)
   try:v.lab.qmp('sitea','quit')
   except (OSError,ValueError):pass
   wait(lambda:v.lab.running('sitea') is None,15);cmd=v.lab.command('sitea',accel)
   if accel=='kvm' and not os.access('/dev/kvm',os.R_OK|os.W_OK):cmd=['sg','kvm','-c',shlex.join(cmd)]
   subprocess.run(cmd,check=True);wait(ready);print('PASS container device mode confirmed by power cycling the same isolated CHR',flush=True)
  assert r.call('system/device-mode/print',{'.proplist':'container'},'POST')[0]['container']=='true';assert r.read_file('sdwan-active.json')==before;assert {row['name']:row['public-key'] for row in inventory(r)}==keys
  wait(lambda:r.status().get('overlay') and all(x['healthy'] for x in r.status()['overlay'].values()) and len([n for n in r.call('routing/ospf/neighbor/print',{'.proplist':'state'},'POST') if n.get('state','').lower()=='full'])==2)
  report.update({'pass':True,'version':'7.24.5','package_sha256':expected,'container_device_mode':True,'keys_and_active_config_preserved':True,'branch_paths_recovered':2});print('PASS existing keys/configuration and both independent branch paths recover; no container was started',flush=True)
 finally:path.write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
