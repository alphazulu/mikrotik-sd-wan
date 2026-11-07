#!/usr/bin/env python3
"""CHR ONLY: ordinary VPN WANs, IP/list selectors, jump chains and scoped TCP."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic
from sdwan.config import validate
from sdwan.vpn_egress import add_wan

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];h=v.routers['hub'];before=json.loads(a.read_file('sdwan-active.json'));report={'pass':False,'checks':[]};created=[];traffic=None;applied=False;tag='unified-wan-acceptance-only'
 spec=importlib.util.spec_from_file_location('unified_wan_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'unified-wan-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(a,validate(c),'sdwan-overlay-sitea')
 def add(r,menu,data):
  done=r.call(menu+'/add',dict(data,comment=tag),'POST');created.append((r,menu,done['ret']));return done['ret']
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def wait(fn,timeout=120):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   s=a.status()
   if s.get('error'):raise AssertionError(s['error'])
   if fn(s):return s
   time.sleep(.3)
  raise AssertionError({'selected':s.get('selected'),'states':s.get('states'),'samples':s.get('samples')})
 try:
  cfg=copy.deepcopy(before);cfg['revision']='unified-wan-ip-list';cfg.pop('vpn_egress',None)
  for i,kind in enumerate(('wireguard','sstp'),1):cfg=add_wan(cfg,v.state['links'][kind],name='vpn'+str(i),underlays=['wan1','wan2'],masquerade=True,allow_selected_forward=True)
  for rank,name,selectors,wans in [(10,'both',dict(source_list='fixture-users',destination_list='fixture-targets'),['vpn1','vpn2','wan2','wan1']),(20,'destip',dict(destination='198.19.100.1'),['vpn2','wan1']),(30,'srcip',dict(source='10.201.2.3'),['vpn1','wan1']),(40,'srclist',dict(source_list='fixture-other-users'),['vpn2','wan1'])]:
   p=dict(name=name,source='0.0.0.0/0',table='sdwan-'+name,profile='default',mode='prefer',wans=wans,allow_degraded=False,priority=rank);p.update(selectors);cfg['policies'].append(p)
  list_ids=[add(a,'ip/firewall/address-list',dict(list=name,address=address)) for name,address in [('fixture-users','10.201.2.1'),('fixture-targets','198.19.100.1'),('fixture-other-users','10.201.2.4')]]
  applied=True;apply(cfg);wait(lambda s:s.get('selected',{}).get('both')=='vpn1' and s['selected'].get('destip')=='vpn2' and s['selected'].get('srclist')=='vpn2' and all(x['healthy'] for x in s['overlay'].values()))
  assert 'vpn_egress' not in json.loads(a.read_file('sdwan-active.json'))
  traffic=VPNTraffic(v);traffic.prepare()
  for host in ('10.201.2.3','10.201.2.4','10.201.2.5'):add(traffic.b,'ip/address',{'address':host+'/32','interface':'ether4'})
  flows={};flows['both']=traffic.stream(59410,'sdwan-out-both:vpn1');flows['destip']=traffic.stream(59411,'sdwan-out-destip:vpn2',source='10.201.2.5');flows['srcip']=traffic.stream(59412,'sdwan-out-srcip:vpn1',source='10.201.2.3',target='198.19.100.2');flows['srclist']=traffic.stream(59413,'sdwan-out-srclist:vpn2',source='10.201.2.4',target='198.19.100.2');flows['ordinary']=traffic.stream(59414,'sdwan-out-default:wan1',source='10.201.2.5',target='198.19.100.2');flows['branch']=traffic.stream(59419,'no-mark',target='10.201.1.2')
  record('physical and VPN WANs share ordinary source-IP, destination-IP, source-list and combined-list policies, with real TCP and no separate VPN configuration switch')
  rules=a.call('ip/firewall/mangle/print',{'.proplist':'chain,comment,action,jump-target,src-address-list,dst-address-list,new-connection-mark'},'POST');jump=next(x for x in rules if x.get('comment')=='sdwan:v1:policy-jump:both');assert jump['action']=='jump' and jump['src-address-list']=='fixture-users' and jump['dst-address-list']=='fixture-targets';assert all(x['chain']==jump['jump-target'] and 'src-address-list' not in x and 'dst-address-list' not in x for x in rules if x.get('comment','').startswith('sdwan:v1:classify:both:'))
  record('one readable selector jump enters a stable policy chain; WAN classifiers and fail-closed guard share that chain')
  a.call('ip/firewall/address-list/'+list_ids[0],method='DELETE');created.remove((a,'ip/firewall/address-list',list_ids[0]));time.sleep(1);traffic.stream(59415,'sdwan-out-destip:vpn2');traffic.assert_sessions(retained=list(flows.values()));add(a,'ip/firewall/address-list',dict(list='fixture-users',address='10.201.2.1'));time.sleep(1)
  record('live MikroTik source-list removal changes new-flow selection while existing marked flows and private TCP survive')
  block=add(h,'ip/firewall/filter',{'chain':'forward','in-interface':'vpn-server-wg','dst-address':'198.19.100.1','protocol':'tcp','dst-port':'58081-58083','action':'drop','place-before':'0'})
  wait(lambda s:s['selected']['both']=='vpn2' and s['selected']['srcip']=='wan1');traffic.assert_sessions(absent=[flows['both'],flows['srcip']],retained=[flows['destip'],flows['srclist'],flows['ordinary'],flows['branch']]);traffic.stream(59416,'sdwan-out-both:vpn2')
  record('VPN resource SLA failure applies each ordinary policy priority independently and retires only affected connection marks')
  h.call('ip/firewall/filter/'+block,method='DELETE');created.remove((h,'ip/firewall/filter',block));wait(lambda s:s['selected']['both']=='vpn1' and s['selected']['srcip']=='vpn1');traffic.assert_sessions(retained=[flows['ordinary'],flows['branch']]);traffic.close();traffic=None
  record('preferred VPN WAN automatically returns after fresh SLA without resetting unrelated Internet or branch sessions')
  cfg2=copy.deepcopy(cfg);cfg2['revision']='unified-default-vpn';next(p for p in cfg2['policies'] if not p['source'])['wans']=['vpn1','wan1','wan2'];apply(cfg2);wait(lambda s:s['selected']['default']=='vpn1' and s['vpn_egress']['vpn1']['underlay']=='wan1')
  traffic=VPNTraffic(v);traffic.prepare();traffic.stream(59410,'sdwan-out-default:vpn1',source='10.201.2.5',target='198.19.100.2')
  record('the general Internet policy can also prefer a VPN WAN while the tunnel transport remains pinned to its physical provider')
  report['pass']=True
 finally:
  # Extra client addresses must be removed before the traffic fixture closes its
  # Router handles. Retain the addresses through both traffic phases above.
  for r,menu,id in reversed(created):
   if menu=='ip/address':
    try:r.call(menu+'/'+id,method='DELETE')
    except RuntimeError:pass
  if traffic:traffic.close()
  for r,menu,id in reversed(created):
   if menu=='ip/address':continue
   try:r.call(menu+'/'+id,method='DELETE')
   except RuntimeError:pass
  try:
   if applied:apply(before)
  finally:(v.run/'unified-wan-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
