#!/usr/bin/env python3
"""CHR ONLY: key preparation creates a disabled identity using public-only reads."""
import argparse,fcntl,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.overlay_runtime import prepare_keys,inventory,PREFIX

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];request=[{'name':'key-api-acceptance','listen_port':52991}];name='sdwan-wg-'+request[0]['name'];report={'checks':[],'pass':False};calls=[];cleanup=False
 class PublicRouter:
  def read_file(self,*args):return r.read_file(*args)
  def call(self,path,data=None,method=None):
   if path.startswith('interface/wireguard'):
    calls.append((path,method))
    assert method!='PUT' and method!='PATCH','unrestricted native readback must not occur'
    if path.endswith('/print'):assert data and '.proplist' in data and not any(k in data['.proplist'] for k in ('private-key','preshared-key'))
    elif method!='DELETE':assert path=='interface/wireguard/add' and method=='POST'
   return r.call(path,data,method)
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 try:
  assert not any(row['name']==name or int(row['listen-port'])==52991 for row in inventory(r)),'fixture name/port collision'
  cleanup=True
  router=PublicRouter();first=prepare_keys(router,request,'sdwan-overlay-sitea');row=next(x for x in inventory(router) if x['name']==name);assert row['disabled']=='true' and row['public-key']==first[0]['public_key']
  record('actual API add returns an ID without unrestricted readback; a disabled identity is read through public-only property lists')
  assert prepare_keys(router,request,'sdwan-overlay-sitea')==first and sum(path=='interface/wireguard/add' for path,_ in calls)==1
  record('repeated preparation preserves the on-router identity without generating another key')
  report['pass']=True
 finally:
  for row in inventory(r):
   if cleanup and row.get('name')==name and row.get('comment')==PREFIX+request[0]['name'] and row.get('disabled')=='true':r.call('interface/wireguard/'+row['.id'],method='DELETE')
  (v.run/'overlay-key-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
