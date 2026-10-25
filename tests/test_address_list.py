import copy
import unittest
from pathlib import Path
from sdwan.config import load,validate,objects
from sdwan.policies import match_flow,conflicts,signature
ROOT=Path(__file__).resolve().parents[1]
def config():
 cfg=load(ROOT/'config/sdwan.json')
 for i,p in enumerate(p for p in cfg['policies'] if p['source']):p['priority']=20+i*10
 cfg['policies'].append(dict(name='targets',source='0.0.0.0/0',table='sdwan-targets',profile='default',mode='prefer',wans=['wan2','wan1'],allow_degraded=False,priority=10,destination_list='VPN destinations'))
 return cfg
class AddressListTests(unittest.TestCase):
 def test_uses_existing_list_without_materializing_or_owning_its_entries(self):
  cfg=validate(config());native=objects(cfg)
  jump=native['ip/firewall/mangle','sdwan:v1:policy-jump:targets'];self.assertEqual(jump['dst-address-list'],'VPN destinations')
  guard=native['ip/firewall/mangle','sdwan:v1:guard:targets'];self.assertEqual(jump['jump-target'],guard['chain']);self.assertEqual(guard['connection-mark'],'no-mark')
  self.assertFalse(any(values.get('list')=='VPN destinations' for (menu,_),values in native.items() if menu=='ip/firewall/address-list'))
 def test_current_cidr_membership_and_empty_list_match_exactly(self):
  cfg=config();flow=dict(source='192.168.50.101',destination='203.0.113.20')
  self.assertEqual(match_flow(cfg,**flow,address_lists={'VPN destinations':['203.0.113.0/24']})['policy'],'targets')
  self.assertEqual(match_flow(cfg,**flow,address_lists={'VPN destinations':[]})['policy'],'client101')
 def test_unknown_live_membership_is_never_assumed_to_match(self):
  with self.assertRaisesRegex(ValueError,'свежий состав'):match_flow(config(),'192.168.50.101','203.0.113.20')
 def test_list_reference_participates_in_signature_but_members_are_not_saved(self):
  cfg=config();other=copy.deepcopy(cfg);other['policies'][-1]['destination_list']='another';self.assertNotEqual(signature(cfg),signature(other))
 def test_opaque_list_does_not_falsely_shadow_all_clients(self):
  cfg=validate(config());self.assertTrue(conflicts(cfg));self.assertTrue(all(not row['shadowed'] for row in conflicts(cfg) if row['first']=='targets'))
 def test_invalid_negated_and_ambiguous_selectors_rejected(self):
  for value in ['!VPN destinations',' bad','x\n','x'*65,'я'*33,None,False,123]:
   cfg=config();cfg['policies'][-1]['destination_list']=value
   with self.subTest(value=value),self.assertRaises(ValueError):validate(cfg)
  cfg=config();cfg['groups']={'static':['203.0.113.0/24']};cfg['policies'][-1]['destination_group']='static'
  with self.assertRaisesRegex(ValueError,'mutually exclusive'):validate(cfg)
if __name__=='__main__':unittest.main()
