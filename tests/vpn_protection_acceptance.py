#!/usr/bin/env python3
"""CHR ONLY: full rollback after adopting a disabled existing PPP VPN client."""
import argparse,copy,fcntl,importlib.util,json,sys,tempfile,time,contextlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.config import validate
from sdwan.deployment import start,wait as deployment_wait,read_state

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];report={'checks':[],'pass':False};name='vpn-rollback-disabled';tag='vpn-protection-acceptance-only'
 spec=importlib.util.spec_from_file_location('vpn_protection_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def rows():return r.call('interface/ovpn-client/print',{'.proplist':'.id,name,disabled,add-default-route,route-nopull,comment','.query':['name='+name]},'POST')
 try:
  assert not rows(),'Existing protected test must not be duplicated'
  assert not json.loads(r.read_file('sdwan-active.json')).get('vpn_egress',{}).get('enabled'),'Restore baseline before protection test'
  r.call('interface/ovpn-client',{'name':name,'connect-to':'198.18.100.1','port':'51194','user':'disabled-lab-client','disabled':'true','add-default-route':'true','route-nopull':'false','comment':tag},'PUT')
  previous={filename:r.read_file(filename) for filename in (*cli.FILES,'sdwan-config.json','sdwan-active.json','sdwan-backup.json')}
  cfg=json.loads(previous['sdwan-active.json']);cfg['revision']='vpn-rollback-injected';cfg['vpn_egress']={'enabled':True,'masquerade':True,'allow_selected_forward':True};w=copy.deepcopy(cfg['wans'][0]);w.pop('address');w.pop('gateway');w.update(name='vpn1',kind='vpn',interface=name,vpn_type='openvpn',vpn_endpoint='198.18.100.1',underlays=['wan1','wan2'],probe_table='sdwan-probe-vpn1');cfg['wans'].append(w);cfg['policies'].append(dict(name='rollback-targets',source='0.0.0.0/0',destination_list='future-unused-list',priority=10,profile='default',table='sdwan-rollback-targets',wans=['vpn1','wan1'],mode='prefer',allow_degraded=False));validate(cfg)
  with tempfile.TemporaryDirectory(prefix='vpn-protection-') as folder:
   package=cli.bundle(cfg,folder);installer=package/'sdwan-install.rsc';installer.write_text(installer.read_text()+'''
:local client [/interface/ovpn-client/find where name="vpn-rollback-disabled"]
:if ([/interface/ovpn-client/get $client add-default-route] || (![/interface/ovpn-client/get $client route-nopull])) do={ :error "fixture VPN routing options were not adopted" }
:if ([:len [/ip/firewall/mangle/find where comment="sdwan:v1:classify:rollback-targets:vpn1"]] != 1) do={ :error "fixture VPN classifier was not installed" }
:error "injected failure after VPN adoption and dataplane installation"
''')
   with (v.run/'vpn-protected-rollback.log').open('a') as log,contextlib.redirect_stdout(log):
    token=start(r,package,'sdwan-overlay-sitea',revision=cfg['revision'],default_policy='default',timeout=45)
    try:deployment_wait(r,token,'sdwan-overlay-sitea',timeout=45)
    except RuntimeError as error:assert 'rolled-back' in str(error) and 'injected failure after VPN adoption' in str(error),str(error)
    else:raise AssertionError('Injected failed deployment committed')
   assert read_state(r,token)['phase']=='rolled-back'
  for filename,text in previous.items():assert r.read_file(filename)==text,'Framework/config mismatch after rollback: '+filename
  record('local watchdog restores encrypted full backup and all ten RSC files/configs after actual VPN routing/dataplane changes and worker failure')
  row=rows()[0];assert row['disabled']=='true' and row['add-default-route']=='true' and row['route-nopull']=='false',row
  record('full rollback restores original PPP automatic-default and OpenVPN pull settings while retaining the disabled state')
  end=time.monotonic()+90
  while time.monotonic()<end:
   s=r.status()
   if not s.get('error') and s.get('selected',{}).get('default')=='wan1' and s.get('overlay') and all(x['healthy'] for x in s['overlay'].values()):break
   time.sleep(.3)
  else:raise AssertionError(s)
  for menu in ('ip/firewall/mangle','ip/firewall/nat','ip/firewall/filter','ip/firewall/address-list'):
   assert not any(row.get('comment','').startswith('sdwan:v1:vpn:') for row in r.call(menu+'/print',{'.proplist':'comment'},'POST')),menu
  record('fresh native physical SLA and both branch overlay legs recover after CHR reboot; failed optional VPN objects are absent')
  report['pass']=True
 finally:
  try:
   for row in rows():
    if row.get('comment')==tag:r.call('interface/ovpn-client/'+row['.id'],method='DELETE')
  finally:(v.run/'vpn-protection-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
