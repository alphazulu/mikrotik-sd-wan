#!/usr/bin/env python3
"""CHR ONLY: Python/preflight and native VPN validation, without network writes."""
import argparse,copy,fcntl,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.config import validate
from sdwan.vpn_egress import binding,vpn_wans

def q(value):return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('$','\\$').replace('\r','\\r').replace('\n','\\n')+'"'

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];name='vpn-validation-acceptance';created=[];files=[];cases=[]
 before=json.loads(r.read_file('sdwan-active.json'));assert not vpn_wans(before),'Restore baseline before contract checks'
 def seed(kind='wireguard'):
  c=copy.deepcopy(before);c['vpn_egress']={'enabled':True};w=copy.deepcopy(c['wans'][0]);w.pop('address');w.pop('gateway');w.update(v.state['links'][kind]);w.update(name='vpn1',kind='vpn',probe_table='sdwan-probe-vpn1');c['wans'].append(w);c['policies'].append(dict(name='targets',source='0.0.0.0/0',priority=10,destination_list='existing targets',wans=['vpn1','wan1'],table='sdwan-targets',profile='default',mode='prefer',allow_degraded=False));return c
 def add(label,c):
  try:
   validate(c)
   for w in vpn_wans(c):binding(r,w)
   expected=True
  except ValueError:expected=False
  cases.append(dict(case=label,expected=expected,config_json=json.dumps(c,separators=(',',':'))))
 for kind in ('wireguard','l2tp','sstp','openvpn'):add(kind+' existing client',seed(kind))
 add('default off baseline',before)
 for label,change in [('disabled with VPN',lambda c:c['vpn_egress'].update(enabled=False)),('typed flag',lambda c:c['vpn_egress'].update(enabled='true')),('explicit null',lambda c:c['vpn_egress'].update(enabled=None)),('secret option',lambda c:c['vpn_egress'].update(password='forbidden-placeholder')),('parent cycle',lambda c:c['wans'][-1].update(underlays=['vpn1'])),('duplicate parent',lambda c:c['wans'][-1].update(underlays=['wan1','wan1'])),('no parent',lambda c:c['wans'][-1].update(underlays=[])),('default VPN',lambda c:c['policies'][0].update(wans=['vpn1'])),('unscoped VPN policy',lambda c:c['policies'][-1].pop('destination_list')),('source snapshot',lambda c:c['wans'][-1].update(address='10.204.1.2')),('changed exit key',lambda c:c['wans'][-1].update(vpn_peer_public_key='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')),('recursive endpoint',lambda c:c['wans'][-1].update(vpn_endpoint='10.201.2.10'))]:
  c=seed();change(c);add(label,c)
 payload=json.dumps(cases,separators=(',',':'));assert len(payload.encode())<60000
 try:
  assert not r.call('system/script/print',{'.proplist':'name','.query':['name='+name]},'POST'),'Existing contract test must not be duplicated'
  for filename,body in [('vpn-validation-library.rsc',(ROOT/'native/sdwan-vpn.rsc').read_text()),('vpn-validation-cases.json',payload)]:r.upload(filename,body);files.append(filename)
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name=sdwanVPNValidationJSON']},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
  source='''/system/scheduler/disable [/system/scheduler/find where name="vpn-validation-acceptance"]
:global sdwanVPNValidationJSON
:onerror failure in={
/import file-name="vpn-validation-library.rsc"
:global sdwanVPNValidate
:local cases [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="vpn-validation-cases.json"] contents]]
:local result [:toarray ""]
:foreach item in=$cases do={
 :local cfg [:deserialize from=json options=json.no-string-conversion value=($item->"config_json")]
 :local accepted true
 :local errorText ""
 :onerror rejected in={ :local ignored [$sdwanVPNValidate cfg=$cfg] } do={ :set accepted false; :set errorText $rejected }
 :set ($result->[:len $result]) {"case"=($item->"case");"expected"=($item->"expected");"accepted"=$accepted;"pass"=($accepted = ($item->"expected"));"error"=$errorText}
}
:set sdwanVPNValidationJSON [:serialize to=json value=$result options=json.no-string-conversion]
} do={ :set sdwanVPNValidationJSON [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
'''
  row=r.call('system/script',{'name':name,'source':source,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/script',row['.id']))
  row=r.call('system/scheduler',{'name':name,'interval':'1s','on-event':'/system/script/run '+name,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/scheduler',row['.id']))
  end=time.monotonic()+20
  while time.monotonic()<end:
   rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name=sdwanVPNValidationJSON']},'POST')
   if rows and rows[0].get('value','').startswith(('[','{')):break
   time.sleep(.2)
  else:raise AssertionError('No native contract report')
  report=json.loads(rows[0]['value']);(v.run/'vpn-contract-validation.json').write_text(json.dumps(report,indent=2)+'\n');assert isinstance(report,list) and len(report)==len(cases),report
  assert all(x['pass'] for x in report),[x for x in report if not x['pass']]
  print('PASS Python/native VPN contract: '+str(len(report))+' cases')
 finally:
  for menu,id in reversed(created):r.call(menu+'/'+id,method='DELETE')
  for filename in files:
   row=r.file_entry(filename)
   if row:r.call('file/'+row['.id'],method='DELETE')
  v.close();lock.close()

if __name__=='__main__':main()
