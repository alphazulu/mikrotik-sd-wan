#!/usr/bin/env python3
"""CHR ONLY: ambiguous VPN source addresses cannot escape through another exit."""
import argparse,copy,fcntl,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab

def quote(s):return '"'+s.replace('\\','\\\\').replace('"','\\"').replace('$','\\$')+'"'
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];created=[];files=[];original=None;name='vpn-duplicate-source-check'
 try:
  cfg=json.loads(r.read_file('sdwan-active.json'));assert not cfg.get('vpn_egress',{}).get('enabled'),'Restore baseline before isolated resolver test'
  for i,kind in enumerate(('wireguard','sstp'),1):
   w=copy.deepcopy(cfg['wans'][0]);w.pop('address');w.pop('gateway');w.update(v.state['links'][kind]);w.update(name='vpn'+str(i),kind='vpn',probe_table='sdwan-probe-vpn'+str(i));cfg['wans'].append(w)
  original=r.call('ip/address/print',{'.proplist':'.id,address,invalid','.query':['interface=vpn-exit-wg']},'POST')[0];assert original['address']=='10.204.1.2/30'
  r.call('ip/address/'+original['.id'],{'address':'10.204.3.2/30'},'PATCH')
  for filename,body in [('vpn-duplicate-links.rsc',(ROOT/'native/sdwan-links.rsc').read_text()),('vpn-duplicate-module.rsc',(ROOT/'native/sdwan-vpn.rsc').read_text())]:r.upload(filename,body);files.append(filename)
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name=sdwanVPNDuplicateSource']},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
  source='''/system/scheduler/disable [/system/scheduler/find where name="vpn-duplicate-source-check"]
:global sdwanVPNDuplicateSource
:onerror failure in={
/import file-name="vpn-duplicate-links.rsc"
/import file-name="vpn-duplicate-module.rsc"
:global sdwanResolveWANs
:local cfg [:deserialize from=json options=json.no-string-conversion value='''+quote(json.dumps(cfg,separators=(',',':')))+''']
:set sdwanVPNDuplicateSource [:serialize to=json value=[$sdwanResolveWANs wans=($cfg->"wans")] options=json.no-string-conversion]
} do={ :set sdwanVPNDuplicateSource [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
'''
  row=r.call('system/script',{'name':name,'source':source,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/script',row['.id']))
  row=r.call('system/scheduler',{'name':name,'interval':'1s','on-event':'/system/script/run '+name,'policy':'read,write,policy,test,sensitive','comment':name},'PUT');created.append(('system/scheduler',row['.id']))
  end=time.monotonic()+20
  while time.monotonic()<end:
   rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name=sdwanVPNDuplicateSource']},'POST')
   if rows and rows[0].get('value','').startswith(('[','{')):break
   time.sleep(.2)
  else:raise AssertionError('No native resolver report')
  data=json.loads(rows[0]['value']);assert isinstance(data,list),data;by={w['name']:w for w in data};assert by['wan1']['ready'] and by['wan2']['ready'];assert not by['vpn1']['ready'] and not by['vpn2']['ready'],by
  assert all('duplicate WAN address' in by[n]['link_reason'] for n in ('vpn1','vpn2'))
  (v.run/'vpn-duplicate-source-validation.json').write_text(json.dumps({'pass':True,'physical_wans_ready':True,'both_duplicate_vpn_sources_rejected':True},indent=2)+'\n');print('PASS native resolver rejects both duplicate VPN source bindings while physical WANs remain ready')
 finally:
  if original:r.call('ip/address/'+original['.id'],{'address':original['address']},'PATCH')
  for menu,id in reversed(created):r.call(menu+'/'+id,method='DELETE')
  for filename in files:
   row=r.file_entry(filename)
   if row:r.call('file/'+row['.id'],method='DELETE')
  v.close();lock.close()

if __name__=='__main__':main()
