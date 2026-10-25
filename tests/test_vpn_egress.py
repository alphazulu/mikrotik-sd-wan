import base64,copy
from pathlib import Path
import unittest
from sdwan.config import load,validate as validate_config
from sdwan.vpn_egress import validate,binding,enabled
ROOT=Path(__file__).resolve().parents[1]
KEY=base64.b64encode(bytes([8])*32).decode()
def config():
 c=load(ROOT/'config/sdwan.json');c['vpn_egress']={'enabled':True};w=copy.deepcopy(c['wans'][0]);w.update(name='vpn1',interface='vpn-out',kind='vpn',vpn_type='wireguard',vpn_endpoint='198.51.100.20',vpn_listen_port=51911,vpn_peer_public_key=KEY,underlays=['wan1','wan2']);w.pop('address');w.pop('gateway');w['probe_table']='sdwan-probe-vpn1';c['wans'].append(w)
 for i,p in enumerate(p for p in c['policies'] if p['source']):p['priority']=20+i*10
 c['policies'].append(dict(c['policies'][1],name='vpn-targets',source='0.0.0.0/0',table='sdwan-vpn-targets',destination_list='VPN targets',priority=10,wans=['vpn1','wan1']));return c
class VPNTests(unittest.TestCase):
 def test_opt_in_and_existing_default_remain_physical(self):
  c=config();validate_config(c);validate(c);c['vpn_egress']['enabled']=False
  with self.assertRaisesRegex(ValueError,'explicit'):validate(c)
  self.assertFalse(enabled({}))
 def test_parent_cycles_and_vpn_default_rejected(self):
  for change in ('cycle','default'):
   c=config()
   if change=='cycle':c['wans'][-1]['underlays']=['vpn1']
   else:c['policies'][0]['wans']=['vpn1']
   with self.assertRaises(ValueError):validate(c)
 def test_credentials_and_untyped_flags_cannot_enter_feature_contract(self):
  for patch in [{'password':'secret'},{'masquerade':1},{'enabled':'yes'}]:
   c=config();c['vpn_egress'].update(patch)
   with self.assertRaises(ValueError):validate(c)
 def test_ppp_variants_have_no_wireguard_identity_or_lease_snapshot(self):
  for kind in ('l2tp','sstp','openvpn'):
   c=config();w=c['wans'][-1];w['vpn_type']=kind;del w['vpn_peer_public_key'];del w['vpn_listen_port'];validate(c)
 def test_sstp_proxy_fails_before_transport_can_escape_the_declared_underlay(self):
  class Router:
   def call(self,path,data,method):return [{'.id':'*1','connect-to':'198.51.100.20','http-proxy':'192.0.2.44'}]
  c=config();w=c['wans'][-1];w['vpn_type']='sstp'
  with self.assertRaisesRegex(ValueError,'proxy'):binding(Router(),w)
 def test_binding_only_requests_public_properties_and_refuses_branch_peer(self):
  class Router:
   def call(self,path,data,method):
    assert 'private-key' not in data['.proplist'] and 'password' not in data['.proplist']
    if path=='interface/wireguard/print':return [{'.id':'*1','listen-port':'51911'}]
    return [{'.id':'*2','public-key':KEY,'endpoint-address':'198.51.100.20','endpoint-port':'51820','allowed-address':'10.201.0.0/16'}]
  with self.assertRaisesRegex(ValueError,'0.0.0.0/0'):binding(Router(),config()['wans'][-1])
 def test_l2tp_fastpath_rejected_without_changing_client_settings(self):
  class Router:
   def call(self,path,data,method):
    assert path=='interface/l2tp-client/print' and method=='POST' and 'allow-fast-path' in data['.proplist']
    return [{'.id':'*1','connect-to':'198.51.100.20','allow-fast-path':'true'}]
  c=config();w=c['wans'][-1];w['vpn_type']='l2tp'
  with self.assertRaisesRegex(ValueError,'allow-fast-path'):binding(Router(),w)
if __name__=='__main__':unittest.main()
