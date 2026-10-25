#!/usr/bin/env python3
"""CHR ONLY: active VPN cold boot, fresh SLA and unchanged WireGuard identity."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.config import validate
from sdwan.diagnostics import seconds

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];before=json.loads(r.read_file('sdwan-active.json'));report={'checks':[],'pass':False};applied=False
 spec=importlib.util.spec_from_file_location('vpn_restart_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'vpn-protected-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(r,validate(c),'sdwan-overlay-sitea')
 def key():return r.call('interface/wireguard/print',{'.proplist':'public-key','.query':['name=vpn-exit-wg']},'POST')[0]['public-key']
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def wait(fn,timeout=120):
  end=time.monotonic()+timeout;last=None
  while time.monotonic()<end:
   try:
    last=fn()
    if last:return last
   except (ConnectionError,OSError,RuntimeError):r.close()
   time.sleep(.3)
  raise AssertionError({'timeout':last})
 def healthy():
  s=r.status()
  if s.get('error'):raise AssertionError(s['error'])
  return s if s.get('selected',{}).get('vpn-targets')=='vpn1' and s['selected'].get('default')=='wan1' and s.get('overlay') and all(x['healthy'] for x in s['overlay'].values()) else None
 try:
  cfg=copy.deepcopy(before);cfg['revision']='vpn-active-cold-restart';cfg['vpn_egress']={'enabled':True};w=copy.deepcopy(cfg['wans'][0]);w.pop('address');w.pop('gateway');w.update(v.state['links']['wireguard']);w.update(name='vpn1',kind='vpn',probe_table='sdwan-probe-vpn1');cfg['wans'].append(w);cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',destination_list='future-empty-restart-list',priority=10,wans=['vpn1','wan1','wan2'],table='sdwan-vpn-targets',profile='default',mode='prefer',allow_degraded=False))
  public=key();applied=True;apply(cfg);wait(healthy);old=seconds(r.call('system/resource')['uptime'])
  try:r.call('system/reboot',{},'POST')
  except (ConnectionError,OSError):r.close()
  wait(lambda:seconds(r.call('system/resource')['uptime'])<old)
  assert r.call('system/identity')['name']=='sdwan-overlay-sitea' and json.loads(r.read_file('sdwan-active.json'))['revision']==cfg['revision'] and key()==public
  record('cold CHR restart preserves the active local configuration and existing WireGuard public identity')
  s=wait(healthy);uptime=seconds(r.call('system/resource')['uptime']);sample=s['samples']['vpn1'];state=s['states']['default/vpn1']
  assert s['revision']==cfg['revision'] and 0<=s['uptime_seconds']<=uptime+1
  assert state['state']=='healthy' and state['good_windows']>=cfg['health']['recover_windows'];assert sample['epoch']>0 and sample['sample_age_seconds']<=cfg['health']['stale_seconds'] and not sample['warming']
  assert all(e['uptime_seconds']<=uptime+1 for e in s['events'])
  record('VPN becomes eligible only with current-boot probe epochs, recovery windows and fresh bounded-age SLA evidence')
  assert s['vpn_egress']['vpn1']['underlay']=='wan1' and s['vpn_egress']['vpn1']['transport_ready']
  # Hub and branch have independent recovery/hold-down windows. Inner probe
  # health on one side does not imply that both OSPF templates are enabled yet.
  wait(lambda:len([n for n in r.call('routing/ospf/neighbor/print',{'.proplist':'state'},'POST') if n.get('state','').lower()=='full'])==2)
  record('physical underlay pinning and both independent private OSPF legs recover after cold module initialization')
  report['pass']=True
 finally:
  try:
   if applied:apply(before)
  finally:(v.run/'vpn-restart-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
