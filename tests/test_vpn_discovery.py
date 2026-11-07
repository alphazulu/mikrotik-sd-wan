import copy,unittest
from test_discovery import fixture,build,choices
from sdwan.discovery import generate,candidates
from sdwan.vpn_egress import configure,validate_pushed_defaults
from sdwan.wan import adopted_dynamic_route

class VPNDiscoveryTests(unittest.TestCase):
 def fixture(self,active=False,manual=False):
  inv=fixture();base=build(inv);link=dict(interface='vpn-out',vpn_type='sstp',vpn_endpoint='exit.example.test',running=True)
  inv['interface'].append(dict(name='vpn-out',type='sstp-out',running='true'));inv['ip/address'].append(dict(interface='vpn-out',address='10.204.3.2/32',dynamic='true'));inv['vpn_interfaces']=[link]
  inv['ip/route'].append({'.id':'*3','dst-address':'0.0.0.0/0','routing-table':'main','gateway':'vpn-out','dynamic':'false' if manual else 'true','vpn':'true'})
  if active:inv['active_config']=configure(base,link,name='vpn1',address_list='targets',underlays=['wan1','wan2'],backups=['wan1'],routes=inv['ip/route'])
  inv['candidates']=candidates(inv);return inv,link
 def test_existing_vpn_and_its_policy_survive_physical_wizard_regeneration(self):
  inv,_=self.fixture(active=True);result=build(inv)
  self.assertEqual([w['name'] for w in result['wans']],['wan1','wan2','vpn1']);self.assertEqual(result['policies'][0]['wans'],['wan1','wan2']);self.assertEqual(next(p for p in result['policies'] if p.get('destination_list'))['wans'],['vpn1','wan1']);self.assertNotIn('10.204.3.2/32',result['local_networks']);self.assertNotIn('vpn_egress',result)
 def test_reset_policies_explicitly_drops_optional_vpn_without_saving_lease_network(self):
  inv,_=self.fixture(active=True);result=build(inv,keep_policies=False);self.assertEqual(len(result['wans']),2);self.assertNotIn('vpn_egress',result);self.assertNotIn('10.204.3.2/32',result['local_networks'])
 def test_unselected_vpn_default_allows_draft_then_explicit_vpn_adoption(self):
  for manual in (False,True):
   inv,link=self.fixture(manual=manual);draft=build(inv);self.assertTrue(inv['unselected_vpn_defaults']);self.assertEqual(len(draft['wans']),2)
   final=configure(draft,link,name='vpn1',address_list='targets',underlays=['wan1'],backups=['wan2'],routes=inv['ip/route'])
   if manual:self.assertIn('*3',{r['.id'] for r in final['takeover_routes']})
   else:self.assertTrue(adopted_dynamic_route(inv['ip/route'][-1],final['wans']))
 def test_static_vpn_default_is_kept_as_an_exact_selector_on_regeneration(self):
  inv,_=self.fixture(active=True,manual=True);result=build(inv);self.assertIn('*3',{r['.id'] for r in result['takeover_routes']})
 def test_pushed_def1_must_be_dynamic_vpn_route_of_declared_openvpn(self):
  cfg={'wans':[dict(name='vpn1',kind='vpn',vpn_type='openvpn',interface='vpn-out')]};route={'.id':'*9','dst-address':'0.0.0.0/1','routing-table':'main','dynamic':'true','vpn':'true','gateway':'10.204.4.1','immediate-gw':'10.204.4.1%vpn-out'};validate_pushed_defaults([route],cfg)
  for patch in ({'dynamic':'false'},{'vpn':'false'},{'gateway':'foreign','immediate-gw':'foreign'}):
   with self.assertRaises(ValueError):validate_pushed_defaults([dict(route,**patch)],cfg)
  with self.assertRaises(ValueError):validate_pushed_defaults([route],{'wans':[]})
  self.assertFalse(adopted_dynamic_route(dict(route,vpn='false'),cfg['wans']))

if __name__=='__main__':unittest.main()
