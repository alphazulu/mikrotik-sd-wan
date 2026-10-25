#!/usr/bin/env python3
"""CHR ONLY: native overlay ownership, nested lists and VRF preflight boundaries.

Fixtures use a new DISABLED WG identity, a disabled foreign OSPF instance and an
unaddressed bridge. No existing protocol/template/VRF assignment is changed.
"""
import argparse,copy,fcntl,ipaddress,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',type=Path,required=True);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];name='overlay-ownership-acceptance';output='sdwanOverlayOwnershipJSON';created=[];files=[];checks=[];active=r.read_file('sdwan-active.json');cfg=json.loads(active);template=None
 def add(menu,data):
  done=r.call(menu+'/add',data,'POST');created.append((menu,done['ret']));return done['ret']
 def setrow(menu,id,**fields):r.call(menu+'/set',dict(fields,**{'.id':id}),'POST')
 try:
  assert not r.call('system/script/print',{'.proplist':'.id','.query':['name='+name]},'POST'),'Previous ownership test must not be duplicated'
  assert not r.call('interface/print',{'.proplist':'.id','.query':['name=sdwan-wg-contract-test']},'POST')
  add('interface/wireguard',{'name':'sdwan-wg-contract-test','listen-port':'52991','mtu':'1380','disabled':'true','comment':'sdwan:v1:overlay:interface:contract-test'})
  public=r.call('interface/wireguard/print',{'.proplist':'public-key','.query':['name=sdwan-wg-contract-test']},'POST')[0]['public-key'];cfg['overlay']['tunnels'][0].update(name='contract-test',listen_port=52991,local_public_key=public)
  add('interface/bridge',{'name':'overlay-contract-physical','comment':name});cfg['wans'][0]['interface']='overlay-contract-physical'
  instance=add('routing/ospf/instance',{'name':'overlay-contract-foreign','version':'2','disabled':'true','router-id':'10.255.250.1','comment':name});area=add('routing/ospf/area',{'name':'overlay-contract-foreign','instance':'overlay-contract-foreign','area-id':'0.0.0.0','comment':name})
  for listname,extra in [('overlay-contract-leaf',{}),('overlay-contract-nested',{'include':'overlay-contract-leaf'}),('overlay-contract-excluded',{'include':'all','exclude':'overlay-contract-leaf'}),('overlay-contract-static',{'include':'static'}),('overlay-contract-dynamic',{'include':'dynamic'})]:add('interface/list',dict(name=listname,comment=name,**extra))
  for tunnel in cfg['overlay']['tunnels']:add('interface/list/member',{'list':'overlay-contract-leaf','interface':'sdwan-wg-'+tunnel['name'],'comment':name})
  template=add('routing/ospf/interface-template',{'area':'overlay-contract-foreign','interfaces':'ether4','comment':name})
  for filename,body in [(name+'.rsc',(ROOT/'native/sdwan-overlay.rsc').read_text().split(':global sdwanOverlayInstall do={',1)[0]),(name+'.json',json.dumps(cfg,separators=(',',':')))]:r.upload(filename,body);files.append(filename)
  source='''/system/scheduler/disable [/system/scheduler/find where name="overlay-ownership-acceptance"]
:global sdwanOverlayOwnershipJSON
:onerror failure in={
/import file-name="overlay-ownership-acceptance.rsc"
:global sdwanOverlayValidate
:local raw [/file/get [/file/find where name="overlay-ownership-acceptance.json"] contents]
:local cfg [:deserialize from=json options=json.no-string-conversion value=$raw]
:local accepted true
:local reason ""
:onerror rejected in={ :local ok [$sdwanOverlayValidate cfg=$cfg rawJSON=$raw] } do={ :set accepted false; :set reason $rejected }
:set sdwanOverlayOwnershipJSON [:serialize to=json value={"accepted"=$accepted;"reason"=$reason} options=json.no-string-conversion]
} do={ :set sdwanOverlayOwnershipJSON [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
'''
  add('system/script',{'name':name,'source':source,'policy':'read,write,policy,test,sensitive','comment':name});scheduler=add('system/scheduler',{'name':name,'interval':'1s','disabled':'true','on-event':'/system/script/run '+name,'policy':'read,write,policy,test,sensitive','comment':name})
  def check(label,expected):
   for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+output]},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
   setrow('system/scheduler',scheduler,disabled='false');end=time.monotonic()+15
   while time.monotonic()<end:
    rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name='+output]},'POST')
    if rows and rows[0].get('value','').startswith('{'):break
    time.sleep(.1)
   else:raise AssertionError('No native ownership result')
   result=json.loads(rows[0]['value']);assert 'error' not in result and result['accepted']==expected,dict(case=label,**result);checks.append(dict(case=label,pass_=True,**result));print('PASS '+label,flush=True)
  check('foreign OSPF on unrelated LAN remains allowed',True)
  for iface in ('sdwan-wg-contract-test','all','static','overlay-contract-leaf','overlay-contract-nested','overlay-contract-static'):
   setrow('routing/ospf/interface-template',template,interfaces=iface);check('foreign OSPF matching '+iface+' is rejected',False)
  setrow('routing/ospf/interface-template',template,interfaces='overlay-contract-excluded');check('exclude removes inherited WG membership',True)
  member=add('interface/list/member',{'list':'overlay-contract-excluded','interface':'sdwan-wg-contract-test','comment':name});check('explicit member after exclude restores collision',False);r.call('interface/list/member/'+member,method='DELETE');created.remove(('interface/list/member',member))
  setrow('routing/ospf/interface-template',template,interfaces='overlay-contract-dynamic');check('dynamic list excludes the static WG identity',True)
  setrow('routing/ospf/interface-template',template,interfaces='all',networks=str(ipaddress.IPv4Interface(cfg['overlay']['tunnels'][0]['address']).network.network_address)+'/32');check('OSPF network matcher uses the WG subnet network address',False)
  setrow('routing/ospf/interface-template',template,networks='192.0.2.0/24');check('nonoverlapping OSPF network matcher remains allowed',True)
  setrow('routing/ospf/interface-template',template,interfaces='all',networks='',disabled='true');check('disabled broad foreign OSPF template remains allowed',True)
  setrow('routing/ospf/interface-template',template,disabled='false')
  owned_list=r.call('interface/list/print',{'.proplist':'.id,include,exclude','.query':['name=sdwan-overlay']},'POST')[0]
  try:
   for field in ('include','exclude'):
    setrow('interface/list',owned_list['.id'],**{field:'none'});check('reserved overlay list forbids '+field+' inheritance',False);setrow('interface/list',owned_list['.id'],**{field:owned_list.get(field,'')})
  finally:setrow('interface/list',owned_list['.id'],include=owned_list.get('include',''),exclude=owned_list.get('exclude',''))
  setrow('routing/ospf/interface-template',template,interfaces='ether4',networks='')
  add('interface/bridge',{'name':'overlay-contract-unused','comment':name})
  vrf=add('ip/vrf',{'name':'overlay-contract-vrf','interfaces':'overlay-contract-unused','comment':name});check('foreign VRF on unused interface does not capture WG or physical underlay',True)
  setrow('ip/vrf',vrf,interfaces='sdwan-wg-contract-test');check('WG assigned to a foreign VRF is rejected',False)
  setrow('ip/vrf',vrf,interfaces='overlay-contract-physical');check('physical underlay assigned to a foreign VRF is rejected',False)
  r.call('ip/vrf/'+vrf,method='DELETE');created.remove(('ip/vrf',vrf))
  foreign=add('ip/firewall/address-list',{'list':'sdwan-overlay-sites','address':'192.0.2.0/24','comment':name});check('foreign entries in reserved overlay site list are rejected',False);r.call('ip/firewall/address-list/'+foreign,method='DELETE');created.remove(('ip/firewall/address-list',foreign))
  table='sdwan-ol-hub-wan2';foreign=add('ip/route',{'dst-address':'192.0.2.0/24','blackhole':'true','routing-table':table,'comment':name});check('foreign route in owned probe table is rejected',False);r.call('ip/route/'+foreign,method='DELETE');created.remove(('ip/route',foreign))
  foreign=add('routing/rule',{'dst-address':'192.0.2.0/24','table':table,'action':'lookup-only-in-table','comment':name});check('foreign rule referencing owned probe table is rejected',False);r.call('routing/rule/'+foreign,method='DELETE');created.remove(('routing/rule',foreign))
  foreign=add('ip/address',{'address':'10.255.249.1/32','interface':'sdwan-wg-contract-test','comment':name});check('foreign address on owned disabled WG identity is rejected',False);r.call('ip/address/'+foreign,method='DELETE');created.remove(('ip/address',foreign))
  import base64
  foreign=add('interface/wireguard/peers',{'interface':'sdwan-wg-contract-test','public-key':base64.b64encode(bytes([7])*32).decode(),'allowed-address':'10.255.248.1/32','disabled':'true','comment':name});check('foreign disabled peer on owned WG identity is rejected',False);r.call('interface/wireguard/peers/'+foreign,method='DELETE');created.remove(('interface/wireguard/peers',foreign))
  check('all ownership fixtures removed from routing boundaries restore acceptance',True);assert r.read_file('sdwan-active.json')==active
 finally:
  for menu,id in reversed(created):r.call(menu+'/'+id,method='DELETE')
  for filename in files:
   row=r.file_entry(filename)
   if row:r.call('file/'+row['.id'],method='DELETE')
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+output]},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
  (v.run/'overlay-ownership-validation.json').write_text(json.dumps({'pass':len(checks)==24,'checks':checks},indent=2)+'\n');v.close();lock.close()
if __name__=='__main__':main()
