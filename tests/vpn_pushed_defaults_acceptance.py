#!/usr/bin/env python3
"""CHR ONLY: reject unadopted OpenVPN def1 routes; adopt existing defaults safely."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.config import validate
from sdwan.deployment import start,wait as deployment_wait

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];h=v.routers['hub'];report={'checks':[],'pass':False};clone='vpn-pushed-default-test';tag='vpn-pushed-default-acceptance-only';created=None;applied=False;native_started=False
 spec=importlib.util.spec_from_file_location('vpn_push_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 before=json.loads(a.read_file('sdwan-active.json'));backup=a.read_file('sdwan-backup.json');original=a.call('interface/ovpn-client/print',{'.proplist':'.id,disabled','.query':['name=vpn-exit-openvpn']},'POST')[0];server=h.call('interface/ovpn-server/server/print',{'.proplist':'.id,redirect-gateway','.query':['name=vpn-lab-openvpn']},'POST')[0]
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def routes():return a.call('ip/route/print',{'.proplist':'.id,dst-address,routing-table,gateway,immediate-gw,vrf-interface,dynamic,vpn,disabled,comment'},'POST')
 def wait(fn,timeout=75):
  end=time.monotonic()+timeout;last=None
  while time.monotonic()<end:
   last=fn()
   if last:return last
   time.sleep(.3)
  raise AssertionError('condition timed out')
 def split():return [r for r in routes() if r.get('dst-address') in ('0.0.0.0/1','128.0.0.0/1') and r.get('routing-table','main')=='main' and r.get('disabled')!='true']
 def apply(c):
  with (v.run/'vpn-protected-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(a,validate(c),'sdwan-overlay-sitea')
 try:
  assert not a.call('interface/ovpn-client/print',{'.proplist':'name','.query':['name='+clone]},'POST')
  a.call('interface/ovpn-client/'+original['.id'],{'disabled':'true'},'PATCH');h.call('interface/ovpn-server/server/'+server['.id'],{'redirect-gateway':'def1'},'PATCH')
  password=json.loads((v.run/'vpn-fixture-auth.json').read_text())['openvpn']['password']
  row=a.call('interface/ovpn-client',{'name':clone,'connect-to':'198.18.100.1','port':'51194','protocol':'tcp','mode':'ip','user':'vpn-lab-openvpn','password':password,'auth':'sha256','cipher':'aes256-cbc','verify-server-certificate':'false','add-default-route':'true','route-nopull':'false','disabled':'false','comment':tag},'PUT');created=row['.id']
  wait(lambda:len(split())==2);assert all(r.get('vpn')=='true' for r in split())
  try:cli.preflight(a,before,'sdwan-overlay-sitea')
  except ValueError as error:assert 'split default' in str(error),str(error)
  else:raise AssertionError('Unadopted def1 route passed preflight')
  record('API preflight rejects real unadopted OpenVPN server-pushed def1 routes before network mutation')
  previous={f:a.read_file(f) for f in (*cli.FILES,'sdwan-config.json','sdwan-active.json','sdwan-backup.json')}
  with tempfile.TemporaryDirectory(prefix='vpn-push-reject-') as folder:
   candidate=copy.deepcopy(before);candidate['revision']='reject-unadopted-def1';package=cli.bundle(candidate,folder)
   with (v.run/'vpn-protected-rollback.log').open('a') as log,contextlib.redirect_stdout(log):
    native_started=True
    token=start(a,package,'sdwan-overlay-sitea',revision=candidate['revision'],default_policy='default',timeout=45)
    try:deployment_wait(a,token,'sdwan-overlay-sitea',timeout=45)
    except RuntimeError as error:assert 'rolled-back' in str(error) and 'split default' in str(error),str(error)
    else:raise AssertionError('Native installer accepted unadopted def1')
   for f,text in previous.items():assert a.read_file(f)==text,f
  wait(lambda:len(split())==2);record('native installer independently rejects unadopted def1 and local watchdog restores the complete previous package')
  cfg=copy.deepcopy(before);cfg['revision']='adopt-existing-pushed-vpn';cfg['vpn_egress']={'enabled':True};w=copy.deepcopy(cfg['wans'][0]);w.pop('address');w.pop('gateway');w.update(name='vpn1',kind='vpn',interface=clone,vpn_type='openvpn',vpn_endpoint='198.18.100.1',underlays=['wan1','wan2'],probe_table='sdwan-probe-vpn1');cfg['wans'].append(w);cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',destination_list='future-empty-push-list',priority=10,wans=['vpn1','wan1'],table='sdwan-vpn-targets',profile='default',mode='prefer',allow_degraded=False));applied=True;apply(cfg)
  wait(lambda:a.status().get('selected',{}).get('vpn-targets')=='vpn1');assert not split();row=a.call('interface/ovpn-client/print',{'.proplist':'.id,add-default-route,route-nopull','.query':['name='+clone]},'POST')[0];assert row['add-default-route']=='false' and row['route-nopull']=='true'
  assert not any(r.get('dynamic')=='true' and r.get('routing-table','main')=='main' and r.get('dst-address')=='0.0.0.0/0' for r in routes())
  flags=json.loads(a.read_file('sdwan-backup.json'))['vpn_clients']['openvpn:'+clone];assert flags['original_add'] is True and flags['original_nopull'] is False
  record('protected adoption captures original flags, suppresses automatic and pushed defaults, reconnects the existing VPN and recovers through common SLA')
  report['pass']=True
 finally:
  try:
   rows=a.call('interface/ovpn-client/print',{'.proplist':'.id,comment','.query':['name='+clone]},'POST')
   for row in rows:
    if row.get('comment')==tag:a.call('interface/ovpn-client/'+row['.id'],{'disabled':'true'},'PATCH')
   if applied or native_started:apply(before)
   for row in rows:
    if row.get('comment')==tag:a.call('interface/ovpn-client/'+row['.id'],method='DELETE')
   if applied:a.upload('sdwan-backup.json',backup)
   h.call('interface/ovpn-server/server/'+server['.id'],{'redirect-gateway':server.get('redirect-gateway','disabled')},'PATCH')
   a.call('interface/ovpn-client/'+original['.id'],{'disabled':original['disabled']},'PATCH')
  finally:(v.run/'vpn-pushed-defaults-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
