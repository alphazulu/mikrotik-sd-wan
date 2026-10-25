#!/usr/bin/env python3
"""Additional VPN-exit fixtures on the existing isolated CGNAT CHRs only."""
import argparse
import fcntl
import json
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.router import Router
from overlay_lab import Lab,NODES
TAG='vpn-egress-lab-fixture'

class VPNLab:
 def __init__(self,project_root):
  self.lab=Lab(project_root);self.root=self.lab.root;self.run=self.lab.run;self.path=self.run/'vpn-fixture.json';self.created=[];self.state=json.loads(self.path.read_text()) if self.path.exists() else {'created':[],'links':{}}
  credentials=json.loads((self.run/'credentials.json').read_text());self.routers={n:Router(self.root,'api://127.0.0.1:'+str(55728+NODES[n]),credentials_data=credentials[n]) for n in ('hub','sitea')}
  for n,r in self.routers.items():
   assert r.call('system/identity')['name']=='sdwan-overlay-'+n
   assert r.call('system/resource')['version'].split()[0]=='7.24.5'
 def close(self):
  for r in self.routers.values():r.close()
 def save(self):self.path.write_text(json.dumps(self.state,indent=2)+'\n')
 def add(self,node,menu,data):
  done=self.routers[node].call(menu+'/add',dict(data,comment=TAG),'POST');self.state['created'].append({'node':node,'menu':menu,'id':done['ret']});self.save();return done['ret']
 def wg(self):
  if 'wireguard' in self.state['links']:print('WireGuard exit fixture already exists; reusing it');return
  a=self.routers['sitea'];h=self.routers['hub']
  for r,name in [(a,'vpn-exit-wg'),(h,'vpn-server-wg')]:
   assert not r.call('interface/wireguard/print',{'.proplist':'name','.query':['name='+name]},'POST'),'Unexpected fixture name collision'
  self.add('hub','interface/wireguard',{'name':'vpn-server-wg','listen-port':'51901','mtu':'1380'})
  self.add('sitea','interface/wireguard',{'name':'vpn-exit-wg','listen-port':'51911','mtu':'1380'})
  def key(r,name):return r.call('interface/wireguard/print',{'.proplist':'public-key','.query':['name='+name]},'POST')[0]['public-key']
  server=key(h,'vpn-server-wg');client=key(a,'vpn-exit-wg')
  self.add('hub','ip/address',{'address':'10.204.1.1/30','interface':'vpn-server-wg'})
  self.add('sitea','ip/address',{'address':'10.204.1.2/30','interface':'vpn-exit-wg'})
  self.add('hub','interface/wireguard/peers',{'interface':'vpn-server-wg','public-key':client,'allowed-address':'10.204.1.2/32','responder':'true'})
  self.add('hub','ip/firewall/filter',{'chain':'input','protocol':'udp','in-interface':'ether2','dst-port':'51901','action':'accept','place-before':'0'})
  self.add('hub','ip/firewall/filter',{'chain':'forward','in-interface':'vpn-server-wg','out-interface':'ether2','action':'accept','place-before':'0'})
  self.add('sitea','interface/wireguard/peers',{'interface':'vpn-exit-wg','public-key':server,'allowed-address':'0.0.0.0/0','endpoint-address':'198.18.100.1','endpoint-port':'51901','persistent-keepalive':'10s'})
  self.state['links']['wireguard']={'interface':'vpn-exit-wg','vpn_type':'wireguard','vpn_endpoint':'198.18.100.1','vpn_listen_port':51911,'vpn_peer_public_key':server,'underlays':['wan1','wan2']};self.save();print('WireGuard external exit fixture prepared; public metadata only')
 def ppp(self,kind):
  if kind in self.state['links']:print(kind+' fixture already exists; reusing it');return
  assert kind in ('l2tp','sstp')
  a=self.routers['sitea'];h=self.routers['hub'];server='interface/'+kind+'-server/server';client='interface/'+kind+'-client'
  rows=h.call(server+'/print',{'.proplist':'.id,enabled,default-profile,authentication,certificate,port,use-ipsec'},'POST')
  # Do not read a configured server's secrets. The fixture requires a disabled
  # virgin emulated server; only its enabled/profile options are adopted.
  row=rows[0];assert row['enabled']=='false','Refusing to replace an enabled lab VPN server'
  saved={k:row[k] for k in ('enabled','default-profile','authentication','certificate','port','use-ipsec') if k in row}
  self.state.setdefault('servers',{})[kind]={'menu':server,'before':saved};self.save()
  number=2 if kind=='l2tp' else 3;user='vpn-lab-'+kind;iface='vpn-exit-'+kind
  auth=self.run/'vpn-fixture-auth.json';credentials=json.loads(auth.read_text()) if auth.exists() else {}
  credentials.setdefault(kind,{'password':secrets.token_urlsafe(32),'ipsec':secrets.token_urlsafe(32)});auth.write_text(json.dumps(credentials,indent=2)+'\n');auth.chmod(0o600)
  self.add('hub','ppp/profile',{'name':'vpn-lab-'+kind,'local-address':f'10.204.{number}.1','remote-address':f'10.204.{number}.2','use-encryption':'required' if kind=='sstp' else 'yes','change-tcp-mss':'yes'})
  self.add('hub','ppp/secret',{'name':user,'password':credentials[kind]['password'],'service':kind,'profile':'vpn-lab-'+kind})
  options={'enabled':'yes','default-profile':'vpn-lab-'+kind,'authentication':'mschap2'}
  if kind=='l2tp':
   options.update({'use-ipsec':'required','ipsec-secret':credentials[kind]['ipsec']})
   self.add('hub','ip/firewall/filter',{'chain':'input','protocol':'udp','in-interface':'ether2','dst-port':'1701,500,4500','action':'accept','place-before':'0'})
   self.add('hub','ip/firewall/filter',{'chain':'input','protocol':'ipsec-esp','in-interface':'ether2','action':'accept','place-before':'0'})
  else:
   options.update({'port':'5443','certificate':'none'})
   self.add('hub','ip/firewall/filter',{'chain':'input','protocol':'tcp','in-interface':'ether2','dst-port':'5443','action':'accept','place-before':'0'})
  self.add('hub','ip/firewall/filter',{'chain':'forward','src-address':f'10.204.{number}.2','out-interface':'ether2','action':'accept','place-before':'0'})
  h.call(server+'/set',options,'POST')
  data={'name':iface,'connect-to':'198.18.100.1','user':user,'password':credentials[kind]['password'],'disabled':'false','add-default-route':'false'}
  if kind=='l2tp':data.update({'use-ipsec':'yes','ipsec-secret':credentials[kind]['ipsec'],'allow-fast-path':'false'})
  else:data.update({'port':'5443','verify-server-certificate':'false','authentication':'mschap2'})
  self.add('sitea',client,data)
  self.state['links'][kind]={'interface':iface,'vpn_type':kind,'vpn_endpoint':'198.18.100.1','underlays':['wan1','wan2']};self.save();print(kind+' external exit fixture prepared; authentication remains private runtime data')
 def ovpn(self):
  kind='openvpn'
  if kind in self.state['links']:print('OpenVPN fixture already exists; reusing it');return
  a=self.routers['sitea'];h=self.routers['hub']
  for name in ('vpn-lab-ca','vpn-lab-ovpn-server'):
   assert not h.call('certificate/print',{'.proplist':'name','.query':['name='+name]},'POST'),'Unexpected certificate name collision'
  def add_certificate(data):
   done=h.call('certificate/add',data,'POST');item={'node':'hub','menu':'certificate','id':done['ret']};self.state['created'].append(item);self.save();return item
  ca=add_certificate({'name':'vpn-lab-ca','common-name':'VPN CHR Lab CA','key-size':'2048','key-usage':'key-cert-sign,crl-sign','days-valid':'30'})
  h.call('certificate/sign',{'number':ca['id'],'name':'vpn-lab-ca'},'POST')
  ca['id']=h.call('certificate/print',{'.proplist':'.id','.query':['name=vpn-lab-ca']},'POST')[0]['.id'];self.save()
  cert=add_certificate({'name':'vpn-lab-ovpn-server','common-name':'198.18.100.1','subject-alt-name':'IP:198.18.100.1','key-size':'2048','key-usage':'digital-signature,key-encipherment,tls-server','days-valid':'30'})
  h.call('certificate/sign',{'number':cert['id'],'ca':'vpn-lab-ca','name':'vpn-lab-ovpn-server'},'POST')
  cert['id']=h.call('certificate/print',{'.proplist':'.id','.query':['name=vpn-lab-ovpn-server']},'POST')[0]['.id'];self.save()
  auth=self.run/'vpn-fixture-auth.json';credentials=json.loads(auth.read_text()) if auth.exists() else {};credentials[kind]={'password':secrets.token_urlsafe(32)};auth.write_text(json.dumps(credentials,indent=2)+'\n');auth.chmod(0o600)
  self.add('hub','ppp/profile',{'name':'vpn-lab-openvpn','local-address':'10.204.4.1','remote-address':'10.204.4.2','change-tcp-mss':'yes'})
  self.add('hub','ppp/secret',{'name':'vpn-lab-openvpn','password':credentials[kind]['password'],'service':'ovpn','profile':'vpn-lab-openvpn'})
  self.add('hub','ip/firewall/filter',{'chain':'input','protocol':'tcp','in-interface':'ether2','dst-port':'51194','action':'accept','place-before':'0'})
  self.add('hub','ip/firewall/filter',{'chain':'forward','src-address':'10.204.4.2','out-interface':'ether2','action':'accept','place-before':'0'})
  done=h.call('interface/ovpn-server/server/add',{'name':'vpn-lab-openvpn','port':'51194','mode':'ip','protocol':'tcp','default-profile':'vpn-lab-openvpn','certificate':'vpn-lab-ovpn-server','require-client-certificate':'false','auth':'sha256','cipher':'aes256-cbc','disabled':'false'},'POST');self.state['created'].append({'node':'hub','menu':'interface/ovpn-server/server','id':done['ret']});self.save()
  self.add('sitea','interface/ovpn-client',{'name':'vpn-exit-openvpn','connect-to':'198.18.100.1','port':'51194','protocol':'tcp','mode':'ip','user':'vpn-lab-openvpn','password':credentials[kind]['password'],'auth':'sha256','cipher':'aes256-cbc','verify-server-certificate':'false','add-default-route':'false','route-nopull':'false','disabled':'false'})
  self.state['links'][kind]={'interface':'vpn-exit-openvpn','vpn_type':kind,'vpn_endpoint':'198.18.100.1','underlays':['wan1','wan2']};self.save();print('OpenVPN external exit prepared; certificate private keys generated and retained on CHR')
 def status(self):
  for kind,data in self.state['links'].items():
   r=self.routers['sitea'];rows=r.call('interface/print',{'.proplist':'name,running,disabled','.query':['name='+data['interface']]},'POST');print(kind,json.dumps(rows))
 def cleanup(self):
  for kind,item in self.state.get('servers',{}).items():
   self.routers['hub'].call(item['menu']+'/set',item['before'],'POST')
  for item in reversed(self.state['created']):
   try:self.routers[item['node']].call(item['menu']+'/'+item['id'],method='DELETE')
   except RuntimeError:pass
  self.state={'created':[],'links':{}};self.save()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['wireguard','l2tp','sstp','openvpn','status','cleanup']);p.add_argument('--project-root',type=Path,default=ROOT);args=p.parse_args()
 fixture=VPNLab(args.project_root);lock=(fixture.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 try:
  if args.command in ('l2tp','sstp'):fixture.ppp(args.command)
  else:getattr(fixture,'wg' if args.command=='wireguard' else 'ovpn' if args.command=='openvpn' else args.command)()
 finally:fixture.close();lock.close()

if __name__=='__main__':main()
