#!/usr/bin/env python3
"""CHR ONLY: native Address List selector types, byte length and control bytes."""
import argparse,fcntl,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.policies import validate_selectors

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];created=[];files=[];name='address-list-contract';cases=[]
 values=['','existing targets','кириллица','!negated',' leading','trailing ','x'*65,'я'*33,None,False,1]+['x'+chr(i)+'y' for i in list(range(32))+[127]]
 for n,value in enumerate(values):
  cfg={'policies':[dict(name='targets',priority=10,source='0.0.0.0/0',destination_list=value)]}
  try:validate_selectors(cfg);expected=True
  except ValueError:expected=False
  cases.append(dict(case=n,expected=expected,config_json=json.dumps(cfg,separators=(',',':'))))
 try:
  assert not r.call('system/script/print',{'.proplist':'name','.query':['name='+name]},'POST')
  for filename,body in [('address-list-contract.rsc',(ROOT/'native/sdwan-links.rsc').read_text()),('address-list-contract.json',json.dumps(cases,separators=(',',':')))]:r.upload(filename,body);files.append(filename)
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name=sdwanAddressListContract']},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
  source='''/system/scheduler/disable [/system/scheduler/find where name="address-list-contract"]
:global sdwanAddressListContract
:onerror failure in={
/import file-name="address-list-contract.rsc"
:global sdwanValidatePolicyLists
:local cases [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="address-list-contract.json"] contents]]
:local result [:toarray ""]
:foreach item in=$cases do={
 :local cfg [:deserialize from=json options=json.no-string-conversion value=($item->"config_json")]
 :local accepted true
 :onerror invalid in={ :local ignored [$sdwanValidatePolicyLists cfg=$cfg] } do={ :set accepted false }
 :set ($result->[:len $result]) {"case"=($item->"case");"expected"=($item->"expected");"accepted"=$accepted;"pass"=($accepted = ($item->"expected"))}
}
:set sdwanAddressListContract [:serialize to=json value=$result options=json.no-string-conversion]
} do={ :set sdwanAddressListContract [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
'''
  row=r.call('system/script',{'name':name,'source':source,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/script',row['.id']))
  row=r.call('system/scheduler',{'name':name,'interval':'1s','on-event':'/system/script/run '+name,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/scheduler',row['.id']))
  end=time.monotonic()+20
  while time.monotonic()<end:
   rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name=sdwanAddressListContract']},'POST')
   if rows and rows[0].get('value','').startswith(('[','{')):break
   time.sleep(.2)
  else:raise AssertionError('No native Address List contract report')
  report=json.loads(rows[0]['value']);(v.run/'address-list-contract-validation.json').write_text(json.dumps(report,indent=2)+'\n');assert isinstance(report,list) and len(report)==len(cases),report;assert all(x['pass'] for x in report),[x for x in report if not x['pass']];print('PASS Python/native Address List contract: '+str(len(report))+' cases')
 finally:
  for menu,id in reversed(created):r.call(menu+'/'+id,method='DELETE')
  for filename in files:
   row=r.file_entry(filename)
   if row:r.call('file/'+row['.id'],method='DELETE')
  v.close();lock.close()

if __name__=='__main__':main()
