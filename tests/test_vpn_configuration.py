import copy,unittest
from pathlib import Path
from sdwan.config import load
from sdwan.vpn_egress import configure,inventory,disable
from sdwan.address_lists import snapshot,MAX_ROWS
from sdwan.policies import ordered
ROOT=Path(__file__).resolve().parents[1]
class VPNConfigurationTests(unittest.TestCase):
 def test_atomic_gui_generation_keeps_default_and_client_order(self):
  c=load(ROOT/'config/sdwan.json');before=copy.deepcopy(c);link=dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test',password='must-not-copy',address='192.0.2.99')
  changed=configure(c,link,name='vpn1',address_list='managed elsewhere',underlays=['wan2','wan1'],backups=['wan1','wan3'])
  self.assertEqual(c,before);self.assertEqual(changed['policies'][0],c['policies'][0]);self.assertEqual([p['name'] for p in ordered(changed)][1:],[p['name'] for p in ordered(c)])
  self.assertEqual(changed['wans'][-1]['underlays'],['wan2','wan1']);self.assertNotIn('password',changed['wans'][-1]);self.assertNotIn('address',changed['wans'][-1]);self.assertEqual(changed['vpn_egress'],dict(enabled=True,masquerade=False,allow_selected_forward=False))
 def test_rejected_change_does_not_mutate_original(self):
  c=load(ROOT/'config/sdwan.json');before=copy.deepcopy(c)
  with self.assertRaises(ValueError):configure(c,dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test'),name='vpn1',address_list='targets',underlays=['vpn1'],backups=['wan1'])
  self.assertEqual(c,before)
 def test_existing_vpn_probes_survive_wizard_update(self):
  c=load(ROOT/'config/sdwan.json');link=dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test');c=configure(c,link,name='vpn1',address_list='a',underlays=['wan1'],backups=['wan2']);c['wans'][-1]['probes'][0]['port']=8443
  result=configure(c,link,name='vpn1',address_list='b',underlays=['wan2'],backups=['wan1']);self.assertEqual(len(result['wans']),4);self.assertEqual(result['wans'][-1]['probes'][0]['port'],8443);self.assertEqual(sum(p['name']=='vpn-vpn1' for p in result['policies']),1)
 def test_existing_policy_manual_selectors_sla_and_priority_are_preserved(self):
  c=load(ROOT/'config/sdwan.json');link=dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test');c=configure(c,link,name='vpn1',address_list='a',underlays=['wan1'],backups=['wan2']);p=next(p for p in c['policies'] if p['name']=='vpn-vpn1');p.update(priority=15,source='192.168.60.0/24',destination='203.0.113.0/24',protocol='tcp',dst_ports='443,8443',profile='voice',table='sdwan-custom-vpn',allow_degraded=True);before=copy.deepcopy(p)
  changed=configure(c,link,name='vpn1',address_list='b',underlays=['wan2'],backups=['wan3']);actual=next(p for p in changed['policies'] if p['name']=='vpn-vpn1');expected=dict(before,destination_list='b',wans=['vpn1','wan3']);self.assertEqual(actual,expected);self.assertEqual(p,before)
 def test_disable_keeps_physical_fallbacks_and_never_changes_input(self):
  c=load(ROOT/'config/sdwan.json');link=dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test');c=configure(c,link,name='vpn1',address_list='a',underlays=['wan1'],backups=['wan2']);before=copy.deepcopy(c);result=disable(c)
  self.assertEqual(c,before);self.assertFalse(result['vpn_egress']['enabled']);self.assertEqual(len(result['wans']),3);self.assertEqual(next(p for p in result['policies'] if p['name']=='vpn-vpn1')['wans'],['wan2']);self.assertEqual(next(p for p in result['policies'] if not p['source'])['wans'],next(p for p in c['policies'] if not p['source'])['wans'])
 def test_disable_removes_vpn_only_strict_policy(self):
  c=load(ROOT/'config/sdwan.json');c=configure(c,dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test'),name='vpn1',address_list='a',underlays=['wan1'],backups=[]);c['policies'][1]['mode']='strict';result=disable(c);self.assertFalse(any(p['name']=='vpn-vpn1' for p in result['policies']))
 def test_list_snapshot_is_bounded_and_never_turns_truncation_into_empty_membership(self):
  class Router:
   def call(self,path,data,method):
    if 'count-only' in data:return {'ret':str(MAX_ROWS+1)}
    raise AssertionError('Large address list must not be downloaded')
  self.assertIsNone(snapshot(Router(),['external']))
 def test_list_snapshot_resolved_dns_prefix_disabled_and_empty_entries(self):
  class Router:
   def call(self,path,data,method):
    if 'count-only' in data:return {'ret':'5'}
    return [dict(list='external',address='target.example.test'),dict(list='external',address='203.0.113.5'),dict(list='external',address='198.51.100.0/24'),dict(list='external',address='192.0.2.1',disabled='true'),dict(list='external',address='2001:db8::1')]
  self.assertEqual(snapshot(Router(),['external','empty']),{'external':['203.0.113.5/32','198.51.100.0/24'],'empty':[]})
 def test_inventory_never_reads_passwords_or_keys_and_excludes_branch_peers(self):
  class Router:
   def call(self,path,data,method):
    self.assertions(data)
    if path=='interface/wireguard/print':return [dict(name='branch',running='true')]
    if path=='interface/wireguard/peers/print':return [dict(interface='branch',**{'allowed-address':'10.0.0.0/8'})]
    if path=='interface/sstp-client/print':return [dict(name='sstp-out',running='false',**{'connect-to':'exit.example.test'})]
    return []
   def assertions(self,data):assert 'password' not in data['.proplist'] and 'private-key' not in data['.proplist'] and 'ipsec-secret' not in data['.proplist']
  self.assertEqual(inventory(Router()),[dict(interface='sstp-out',vpn_type='sstp',running=False,vpn_endpoint='exit.example.test')])
if __name__=='__main__':unittest.main()
