import json,unittest
from test_vpn_egress import config as vpn_config
from test_overlay import config as overlay_config
from sdwan.diagnostics import view

class NetworkDiagnosticsTests(unittest.TestCase):
 def test_maintenance_and_vpn_are_allowlisted_and_do_not_copy_transport_secrets(self):
  cfg=vpn_config();s={'enabled':True,'revision':cfg['revision'],'uptime_seconds':10,'samples':{'vpn1':{'link_ready':True}},'maintenance':{'vpn1':{'configured':'drain','effective':'drain','admit':False,'elapsed_seconds':4,'timeout_seconds':30,'password':'secret'}},'draining_marks':{'sdwan-out-vpn-targets:vpn1':True,'sdwan-out-default:wan1':True},'vpn_egress':{'vpn1':{'underlay':'wan2','transport_ready':True,'signature':'secret','private-key':'secret'}}}
  r=view(s,cfg,router_uptime=10)['wans'][0];self.assertEqual((r['admin_state'],r['admission'],r['retained_marks'],r['vpn_underlay'],r['transport_ready']),('drain',False,1,'wan2',True));self.assertNotIn('secret',json.dumps(r))
 def test_overlay_distinguishes_sla_admission_from_unknown_ospf_and_ages_evidence(self):
  cfg=overlay_config();s={'enabled':True,'revision':cfg['revision'],'uptime_seconds':10,'overlay':{'hub-wan1':{'healthy':True,'probe_up':True,'sample_age_seconds':2,'reason':'healthy','private_key':'secret'},'unconfigured':{'healthy':True}}}
  r=view(s,cfg,router_uptime=15)['overlay'];self.assertEqual(len(r),1);self.assertEqual(r[0]['sample_age_seconds'],7);self.assertEqual(r[0]['ospf_state'],'unknown');self.assertFalse(r[0]['stale']);self.assertNotIn('secret',json.dumps(r));self.assertTrue(view(s,cfg,router_uptime=30)['overlay'][0]['stale'])
 def test_absent_optional_maps_do_not_fabricate_vpn_or_overlay_readiness(self):
  cfg=overlay_config();r=view({'overlay':[],'maintenance':[],'vpn_egress':[],'draining_marks':[]},cfg);self.assertEqual(len(r['overlay']),1);self.assertTrue(r['overlay'][0]['stale']);self.assertIsNone(r['overlay'][0]['healthy'])

if __name__=='__main__':unittest.main()
