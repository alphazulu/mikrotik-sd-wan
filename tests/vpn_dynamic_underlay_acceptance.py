#!/usr/bin/env python3
"""CHR ONLY: DHCP/PPPoE parent lease change with VPN egress and branch OSPF."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic
from sdwan.router import Router
from sdwan.config import validate

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);p.add_argument('--kind',required=True,choices=['dhcp','pppoe']);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];creds=json.loads((v.run/'credentials.json').read_text());n=Router(v.root,'api://127.0.0.1:55731',credentials_data=creds['nata']);assert n.call('system/identity')['name']=='sdwan-overlay-nata'
 before=json.loads(a.read_file('sdwan-active.json'));report={'kind':args.kind,'checks':[],'pass':False};created=[];applied=False;traffic=None;tag='vpn-dynamic-underlay-only';vlan='vpn-dyn-underlay';iface=vlan if args.kind=='dhcp' else 'vpn-dyn-pppoe';menu='ip/dhcp-client' if args.kind=='dhcp' else 'interface/pppoe-client'
 spec=importlib.util.spec_from_file_location('vpn_dynamic_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'vpn-protected-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(a,validate(c),'sdwan-overlay-sitea')
 def add(r,menu,data):
  done=r.call(menu+'/add',dict(data,comment=tag),'POST');created.append((r,menu,done['ret']));return done['ret']
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def wait(fn,timeout=120):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   if fn():return
   time.sleep(.3)
  raise AssertionError({'timeout':a.status()})
 def healthy(ip):
  s=a.status()
  if s.get('error'):raise AssertionError(s['error'])
  return s.get('selected',{}).get('vpn-targets')=='vpn1' and s['selected'].get('default')=='wan1' and s['samples']['wan1']['address']==ip and s['vpn_egress']['vpn1']['underlay']=='wan1' and all(x['healthy'] for x in s['overlay'].values()) and len([x for x in a.call('routing/ospf/neighbor/print',{'.proplist':'state'},'POST') if x.get('state','').lower()=='full'])==2
 try:
  for r in (a,n):assert not r.call('interface/print',{'.proplist':'.id','.query':['name='+vlan]},'POST'),'Existing dynamic-underlay fixture must not be duplicated'
  add(a,'interface/vlan',{'name':vlan,'interface':'ether2','vlan-id':'3201'});add(n,'interface/vlan',{'name':vlan,'interface':'ether3','vlan-id':'3201'})
  add(n,'ip/firewall/filter',{'chain':'forward','src-address':'100.64.30.0/29','out-interface':'ether2','action':'accept','place-before':'0'})
  if args.kind=='dhcp':
   add(n,'ip/address',{'address':'100.64.30.1/29','interface':vlan});pool=add(n,'ip/pool',{'name':vlan,'ranges':'100.64.30.2'});add(n,'ip/dhcp-server/network',{'address':'100.64.30.0/29','gateway':'100.64.30.1'});add(n,'ip/dhcp-server',{'name':vlan,'interface':vlan,'address-pool':vlan,'lease-time':'2m','disabled':'false'})
   add(n,'ip/firewall/filter',{'chain':'input','in-interface':vlan,'protocol':'udp','dst-port':'67','action':'accept','place-before':'0'});add(a,'ip/firewall/filter',{'chain':'input','in-interface':vlan,'protocol':'udp','dst-port':'68','action':'accept','place-before':'0'})
   client=add(a,menu,{'interface':vlan,'add-default-route':'yes','use-peer-dns':'no','disabled':'false'})
  else:
   # Reuse an already private fixture credential; never include it in reports,
   # CLI arguments, generated public JSON or repository history.
   password=json.loads((v.run/'vpn-fixture-auth.json').read_text())['l2tp']['password']
   add(n,'ppp/profile',{'name':vlan,'local-address':'100.64.30.1','remote-address':'100.64.30.2','change-tcp-mss':'yes'})
   secret=add(n,'ppp/secret',{'name':vlan,'password':password,'service':'pppoe','profile':vlan})
   add(n,'interface/pppoe-server/server',{'interface':vlan,'service-name':vlan,'default-profile':vlan,'authentication':'chap','disabled':'false'})
   client=add(a,menu,{'name':iface,'interface':vlan,'service-name':vlan,'user':vlan,'password':password,'add-default-route':'yes','use-peer-dns':'no','disabled':'false'})
  add(a,'interface/list/member',{'list':'WAN','interface':iface});add(a,'ip/firewall/nat',{'chain':'srcnat','out-interface':iface,'action':'masquerade'})
  wait(lambda:any(x.get('interface')==iface and x.get('address','').split('/')[0]=='100.64.30.2' for x in a.call('ip/address/print',{'.proplist':'interface,address'},'POST')))
  cfg=copy.deepcopy(before);cfg['revision']='vpn-dynamic-'+args.kind;cfg['vpn_egress']={'enabled':True,'masquerade':True,'allow_selected_forward':True};cfg['wans'][0].pop('address');cfg['wans'][0].pop('gateway');cfg['wans'][0].update(interface=iface,kind=args.kind);w=copy.deepcopy(before['wans'][0]);w.pop('address');w.pop('gateway');w.update(v.state['links']['wireguard']);w.update(name='vpn1',kind='vpn',probe_table='sdwan-probe-vpn1');cfg['wans'].append(w);cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',destination_list='vpn-dynamic-targets',priority=10,wans=['vpn1','wan1','wan2'],table='sdwan-vpn-targets',profile='default',mode='prefer',allow_degraded=False));add(a,'ip/firewall/address-list',{'list':'vpn-dynamic-targets','address':'198.19.100.1'})
  applied=True;apply(cfg);wait(lambda:healthy('100.64.30.2'));traffic=VPNTraffic(v);traffic.prepare();traffic.stream(59410,'sdwan-out-vpn-targets:vpn1');branch=traffic.stream(59419,'no-mark',target='10.201.1.2')
  record(args.kind+' parent is resolved from its live lease; WireGuard resource SLA and both OSPF legs admit real TCP')
  a.call(menu+'/set',{'.id':client,'disabled':'true'},'POST')
  if args.kind=='dhcp':
   n.call('ip/pool/set',{'.id':pool,'ranges':'100.64.30.3'},'POST')
   for row in n.call('ip/dhcp-server/lease/print',{'.proplist':'.id','.query':['server='+vlan]},'POST'):n.call('ip/dhcp-server/lease/'+row['.id'],method='DELETE')
  else:n.call('ppp/secret/set',{'.id':secret,'remote-address':'100.64.30.3'},'POST')
  wait(lambda:a.status().get('vpn_egress',{}).get('vpn1',{}).get('underlay')=='wan2')
  a.call(menu+'/set',{'.id':client,'disabled':'false'},'POST');wait(lambda:healthy('100.64.30.3'))
  traffic.assert_sessions(retained=[branch]);traffic.stream(59412,'sdwan-out-vpn-targets:vpn1')
  ct=a.call('ip/firewall/connection/print',{'.proplist':'src-address,src-port,dst-address,connection-mark,seen-reply','.query':['protocol=udp','src-port=51911']},'POST');assert any(x.get('src-address')=='100.64.30.3' and x.get('seen-reply')=='true' for x in ct),ct;assert not any(x.get('src-address')=='100.64.30.2' for x in ct),ct
  active=json.loads(a.read_file('sdwan-active.json'));assert 'address' not in active['wans'][0] and 'gateway' not in active['wans'][0]
  record(args.kind+' reconnect changes source IPv4, retires stale VPN transport and restores preferred parent without a lease snapshot; the original branch TCP keeps receiving data')
  report['pass']=True
 finally:
  if traffic:traffic.close()
  try:
   if applied:apply(before)
  finally:
   for r,menu,id in reversed(created):
    try:r.call(menu+'/'+id,method='DELETE')
    except RuntimeError:pass
   (v.run/('vpn-dynamic-'+args.kind+'-validation.json')).write_text(json.dumps(report,indent=2)+'\n');n.close();v.close();lock.close()

if __name__=='__main__':main()
