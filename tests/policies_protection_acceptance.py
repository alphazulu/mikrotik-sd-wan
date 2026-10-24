#!/usr/bin/env python3
"""CHR ONLY: bounded native history, validation and full selector update restore."""
import contextlib,copy,importlib.util,io,json,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.config import load
from sdwan.router import Router
from sdwan.deployment import start,wait as deployment_wait,read_state
spec=importlib.util.spec_from_file_location('cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
 r=Router(ROOT,'api://127.0.0.1:18728');base=load(ROOT/'config/sdwan.json');report={'checks':[]};files=('sdwan-test-policy-components.rsc','sdwan-test-policy-components.json')
 def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
 def healthy():
  end=time.monotonic()+60
  while time.monotonic()<end:
   s=r.status()
   if s.get('error'):raise AssertionError(s)
   if s.get('revision')=='lab-v1' and s.get('states') and all(x['state']=='healthy' for x in s['states'].values()):return
   time.sleep(.3)
  raise AssertionError(s)
 def apply():
  with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,base,'sdwan-edge')
  healthy()
 def reject(candidate,expected,append=''):
  previous={name:r.read_file(name) for name in (*cli.FILES,'sdwan-config.json','sdwan-active.json','sdwan-backup.json')}
  with tempfile.TemporaryDirectory(prefix='sdwan-policy-protection-') as folder:
   package=cli.bundle(candidate,folder)
   if append:
    p=package/'sdwan-install.rsc';p.write_text(p.read_text()+append)
   token=start(r,package,'sdwan-edge',revision=candidate['revision'],default_policy='default',timeout=40)
   try:deployment_wait(r,token,'sdwan-edge',timeout=40)
   except RuntimeError as error:assert 'rolled-back' in str(error) and expected in str(error),str(error)
   else:raise AssertionError('Invalid update committed')
   assert read_state(r,token)['phase']=='rolled-back'
  for name,text in previous.items():assert r.read_file(name)==text,name
  healthy()
 try:
  assert r.call('system/identity')['name']=='sdwan-edge';healthy()
  r.upload(files[1],'{}')
  code=(ROOT/'native/sdwan-links.rsc').read_text()+'''
:global sdwanEvents
:global sdwanEventSequence
:global sdwanRecordEvent
:local previous [:deserialize from=json options=json.no-string-conversion value=[:serialize to=json value=$sdwanEvents options=json.no-string-conversion]]
:local seq $sdwanEventSequence
:local event [:toarray ""]
:set ($event->"type") "test"
:for n from=1 to=105 do={ $sdwanRecordEvent event=$event revision="policy-component-test" }
:local result [:toarray ""]
:set ($result->"count") [:len $sdwanEvents]
:set ($result->"first") (($sdwanEvents->0)->"seq")
:set ($result->"last") (($sdwanEvents->99)->"seq")
:set sdwanEvents $previous
:set sdwanEventSequence $seq
/file/set [/file/find where name="sdwan-test-policy-components.json"] contents=[:serialize to=json value=$result options=json.no-string-conversion]
'''
  r.call('system/scheduler/disable',{'numbers':'sdwan-controller'},'POST')
  try:
   end=time.monotonic()+6
   while any(x.get('script')=='sdwan-controller' for x in r.call('system/script/job')):
    if time.monotonic()>end:raise AssertionError('Controller busy')
    time.sleep(.1)
   r.upload(files[0],code);r.call('import',{'file-name':files[0]},'POST');result=json.loads(r.read_file(files[1]));assert result['count']==100 and result['last']-result['first']==99,result
  finally:r.call('system/scheduler/enable',{'numbers':'sdwan-controller'},'POST')
  record('native RAM journal keeps exactly100 latest ordered events and leaves no persistent event file')
  invalid=copy.deepcopy(base);invalid['revision']='native-invalid-policy';invalid['policies'][0]['protocol']='tcp'
  reject(invalid,'default policy must not have selectors')
  record('native installer rejects a selector on main/default before applying policy changes; watchdog restores previous package')
  candidate=copy.deepcopy(base);candidate['revision']='group-injected-error';candidate['groups']={'test-members':['192.168.50.101/32']}
  for i,p in enumerate(candidate['policies'][1:],1):p['priority']=100+i
  candidate['policies'].append(dict(name='new-app',source='0.0.0.0/0',source_group='test-members',protocol='tcp',dst_ports='443',priority=10,table='sdwan-new-app',profile='default',mode='strict',wans=['wan2'],allow_degraded=False))
  reject(candidate,'injected failure after group selectors','''
:if ([:len [/ip/firewall/address-list/find where list="sdwan-group-test-members"]] != 1) do={ :error "fixture group was not installed" }
:if ([:len [/ip/firewall/mangle/find where comment="sdwan:v1:classify:new-app:wan2"]] != 1) do={ :error "fixture selector was not installed" }
:error "injected failure after group selectors"
''')
  assert not any(x.get('list')=='sdwan-group-test-members' for x in r.call('ip/firewall/address-list'))
  record('worker error after actual group/selector mutation restores encrypted binary backup, all8 RSC/config files, original groups and controller after reboot')
 except Exception as error:
  report['checks'].append({'check':'policy protection interrupted','pass':False,'detail':str(error)});raise
 finally:
  r.close()
  try:
   for row in r.call('file/print',{'.proplist':'.id,name'},'POST'):
    if row['name'] in files:r.call('file/'+row['.id'],method='DELETE')
   apply()
  finally:(ROOT/'runtime/policies-protection-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()

if __name__=='__main__':main()
