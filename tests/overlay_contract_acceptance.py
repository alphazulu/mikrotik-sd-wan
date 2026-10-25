#!/usr/bin/env python3
"""CHR ONLY: compare the optional overlay model with native read-only preflight."""
import argparse,copy,fcntl,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.overlay import validate

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];before=json.loads((v.root/'config/overlay-sitea.json').read_text());name='overlay-contract-acceptance';output='sdwanOverlayContractJSON';cases=[];created=[];files=[];report=[]
 def add(label,c):
  try:validate(c);expected=True
  except ValueError:expected=False
  cases.append({'case':label,'expected':expected,'config_json':json.dumps(c,separators=(',',':'))})
 add('existing dual WAN branch',before);c=copy.deepcopy(before);c['overlay']={'enabled':False};add('default off',c)
 mutations=[('typed enabled',{'enabled':'true'}),('null enabled',{'enabled':None}),('numeric enabled',{'enabled':0}),('disabled with extra settings',{'enabled':False,'password':'forbidden-placeholder'}),('unknown top-level option',{'password':'forbidden-placeholder'}),('null block',None),('invalid role',{'role':'other'}),('empty site prefixes',{'local_prefixes':[]}),('empty remote prefixes',{'remote_prefixes':[]}),('null MTU',{'mtu':None}),('boolean MTU',{'mtu':True}),('oversize MTU',{'mtu':1500}),('null MSS',{'mss_clamp':None}),('typed MSS',{'mss_clamp':'yes'}),('null health',{'health':None}),('unknown health option',{'health':{'parallel':1}}),('probe train exceeds interval',{'health':{'packet_count':20,'interval_seconds':1}}),('stale budget too short',{'health':{'stale_seconds':2}}),('zero recovery windows',{'health':{'recover_windows':0}}),('overlapping site networks',{'remote_prefixes':before['overlay']['local_prefixes']}),('local link-local prefix',{'local_prefixes':['169.254.12.0/24']}),('noncanonical site prefix',{'local_prefixes':['10.201.1.1/24']})]
 for label,patch in mutations:
  c=copy.deepcopy(before)
  if patch is None:c['overlay']=None
  else:c['overlay'].update(patch)
  add(label,c)
 for ip in ('0.0.0.0','127.0.0.1','224.0.0.1','169.254.1.1'):
  c=copy.deepcopy(before);c['overlay']['router_id']=ip;add('forbidden router ID '+ip,c)
 for label,patch in [('unknown tunnel secret',{'password':'forbidden-placeholder'}),('invalid peer key',{'peer_public_key':'not-a-key'}),('zero peer key',{'peer_public_key':'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA='}),('same local and peer key',{'peer_public_key':before['overlay']['tunnels'][0]['local_public_key']}),('zero endpoint port',{'endpoint_port':0}),('large endpoint port',{'endpoint_port':65536}),('short keepalive',{'keepalive_seconds':2}),('recursive endpoint',{'endpoint':'10.201.2.10'}),('invalid hostname',{'endpoint':'http://hub/'}),('empty peer prefixes',{'peer_prefixes':[]}),('unexported peer prefix',{'peer_prefixes':['10.210.0.0/24']}),('duplicate peer prefixes',{'peer_prefixes':['10.201.2.0/24','10.201.2.0/24']}),('broadcast peer on /30',{'address':'10.203.10.1/30','peer_address':'10.203.10.3'}),('link overlaps remote site',{'address':'10.201.2.0/31','peer_address':'10.201.2.1'})]:
  c=copy.deepcopy(before);c['overlay']['tunnels'][0].update(patch);add(label,c)
 c=copy.deepcopy(before);c['overlay']['role']='hub';c['overlay']['local_prefixes']=[]
 for t in c['overlay']['tunnels']:
  for field in ('endpoint','endpoint_port','keepalive_seconds'):t.pop(field,None)
 add('hub responder only',c);c=copy.deepcopy(c);c['overlay']['tunnels'][0]['endpoint']='';add('hub forbids even empty endpoint option',c)
 try:
  assert not r.call('system/script/print',{'.proplist':'.id','.query':['name='+name]},'POST') and not r.file_entry(name+'.json'),'Previous contract test must not be duplicated'
  for filename,body in [(name+'.rsc',(ROOT/'native/sdwan-overlay.rsc').read_text())]:r.upload(filename,body);files.append(filename)
  source='''/system/scheduler/disable [/system/scheduler/find where name="overlay-contract-acceptance"]
:global sdwanOverlayContractJSON
:onerror failure in={
/import file-name="overlay-contract-acceptance.rsc"
:global sdwanOverlayValidate
:local cases [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="overlay-contract-acceptance.json"] contents]]
:local results [:toarray ""]
:foreach item in=$cases do={
 :local cfg [:deserialize from=json options=json.no-string-conversion value=($item->"config_json")]
 :local accepted true
 :local reason ""
 :onerror rejected in={ :local ignored [$sdwanOverlayValidate cfg=$cfg] } do={ :set accepted false; :set reason $rejected }
 :set ($results->[:len $results]) {"case"=($item->"case");"expected"=($item->"expected");"accepted"=$accepted;"pass"=($accepted = ($item->"expected"));"reason"=$reason}
}
:set sdwanOverlayContractJSON [:serialize to=json value=$results options=json.no-string-conversion]
} do={ :set sdwanOverlayContractJSON [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
'''
  done=r.call('system/script/add',{'name':name,'source':source,'policy':'read,write,policy,test,sensitive','comment':name},'POST');created.append(('system/script',done['ret']));done=r.call('system/scheduler/add',{'name':name,'interval':'1s','disabled':'true','on-event':'/system/script/run '+name,'policy':'read,write,policy,test,sensitive','comment':name},'POST');created.append(('system/scheduler',done['ret']));scheduler=done['ret']
  for offset in range(0,len(cases),8):
   batch=cases[offset:offset+8];payload=json.dumps(batch,separators=(',',':'));assert len(payload.encode())<60000
   for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+output]},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
   r.upload(name+'.json',payload)
   if name+'.json' not in files:files.append(name+'.json')
   r.call('system/scheduler/set',{'.id':scheduler,'disabled':'false'},'POST');end=time.monotonic()+20
   while time.monotonic()<end:
    rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name='+output]},'POST')
    if rows and rows[0].get('value','').startswith(('[','{')):break
    time.sleep(.1)
   else:raise AssertionError('No native overlay contract report')
   result=json.loads(rows[0]['value']);assert isinstance(result,list) and len(result)==len(batch),result;report.extend(result)
  (v.run/'overlay-contract-validation.json').write_text(json.dumps(report,indent=2)+'\n');failed=[x for x in report if not x['pass']];assert not failed,failed;print('PASS Python/native overlay contract: '+str(len(report))+' cases',flush=True)
 finally:
  for menu,id in reversed(created):r.call(menu+'/'+id,method='DELETE')
  for filename in files:
   row=r.file_entry(filename)
   if row:r.call('file/'+row['.id'],method='DELETE')
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+output]},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
  v.close();lock.close()

if __name__=='__main__':main()
