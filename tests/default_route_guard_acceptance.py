#!/usr/bin/env python3
"""CHR ONLY: API/native read-only preflight rejects undeclared full defaults."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['hub'];before=json.loads(r.read_file('sdwan-active.json'));report={'checks':[],'pass':False};created=[];tag='sdwan-default-guard-acceptance';filename=tag+'.json';output='sdwanDefaultGuardJSON'
 spec=importlib.util.spec_from_file_location('default_guard_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def add(menu,data):
  done=r.call(menu+'/add',dict(data,comment=tag),'POST');created.append((menu,done['ret']));return done['ret']
 def clear():
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+output]},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
 def native(c):
  clear();r.upload(filename,json.dumps(c,separators=(',',':')));r.call('system/scheduler/set',{'.id':scheduler,'disabled':'false'},'POST');end=time.monotonic()+15
  while time.monotonic()<end:
   rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name='+output]},'POST')
   if rows and rows[0].get('value','').startswith('{'):return json.loads(rows[0]['value'])
   time.sleep(.1)
  raise AssertionError('Native read-only preflight did not finish')
 def check(label,c,accepted):
  try:
   with (v.run/'default-guard-preflight.log').open('a') as log,contextlib.redirect_stdout(log):cli.preflight(r,c,'sdwan-overlay-hub')
   api=True
  except ValueError:api=False
  result=native(c);assert api==accepted and result['accepted']==accepted,{'case':label,'api':api,'native':result}
  report['checks'].append({'check':label,'pass':True});print('PASS '+label,flush=True)
 try:
  assert not r.call('system/script/print',{'.proplist':'.id','.query':['name='+tag]},'POST') and not r.file_entry(filename),'Previous guard test must not be duplicated'
  # Execute the actual installer's read-only prefix, before ANY scheduler,
  # firewall, route or backup mutation; do not maintain a second guard copy.
  source=(ROOT/'native/sdwan-install.rsc').read_text().split(':if ([:tostr [/ip/firewall/connection/tracking/get enabled]]',1)[0];assert 'undeclared default route would bypass' in source and '/system/scheduler/disable' not in source;source=source.replace('"sdwan-config.json"','"'+filename+'"')
  script=add('system/script',{'name':tag,'source':'/system/scheduler/disable [/system/scheduler/find where name="'+tag+'"]\n:global '+output+'\n:onerror failure in={\n'+source+'\n:set '+output+' "{\\"accepted\\":true}"\n} do={ :set '+output+' [:serialize to=json value={"accepted"=false;"reason"=$failure} options=json.no-string-conversion] }','policy':'read,write,policy,test,sensitive'})
  scheduler=add('system/scheduler',{'name':tag,'interval':'1s','disabled':'true','on-event':'/system/script/run '+tag,'policy':'read,write,policy,test,sensitive'})
  check('existing managed defaults pass API and native preflight',before,True)
  rid=add('ip/route',{'dst-address':'0.0.0.0/0','gateway':'198.18.100.2','routing-table':'main','distance':'250','disabled':'true'})
  check('a disabled foreign default is inert and passes both gates',before,True)
  r.call('ip/route/set',{'.id':rid,'disabled':'false'},'POST');check('an enabled lower-priority foreign default is rejected before it can bypass a future SLA closure',before,False)
  adopted=copy.deepcopy(before);adopted.setdefault('takeover_routes',[]).append({'.id':rid,'dst-address':'0.0.0.0/0','gateway':'198.18.100.2','routing-table':'main'});check('explicit exact static route adoption passes both gates',adopted,True)
  stale=copy.deepcopy(adopted);stale['takeover_routes'][-1]['gateway']='198.18.100.10';check('a stale adoption selector cannot authorize a changed default',stale,False)
  report['pass']=True
 finally:
  for menu,id in reversed(created):r.call(menu+'/'+id,method='DELETE')
  row=r.file_entry(filename)
  if row:r.call('file/'+row['.id'],method='DELETE')
  clear();(v.run/'default-route-guard-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
