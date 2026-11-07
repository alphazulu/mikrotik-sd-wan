import copy,json,unittest
from pathlib import Path
from sdwan.config import load,validate,objects
from sdwan.vpn_egress import add_wan,canonical
from sdwan.policies import match_flow,conflicts
ROOT=Path(__file__).resolve().parents[1]

class UnifiedWANTests(unittest.TestCase):
 def config(self):return add_wan(load(ROOT/'config/sdwan.json'),dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test'),name='vpn1',underlays=['wan1','wan2'],masquerade=True)
 def policy(self,c,**selector):
  for i,p in enumerate(p for p in c['policies'] if p['source']):p['priority']=20+i*10
  c['policies'].append(dict(name='chosen',source='0.0.0.0/0',table='sdwan-chosen',profile='default',mode='prefer',wans=['vpn1','wan2'],allow_degraded=False,priority=10,**selector));return validate(c)
 def test_adding_vpn_is_only_a_wan_change_with_no_implicit_rule_or_switch(self):
  c=load(ROOT/'config/sdwan.json');before=copy.deepcopy(c);result=add_wan(c,dict(interface='sstp-out',vpn_type='sstp',vpn_endpoint='exit.example.test',password='not-copied'),name='vpn1',underlays=['wan1']);self.assertEqual(c,before);self.assertEqual(result['policies'],before['policies']);self.assertNotIn('vpn_egress',result);self.assertNotIn('password',json.dumps(result));self.assertEqual(result['wans'][-1]['kind'],'vpn')
 def test_ip_source_destination_and_both_lists_share_policy_engine(self):
  for selector,source,dest,lists in [({'source_list':'Users'},'192.168.50.101','203.0.113.7',{'Users':['192.168.50.101']}),({'destination':'203.0.113.7'},'192.168.50.101','203.0.113.7',{}),({'source_list':'Users','destination_list':'Targets'},'192.168.50.101','203.0.113.7',{'Users':['192.168.50.101'],'Targets':['203.0.113.7']})]:
   c=self.policy(self.config(),**selector);self.assertEqual(match_flow(c,source,dest,address_lists=lists)['policy'],'chosen')
   if 'source_list' in selector:self.assertNotEqual(match_flow(c,'192.168.50.102',dest,address_lists=lists)['policy'],'chosen')
   if 'destination_list' in selector:self.assertNotEqual(match_flow(c,source,'203.0.113.8',address_lists=lists)['policy'],'chosen')
 def test_bare_ip_source_and_default_can_prefer_any_wan(self):
  c=self.config();c['policies']=[c['policies'][0],dict(name='user',source='192.168.50.101',table='sdwan-user',profile='default',mode='prefer',wans=['vpn1','wan1'],allow_degraded=False)];c['policies'][0]['wans']=['vpn1','wan2'];validate(c);self.assertEqual(match_flow(c,'192.168.50.101','203.0.113.9')['policy'],'user')
 def test_source_list_has_same_name_type_and_unknown_membership_guards(self):
  for value in (None,False,'!inverted',' leading','x\n','я'*33):
   with self.subTest(value=value),self.assertRaises(ValueError):self.policy(self.config(),source_list=value)
  c=self.policy(self.config(),source_list='Users')
  with self.assertRaisesRegex(ValueError,'свежий состав'):match_flow(c,'192.168.50.101','203.0.113.9')
  self.assertTrue(all(not x['shadowed'] for x in conflicts(c) if x['first']=='chosen'))
 def test_legacy_flags_migrate_without_mutating_input_and_explicit_wan_flag_wins(self):
  c=self.config();c['vpn_egress']={'enabled':True,'masquerade':True,'allow_selected_forward':True};c['wans'][-1]['masquerade']=False;c['wans'][-1].pop('allow_selected_forward');before=copy.deepcopy(c);new=canonical(c);self.assertEqual(c,before);self.assertNotIn('vpn_egress',new);self.assertFalse(new['wans'][-1]['masquerade']);self.assertTrue(new['wans'][-1]['allow_selected_forward'])
 def test_selectors_live_only_at_jump_and_optional_nat_is_per_wan_for_all_kinds(self):
  c=self.policy(self.config(),source_list='Users',destination_list='Targets');c['wans'][0]['masquerade']=True;o=objects(validate(c));jump=o['ip/firewall/mangle','sdwan:v1:policy-jump:chosen'];self.assertEqual((jump['src-address-list'],jump['dst-address-list']),('Users','Targets'))
  for wn in ('vpn1','wan2'):
   rule=o['ip/firewall/mangle','sdwan:v1:classify:chosen:'+wn];self.assertEqual(rule['chain'],jump['jump-target']);self.assertNotIn('src-address-list',rule)
  self.assertIn(('ip/firewall/nat','sdwan:v1:egress:chosen:vpn1'),o);self.assertIn(('ip/firewall/nat','sdwan:v1:egress:default:wan1'),o);self.assertFalse(any(menu=='ip/firewall/address-list' and row.get('list') in ('Users','Targets') for (menu,_),row in o.items()))

if __name__=='__main__':unittest.main()
