#!/usr/bin/env python3
"""CHR ONLY: restore a previous complete framework without the new DNS library.

Use a known audited compatible 40-character commit containing overlay/VPN but
no sdwan-dns.rsc. All changes target the existing SiteB; finally restores its
current native configuration/source. No keys or credentials are exported.
"""
import argparse,contextlib,copy,fcntl,importlib.util,json,re,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from vpn_lab import VPNLab
from sdwan.router import Router
from sdwan.deployment import start,wait as deployment_wait,read_state

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);p.add_argument('--legacy-commit',required=True);args=p.parse_args();assert re.fullmatch('[0-9a-f]{40}',args.legacy_commit),'Use an exact audited commit';v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);creds=json.loads((v.run/'credentials.json').read_text());r=Router(v.root,'api://127.0.0.1:55730',credentials_data=creds['siteb']);assert r.call('system/identity')['name']=='sdwan-overlay-siteb';before=json.loads(r.read_file('sdwan-active.json'));assert before.get('controller_backend','routeros')!='container';changed=False;report={'pass':False,'checks':[],'legacy_commit':args.legacy_commit}
 spec=importlib.util.spec_from_file_location('dns_rollback_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def wait(fn,timeout=120):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   if fn():return
   time.sleep(.3)
  raise AssertionError('DNS framework rollback recovery timed out')
 def healthy():
  s=r.status();return not s.get('error') and s['selected']['default']=='wan1' and all(x['healthy'] for x in s['overlay'].values()) and sum(x['state']=='Full' for x in r.call('routing/ospf/neighbor/print',{'.proplist':'state'},'POST'))==2
 def record(label):report['checks'].append({'check':label,'pass':True});print('PASS '+label,flush=True)
 def identities():return {x['name']:x['public-key'] for x in r.call('interface/wireguard/print',{'.proplist':'name,public-key,comment'},'POST') if x.get('comment','').startswith('sdwan:v1:overlay:interface:')}
 try:
  assert subprocess.run(['git','cat-file','-e',args.legacy_commit+':native/sdwan-dns.rsc'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0,'Legacy commit must predate the new library'
  legacy=copy.deepcopy(before);legacy['revision']='dns-module-legacy-baseline';cli.preflight(r,legacy,'sdwan-overlay-siteb')
  with tempfile.TemporaryDirectory(prefix='sdwan-dns-rollback-') as folder:
   package=Path(folder)/'legacy';package.mkdir()
   for filename in cli.FILES:
    if filename=='sdwan-dns.rsc':continue
    # The current generic bootstrap seals an explicit absent-file manifest.
    source=(ROOT/'native'/filename).read_text() if filename in ('sdwan-deployment.rsc','sdwan-deploy-worker.rsc','sdwan-deploy-watchdog.rsc') else subprocess.check_output(['git','show',args.legacy_commit+':native/'+filename],cwd=ROOT,text=True)
    if filename=='sdwan-controller.rsc':assert 'sdwanDNSBootstrap' not in source
    (package/filename).write_text(source)
   (package/'sdwan-config.json').write_text(json.dumps(legacy,separators=(',',':')))
   changed=True
   with (v.run/'dns-module-rollback-deploy.log').open('a') as log,contextlib.redirect_stdout(log):
    token=start(r,package,'sdwan-overlay-siteb',revision=legacy['revision'],default_policy='default');deployment_wait(r,token,'sdwan-overlay-siteb')
   wait(healthy)
   entry=r.file_entry('sdwan-dns.rsc');assert entry;r.call('file/'+entry['.id'],method='DELETE');assert r.file_entry('sdwan-dns.rsc') is None
   previous={f:r.read_file(f) for f in (*[x for x in cli.FILES if x!='sdwan-dns.rsc'],'sdwan-config.json','sdwan-active.json','sdwan-backup.json')};keys=identities();record('compatible native legacy framework is healthy with the new DNS source file genuinely absent')
   bad=copy.deepcopy(before);bad['revision']='dns-module-injected-failure';package=cli.bundle(bad,Path(folder)/'new');installer=package/'sdwan-install.rsc';installer.write_text(installer.read_text()+'\n:if ([:len [/file/find where name="sdwan-dns.rsc"]] != 1) do={ :error "new DNS module was not uploaded" }\n:error "injected failure after new DNS module import"\n')
   with (v.run/'dns-module-rollback-deploy.log').open('a') as log,contextlib.redirect_stdout(log):
    token=start(r,package,'sdwan-overlay-siteb',revision=bad['revision'],default_policy='default',timeout=45)
    try:deployment_wait(r,token,'sdwan-overlay-siteb',timeout=45)
    except RuntimeError as error:assert 'rolled-back' in str(error) and 'injected failure after new DNS module import' in str(error),str(error)
    else:raise AssertionError('Injected failing installation committed')
   assert read_state(r,token)['phase']=='rolled-back';assert r.file_entry('sdwan-dns.rsc') is None
   for name,body in previous.items():assert r.read_file(name)==body,'Previous package differs: '+name
   assert identities()==keys;wait(healthy);record('encrypted rollback restores the complete previous package and public identities, removes the newly introduced DNS file, and recovers OSPF after reboot')
  report['pass']=True
 finally:
  try:
   if changed:
    with (v.run/'dns-module-rollback-deploy.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(r,before,'sdwan-overlay-siteb')
    wait(healthy)
  finally:(v.run/'dns-module-rollback-validation.json').write_text(json.dumps(report,indent=2)+'\n');r.close();v.close();lock.close()
if __name__=='__main__':main()
