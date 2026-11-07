#!/usr/bin/env python3
"""CHR ONLY: existing WireGuard hostname, DNS address rotation and resource SLA."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic
from sdwan.router import Router
from sdwan.config import validate

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];h=v.routers['hub'];creds=json.loads((v.run/'credentials.json').read_text());n=Router(v.root,'api://127.0.0.1:55731',credentials_data=creds['nata']);assert n.call('system/identity')['name']=='sdwan-overlay-nata'
 before=json.loads(a.read_file('sdwan-active.json'));report={'checks':[],'pass':False};created=[];applied=False;traffic=None;peer=None;hostname='vpn-egress-fixture.test';tag='vpn-dns-acceptance-only'
 spec=importlib.util.spec_from_file_location('vpn_dns_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'vpn-protected-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(a,validate(c),'sdwan-overlay-sitea')
 def add(r,menu,data):
  done=r.call(menu+'/add',dict(data,comment=tag),'POST');created.append((r,menu,done['ret']));return done['ret']
 def record(check):report['checks'].append({'check':check,'pass':True});print('PASS '+check,flush=True)
 def wait(fn,timeout=180):
  end=time.monotonic()+timeout;last=None
  while time.monotonic()<end:
   last=fn()
   if last:return last
   time.sleep(.3)
  raise AssertionError({'timeout':last,'status':a.status(),'endpoints':endpoints(),'peer':public_peer()})
 def public_peer():return a.call('interface/wireguard/peers/print',{'.proplist':'.id,endpoint-address,current-endpoint-address,rx,tx,last-handshake','.query':['interface=vpn-exit-wg']},'POST')[0]
 def endpoints():return a.call('ip/firewall/address-list/print',{'.proplist':'address,dynamic','.query':['list=sdwan-vpn-endpoint-vpn1']},'POST')
 def healthy(ip):
  s=a.status()
  if s.get('error'):raise AssertionError(s['error'])
  routes=a.call('ip/route/print',{'.proplist':'dst-address,active','.query':['comment=sdwan:v1:vpn:transport:vpn1']},'POST')
  return s if s.get('selected',{}).get('vpn-targets')=='vpn1' and public_peer().get('current-endpoint-address')==ip and any(x['address']==ip for x in endpoints()) and any(x.get('dst-address')==ip+'/32' and x.get('active')=='true' for x in routes) else None
 try:
  assert not a.call('ip/dns/static/print',{'.proplist':'.id','.query':['name='+hostname]},'POST'),'fixture DNS name collision'
  peer=public_peer();assert peer['endpoint-address']=='198.18.100.1'
  dns=add(a,'ip/dns/static',{'name':hostname,'type':'A','address':'198.18.100.1','ttl':'5s'})
  a.call('interface/wireguard/peers/set',{'.id':peer['.id'],'endpoint-address':hostname},'POST')
  cfg=copy.deepcopy(before);cfg['revision']='vpn-dns-rotation';cfg['vpn_egress']={'enabled':True,'masquerade':True,'allow_selected_forward':True};w=copy.deepcopy(cfg['wans'][0]);w.pop('address');w.pop('gateway');w.update(v.state['links']['wireguard']);w.update(name='vpn1',kind='vpn',vpn_endpoint=hostname,probe_table='sdwan-probe-vpn1');cfg['wans'].append(w);cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',destination_list='vpn-dns-targets',priority=10,wans=['vpn1','wan1','wan2'],table='sdwan-vpn-targets',profile='default',mode='prefer',allow_degraded=False));add(a,'ip/firewall/address-list',{'list':'vpn-dns-targets','address':'198.19.100.1'})
  applied=True;apply(cfg);wait(lambda:healthy('198.18.100.1'));traffic=VPNTraffic(v);traffic.prepare();traffic.stream(59410,'sdwan-out-vpn-targets:vpn1');ordinary=traffic.stream(59411,'sdwan-out-default:wan1',target='198.19.100.2');branch=traffic.stream(59419,'no-mark',target='10.201.1.2')
  record('configured hostname resolves through the owned DNS Address List and bootstrap route; resource SLA admits real VPN TCP')
  add(h,'ip/address',{'address':'198.18.100.10/32','interface':'ether2'});add(n,'ip/route',{'dst-address':'198.18.100.10/32','gateway':'198.18.100.1','routing-table':'main'})
  add(h,'ip/firewall/nat',{'chain':'srcnat','protocol':'udp','src-port':'51901','out-interface':'ether2','action':'src-nat','to-addresses':'198.18.100.10','place-before':'0'})
  add(h,'ip/firewall/filter',{'chain':'input','dst-address':'198.18.100.1','protocol':'udp','dst-port':'51901','action':'drop','place-before':'0'})
  a.call('ip/dns/static/set',{'.id':dns,'address':'198.18.100.10'},'POST');a.call('ip/dns/cache/flush',{},'POST')
  wait(lambda:healthy('198.18.100.10'));assert public_peer()['endpoint-address']==hostname;assert not any(x['address']=='198.18.100.1' for x in endpoints());traffic.stream(59412,'sdwan-out-vpn-targets:vpn1');traffic.assert_sessions(retained=[ordinary,branch])
  record('DNS rotation and retirement of the old server address restore preferred VPN resource SLA and real TCP without rewriting the hostname or resetting unrelated flows')
  report['pass']=True
 finally:
  if traffic:traffic.close()
  if peer:a.call('interface/wireguard/peers/set',{'.id':peer['.id'],'endpoint-address':peer['endpoint-address']},'POST')
  for r,menu,id in reversed(created):
   try:r.call(menu+'/'+id,method='DELETE')
   except RuntimeError:pass
  try:
   if applied:apply(before)
  finally:(v.run/'vpn-dns-validation.json').write_text(json.dumps(report,indent=2)+'\n');n.close();v.close();lock.close()

if __name__=='__main__':main()
