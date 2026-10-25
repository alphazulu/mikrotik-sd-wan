#!/usr/bin/env python3
"""CHR ONLY: new local scratch controller, VPN/OSPF parity and live bounded web.

Uses the already prepared container on existing overlay site A. The child VPN
matrix owns lab.lock during its mutations; the parent only observes web then.
"""
import argparse,contextlib,fcntl,http.client,importlib.util,json,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.container_runtime import read_container,paths

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];before=r.read_file('sdwan-active.json');cfg=json.loads((v.root/'config/overlay-sitea-container.json').read_text());report={'checks':[],'pass':False};applied=False;started=False;forwarded=False;nat=None;child=None
 spec=importlib.util.spec_from_file_location('network_container_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'network-container-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(r,c,'sdwan-overlay-sitea')
 def wait(fn,timeout=90):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   if fn():return
   time.sleep(.3)
  raise AssertionError('Container parity condition timed out')
 def active():
  s=r.status()
  if s.get('error'):raise AssertionError(s['error'])
  return s.get('container',{}).get('active') is True and s.get('selected',{}).get('default')=='wan1' and s.get('overlay') and all(x['healthy'] for x in s['overlay'].values())
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def request(path,token=None):
  conn=http.client.HTTPConnection('127.0.0.1',45880,timeout=4)
  try:
   conn.request('GET',path,headers={'Authorization':'Bearer '+token} if token else {});response=conn.getresponse();body=response.read(300000);assert len(body)<300000;return response.status,body
  finally:conn.close()
 def web():
  code,body=request('/api/status',token);assert code==200;data=json.loads(body);return data
 try:
  row=read_container(r);assert row and row['stopped']=='true' and cfg['controller_backend']=='container','Prepare the stopped new image first; do not duplicate an active test'
  expected=json.loads((v.run/'overlay-container-prepare-validation.json').read_text())['image_id'];assert row.get('image-id','').removeprefix('sha256:')==expected
  applied=True;apply(cfg);r.call('container/start',{'numbers':row['.id']},'POST');started=True;wait(active);record('exact new scratch image controls the existing CHR through the local API while both private OSPF paths remain healthy')
  with (v.run/'network-container-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.preflight(r,cfg,'sdwan-overlay-sitea')
  record('protected overlay and VPN installation retains prepared container isolation ordering and passes the unchanged API safety gate')
  nat=r.call('ip/firewall/nat/add',{'chain':'dstnat','in-interface':'ether1','src-address':'10.78.1.2','protocol':'tcp','dst-address':'10.78.1.15','dst-port':'58880','action':'dst-nat','to-addresses':'172.31.255.2','to-ports':'8080','comment':'sdwan-network-container-test','place-before':'0'},'POST')['ret']
  result=v.lab.qmp('sitea','human-monitor-command',{'command-line':'hostfwd_add n1 tcp:127.0.0.1:45880-10.78.1.15:58880'});assert not result,result;forwarded=True
  token=r.read_file(paths(cfg)['web_token']);password=r.read_file(paths(cfg)['password']);assert request('/api/status')[0]==401;code,body=request('/');assert code==200 and b'overlay-panel' in body and b'transports-panel' in body
  wait(lambda:not web()['stale'] and len(web()['current']['overlay'])==2);data=web();assert data['current']['actor']=='container' and len(data['current']['transports'])==len(cfg['wans']) and all(x['healthy'] for x in data['current']['overlay']);safe=json.dumps(data);assert token not in safe and password not in safe;record('live authenticated container web reports bounded maintenance and inner overlay SLA without credentials')
  native_report=v.run/'vpn-priority-validation.json'
  if native_report.exists():(v.run/'vpn-priority-before-container-validation.json').write_bytes(native_report.read_bytes())
  # The existing acceptance owns the same nonblocking lock. Parent performs no
  # RouterOS writes until the child has finished and the lock is reacquired.
  fcntl.flock(lock,fcntl.LOCK_UN)
  observed=False
  with (v.run/'network-container-vpn-matrix.log').open('w') as log:
   child=subprocess.Popen([sys.executable,'-u',str(ROOT/'tests/vpn_priority_acceptance.py'),'--lab-root',str(args.lab_root)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
   while child.poll() is None:
    try:
     data=web();rows=data.get('current',{}).get('transports',[])
     if not data.get('stale') and data.get('current',{}).get('actor')=='container' and len([x for x in rows if x.get('vpn_underlay') in ('wan1','wan2') and x.get('vpn_ready')])==2:observed=True
    except (OSError,AssertionError,ValueError):pass
    time.sleep(1)
   assert child.returncode==0,'Inspect private network-container-vpn-matrix.log'
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);matrix=json.loads(native_report.read_text());assert matrix['pass'] and len(matrix['checks'])==7 and observed;report['vpn_matrix_checks']=7;record('two-VPN priority matrix passes under the local Rust backend, including scoped real TCP cleanup and independent branch survival; live web observes both VPN parents')
  wait(active);intent=r.read_file('sdwan-container-intent.json');writes=web()['resources']['write_bytes'];time.sleep(12);assert r.read_file('sdwan-container-intent.json')==intent
  if type(writes) is int:assert web()['resources']['write_bytes']==writes
  report['process_write_bytes']=writes;record('steady handoff leaves the RouterOS intent file byte-identical; unavailable process I/O counters remain explicitly unknown')
  r.call('container/stop',{'numbers':row['.id']},'POST');wait(lambda:read_container(r).get('stopped')=='true' and not r.status().get('container',{}).get('active'));started=False;assert r.status()['selected']['default']=='wan1' and all(x['healthy'] for x in r.status()['overlay'].values());record('stopped local container returns ownership to warm RouterOS fallback without losing private paths')
  report['pass']=True
 finally:
  if child and child.poll() is None:child.send_signal(signal.SIGINT);child.wait(timeout=120)
  fcntl.flock(lock,fcntl.LOCK_EX)
  if started:
   r.call('container/stop',{'numbers':read_container(r)['.id']},'POST');wait(lambda:read_container(r).get('stopped')=='true',30)
  if forwarded:v.lab.qmp('sitea','human-monitor-command',{'command-line':'hostfwd_remove n1 tcp:127.0.0.1:45880'})
  if nat:r.call('ip/firewall/nat/'+nat,method='DELETE')
  try:
   if applied:apply(json.loads(before))
  finally:(v.run/'network-container-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
