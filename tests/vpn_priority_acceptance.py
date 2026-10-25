#!/usr/bin/env python3
"""CHR ONLY: two VPN exits, physical backups, all-down and independent OSPF."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic
from sdwan.config import validate

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];h=v.routers['hub'];before=json.loads(a.read_file('sdwan-active.json'));report={'checks':[],'pass':False};created=[];disabled=[];traffic=None;applied=False;tag='vpn-priority-acceptance-only'
 spec=importlib.util.spec_from_file_location('vpn_priority_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'vpn-protected-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(a,validate(c),'sdwan-overlay-sitea')
 def add(r,menu,data):
  row=r.call(menu,dict(data,comment=tag),'PUT');created.append((r,menu,row['.id']));return row['.id']
 def remove(r,menu,id):r.call(menu+'/'+id,method='DELETE');created.remove((r,menu,id))
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def wait(fn,timeout=75):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   s=a.status()
   if s.get('error'):raise AssertionError(s['error'])
   if fn(s):return s
   time.sleep(.3)
  raise AssertionError(s)
 try:
  cfg=copy.deepcopy(before);cfg['revision']='vpn-priority-matrix';cfg['vpn_egress']={'enabled':True,'masquerade':True,'allow_selected_forward':True}
  for i,kind in enumerate(('wireguard','sstp'),1):
   w=copy.deepcopy(cfg['wans'][0]);w.pop('address');w.pop('gateway');w.update(v.state['links'][kind]);w.update(name='vpn'+str(i),kind='vpn',probe_table='sdwan-probe-vpn'+str(i));cfg['wans'].append(w)
  cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',destination_list='vpn-priority-targets',priority=10,wans=['vpn1','vpn2','wan1','wan2'],table='sdwan-vpn-targets',profile='default',mode='prefer',allow_degraded=False))
  add(a,'ip/firewall/address-list',{'list':'vpn-priority-targets','address':'198.19.100.1'});applied=True;apply(cfg)
  wait(lambda s:s['selected'].get('vpn-targets')=='vpn1' and all(x['state']=='healthy' for x in s['states'].values()) and all(x['healthy'] for x in s['overlay'].values()))
  traffic=VPNTraffic(v);traffic.prepare();first=traffic.stream(59410,'sdwan-out-vpn-targets:vpn1');ordinary=traffic.stream(59411,'sdwan-out-default:wan1',target='198.19.100.2');branch=traffic.stream(59419,'no-mark',target='10.201.1.2')
  record('two healthy VPN exits share the common engine; matched TCP prefers VPN1 while ordinary and branch traffic remain independent')
  wg_block=add(h,'ip/firewall/filter',{'chain':'forward','in-interface':'vpn-server-wg','dst-address':'198.19.100.1','protocol':'tcp','dst-port':'58081-58083','action':'drop','place-before':'0'})
  wait(lambda s:s['selected']['vpn-targets']=='vpn2');traffic.assert_sessions(absent=[first],retained=[ordinary,branch]);second=traffic.stream(59412,'sdwan-out-vpn-targets:vpn2')
  record('VPN1 target failure selects the lower-priority VPN2 and retires only affected TCP conntrack')
  sstp_block=add(h,'ip/firewall/filter',{'chain':'forward','in-interface':'<sstp-vpn-lab-sstp>','dst-address':'198.19.100.1','protocol':'tcp','dst-port':'58081-58083','action':'drop','place-before':'0'})
  wait(lambda s:s['selected']['vpn-targets']=='wan1');traffic.assert_sessions(absent=[second],retained=[ordinary,branch]);third=traffic.stream(59414,'sdwan-out-vpn-targets:wan1')
  record('failure of both VPN exits selects the declared physical backup without resetting other policy or branch streams')
  physical_blocks=[]
  for wan in cfg['wans'][:2]:physical_blocks.append(add(a,'ip/firewall/filter',{'chain':'output','src-address':wan['address'],'dst-address':wan['icmp_target'],'protocol':'tcp','dst-port':'58081-58083','action':'drop','place-before':'0'}))
  wait(lambda s:s['selected']['vpn-targets']=='none' and s['selected']['default']=='none')
  routes=a.call('ip/route/print',{'.proplist':'routing-table,active,blackhole'},'POST');assert any(x.get('routing-table')=='sdwan-vpn-targets' and x.get('active')=='true' and 'blackhole' in x for x in routes)
  traffic.assert_sessions(absent=[third,ordinary],retained=[branch]);record('all declared egress SLA failures activate the policy blackhole while private OSPF TCP continues')
  remove(h,'ip/firewall/filter',wg_block)
  wait(lambda s:s['selected']['vpn-targets']=='vpn1' and s['selected']['default']=='none');traffic.assert_sessions(retained=[branch]);traffic.stream(59415,'sdwan-out-vpn-targets:vpn1')
  record('preferred VPN recovers through a ready physical underlay even while generic main Internet policy is SLA-closed')
  for id in physical_blocks:remove(a,'ip/firewall/filter',id)
  remove(h,'ip/firewall/filter',sstp_block)
  wait(lambda s:s['selected']['default']=='wan1' and s['selected']['vpn-targets']=='vpn1' and all(x['state']=='healthy' for x in s['states'].values()));traffic.assert_sessions(retained=[branch]);traffic.close();traffic=None
  record('recovering other exits keeps the highest-priority VPN selected and preserves the branch stream')
  for iface in ('ether2','ether3'):
   row=a.call('interface/print',{'.proplist':'.id,disabled','.query':['name='+iface]},'POST')[0];assert row['disabled']=='false';disabled.append(row['.id']);a.call('interface/'+row['.id'],{'disabled':'true'},'PATCH')
  wait(lambda s:s['selected']['vpn-targets']=='none' and all(not x['transport_ready'] for x in s['vpn_egress'].values()))
  record('loss of all physical underlays makes both logical VPN exits unavailable and fails closed')
  for id in disabled:a.call('interface/'+id,{'disabled':'false'},'PATCH')
  disabled=[];wait(lambda s:s['selected']['vpn-targets']=='vpn1' and all(x['state']=='healthy' for x in s['states'].values()) and all(x['healthy'] for x in s['overlay'].values()));report['pass']=True
 finally:
  for id in disabled:a.call('interface/'+id,{'disabled':'false'},'PATCH')
  if traffic:traffic.close()
  for r,menu,id in reversed(created):
   try:r.call(menu+'/'+id,method='DELETE')
   except RuntimeError:pass
  try:
   if applied:apply(before)
  finally:(v.run/'vpn-priority-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
