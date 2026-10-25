#!/usr/bin/env python3
"""CHR ONLY: overlay reapply/off/on and encrypted rollback with real TCP.

All actual writes target the existing isolated site-A CHR; the original native
configuration is restored in finally. No keys/authentication are exported.
"""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic
from sdwan.deployment import start,wait as deployment_wait,read_state
from sdwan.vpn_egress import vpn_wans

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);p.add_argument('--json-guards-only',action='store_true');args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];before=json.loads(r.read_file('sdwan-active.json'));assert before.get('overlay',{}).get('enabled') and not vpn_wans(before);checks=[];traffic=None;applied=False;report={'pass':False,'checks':checks}
 spec=importlib.util.spec_from_file_location('overlay_lifecycle_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'overlay-lifecycle-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(r,c,'sdwan-overlay-sitea')
 def wait(fn,timeout=90):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   value=fn()
   if value:return value
   time.sleep(.25)
  raise AssertionError('Overlay lifecycle condition timed out')
 def healthy():
  s=r.status();return not s.get('error') and s.get('selected',{}).get('default')=='wan1' and s.get('overlay') and all(t['healthy'] for t in s['overlay'].values())
 def identities():return {x['name']:{k:x.get(k) for k in ('public-key','listen-port','mtu')} for x in r.call('interface/wireguard/print',{'.proplist':'name,public-key,listen-port,mtu,comment'},'POST') if x.get('comment','').startswith('sdwan:v1:overlay:interface:')}
 def record(label):checks.append({'check':label,'pass':True});print('PASS '+label,flush=True)
 def protected_failure(config,*,raw_null=False,raw_health=False):
  previous={f:r.read_file(f) for f in (*cli.FILES,'sdwan-config.json','sdwan-active.json','sdwan-backup.json')};keys=identities()
  with tempfile.TemporaryDirectory(prefix='overlay-lifecycle-') as folder:
   package=cli.bundle(config,folder)
   if raw_null or raw_health:
    c=json.loads((package/'sdwan-config.json').read_text());
    if raw_null:c['overlay']['tunnels'].insert(0,None);expected='JSON null is not an overlay configuration value'
    else:c['overlay']['health']=[];expected='overlay JSON object/list type mismatch'
    (package/'sdwan-config.json').write_text(json.dumps(c,separators=(',',':')))
   else:
    installer=package/'sdwan-install.rsc';installer.write_text(installer.read_text()+'''\n:local fixtureInterface [/interface/wireguard/find where name="sdwan-wg-hub-wan1"]
:if ([/interface/wireguard/get $fixtureInterface mtu] != 1360) do={ :error "test overlay MTU mutation was not installed" }
:if ([:len [/ip/firewall/mangle/find where comment="sdwan:v1:overlay:mss"]] != 1) do={ :error "test overlay MSS mutation was not installed" }
:error "injected failure after overlay MTU/OSPF/MSS changes"
''');expected='injected failure after overlay MTU/OSPF/MSS changes'
   with (v.run/'overlay-lifecycle-rollback.log').open('a') as log,contextlib.redirect_stdout(log):
    token=start(r,package,'sdwan-overlay-sitea',revision=config['revision'],default_policy='default',timeout=45)
    try:deployment_wait(r,token,'sdwan-overlay-sitea',timeout=45)
    except RuntimeError as error:assert 'rolled-back' in str(error) and expected in str(error),str(error)
    else:raise AssertionError('Injected invalid deployment committed')
   assert read_state(r,token)['phase']=='rolled-back'
  for f,text in previous.items():assert r.read_file(f)==text,'Recovered framework/config differs: '+f
  assert identities()==keys;wait(healthy)
 try:
  applied=True;apply(before);wait(healthy);original_keys=identities();record('updated native schema/ownership gates install successfully and both branch OSPF legs recover with ordinary Internet SLA')
  if args.json_guards_only:
   for raw_case in ('null','health-list'):
    bad=copy.deepcopy(before);bad['revision']='overlay-json-guard-'+raw_case;protected_failure(bad,raw_null=raw_case=='null',raw_health=raw_case=='health-list');record('native original-JSON '+raw_case+' guard rejects malformed collection and restores the complete package through protected rollback')
   report['pass']=True;return
  traffic=VPNTraffic(v);traffic.prepare();internet=traffic.stream(59410,'sdwan-out-default:wan1');branch=traffic.stream(59419,'no-mark',target='10.201.1.2');apply(before);wait(healthy);assert identities()==original_keys;traffic.assert_sessions(retained=[internet,branch]);record('idempotent protected reapply retains public identities and the same real Internet and private TCP connections')
  traffic.close();traffic=None
  off=copy.deepcopy(before);off['overlay']={'enabled':False};off['revision']='overlay-disabled-lifecycle';apply(off)
  s=r.status();assert not s.get('error') and not s.get('overlay') and s['selected']['default']=='wan1';assert identities()==original_keys
  interfaces=r.call('interface/wireguard/print',{'.proplist':'name,disabled,comment'},'POST');assert all(x.get('disabled')=='true' for x in interfaces if x.get('comment','').startswith('sdwan:v1:overlay:interface:'))
  for menu in ('interface/wireguard/peers','ip/address','ip/route','routing/rule','tool/netwatch','routing/ospf/interface-template','routing/ospf/area','routing/ospf/instance','routing/filter/rule','ip/firewall/mangle','ip/firewall/nat','ip/firewall/filter','ip/firewall/address-list','interface/list/member'):
   assert not any(x.get('comment','').startswith('sdwan:v1:overlay:') for x in r.call(menu+'/print',{'.proplist':'comment'},'POST')),menu
  record('disabling overlay removes its routing/firewall/OSPF/probe objects, retains disabled key identities and leaves ordinary Internet selection healthy')
  apply(before);wait(healthy);assert identities()==original_keys;record('reenabling overlay reuses exact public identities and restores both private paths through fresh inner SLA')
  changed=copy.deepcopy(before);changed['revision']='overlay-injected-lifecycle';changed['overlay'].update(mtu=1360,mss_clamp=True);changed['overlay']['tunnels'][0]['cost']+=7;protected_failure(changed);record('local watchdog rolls back actual MTU/OSPF/MSS mutations, encrypted full configuration and all ten source files after worker failure')
  bad=copy.deepcopy(before);bad['revision']='overlay-null-injected';protected_failure(bad,raw_null=True);record('native original-JSON guard rejects a null tunnel before reconciliation and protected rollback restores the complete previous package')
  report['pass']=True
 finally:
  try:
   if traffic:traffic.close()
   if applied:apply(before);wait(healthy)
  finally:(v.run/('overlay-json-guards-validation.json' if args.json_guards_only else 'overlay-lifecycle-validation.json')).write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()
if __name__=='__main__':main()
