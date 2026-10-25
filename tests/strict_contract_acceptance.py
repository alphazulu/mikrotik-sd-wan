from pathlib import Path
import sys,json,importlib.util,copy,time
import argparse
public=Path(__file__).resolve().parents[1];sys.path.insert(0,str(public))
p=argparse.ArgumentParser(description='CHR ONLY: native and Python strict-probe validation contract');p.add_argument('--lab-root',type=Path,required=True);args=p.parse_args();root=args.lab_root.resolve()
from sdwan.router import Router
from sdwan.probes import validate_probe
spec=importlib.util.spec_from_file_location('overlay_fixture',public/'tools/overlay_lab.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);lab=m.Lab(root)
r=Router(lab.root,'api://127.0.0.1:55728',credentials_data=json.loads((lab.run/'credentials.json').read_text())['hub']);name='sdwan-strict-contract';created=[]
patches=[{}, {'http_codes':[204]}, {'http_codes':[]}, {'http_codes':[True]}, {'http_codes':[200,200]}, {'http_codes':[503]}, {'http_codes':[503],'http_path':'/health'}, {'http_expected_body':'healthy\n'},{'http_expected_body':None},{'http_expected_body':False},{'http_expected_body':'x'*1025},{'http_expected_body':'я'*512},{'http_path':'/a?x=1'},{'http_path':'//foreign/'},{'http_path':'/%zz'},{'http_path':'/%0a'},{'http_path':None},{'type':'dns','dns_expected_ips':['192.0.2.11']},{'type':'dns','dns_expected_ips':['224.0.0.1']},{'type':'dns','dns_expected_ips':None},{'type':'tcp-conn','http_expected_body':'ok'}]
cases=[]
for i,patch in enumerate(patches):
 cfg=lab.sdwan_config('hub');cfg['wans'][0]['probes'][0].update(patch)
 try:validate_probe(cfg['wans'][0]['probes'][0]);expected=True
 except ValueError:expected=False
 cases.append({'case':i,'expected':expected,'config_json':json.dumps(cfg,separators=(',',':'))})
def q(text):return '"'+text.replace('\\','\\\\').replace('"','\\"').replace('$','\\$').replace('\r','\\r').replace('\n','\\n')+'"'
try:
 assert r.call('system/identity')['name']=='sdwan-overlay-hub'
 r.upload('sdwan-contract-library.rsc',(public/'native/sdwan-links.rsc').read_text())
 source=':global sdwanStrictContractJSON\n:if ([:pick [:tostr $sdwanStrictContractJSON] 0 1] = "{") do={ :return "" }\n/import file-name="sdwan-contract-library.rsc"\n:global sdwanValidateStrict\n:local cases [:deserialize from=json options=json.no-string-conversion value='+q(json.dumps(cases,separators=(',',':')))+']\n'+r'''
:local result [:toarray ""]
:foreach item in=$cases do={
 :local cfg [:deserialize from=json options=json.no-string-conversion value=($item->"config_json")]
 :local accepted true
 :local errorText ""
 :onerror failure in={ :local count [$sdwanValidateStrict cfg=$cfg] } do={ :set accepted false; :set errorText $failure }
 :local row [:toarray ""]; :set ($row->"case") ($item->"case"); :set ($row->"expected") ($item->"expected"); :set ($row->"accepted") $accepted; :set ($row->"pass") ($accepted = ($item->"expected")); :set ($row->"error") $errorText
 :set ($result->[:len $result]) $row
}
:set sdwanStrictContractJSON [:serialize to=json value=$result options=json.no-string-conversion]
'''
 assert len(source.encode())<64000,len(source.encode())
 for row in r.call('system/script/environment/print',{'.proplist':'.id,name','.query':['name=sdwanStrictContractJSON']},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
 for menu in ('system/scheduler','system/script'):
  for row in r.call(menu+'/print',{'.proplist':'.id,name','.query':['name='+name]},'POST'):r.call(menu+'/'+row['.id'],method='DELETE')
 row=r.call('system/script',{'name':name,'source':source,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/script',row['.id']))
 row=r.call('system/scheduler',{'name':name,'interval':'1s','on-event':'/system/script/run '+name,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/scheduler',row['.id']))
 end=time.monotonic()+15
 while time.monotonic()<end:
  rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name=sdwanStrictContractJSON']},'POST')
  if rows and rows[0].get('value','').startswith('['):break
  time.sleep(.2)
 data=json.loads(rows[0]['value']);(lab.run/'strict-contract-validation.json').write_text(json.dumps(data,indent=2)+'\n');print('PASS native/Python strict contract: '+str(len(data))+' cases',flush=True)
 assert all(row['pass'] for row in data)
finally:
 for menu,id in reversed(created):
  try:r.call(menu+'/'+id,method='DELETE')
  except Exception:pass
 row=r.file_entry('sdwan-contract-library.rsc')
 if row:r.call('file/'+row['.id'],method='DELETE')
 r.close()
