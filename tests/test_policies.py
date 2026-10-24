import copy,json,unittest
from pathlib import Path
from sdwan.config import validate,objects
from sdwan.policies import conflicts,match_flow,ordered,signature
from sdwan.diagnostics import view,explain,seconds

ROOT=Path(__file__).resolve().parents[1]


def config():
    c=json.loads((ROOT/'config/sdwan.json').read_text())
    for i,p in enumerate(c['policies'][1:],1):p['priority']=100+i*10
    c['groups']={'phones':['192.168.50.101/32','192.168.50.102/32'],'services':['198.19.0.0/24']}
    app=dict(name='sip',source='0.0.0.0/0',source_group='phones',destination_group='services',in_interface='vlan-voice',protocol='udp',dst_ports='5060,10000-20000',table='sdwan-sip',profile='voice',mode='prefer',wans=['wan2','wan1'],allow_degraded=False,priority=10)
    c['policies'].append(app)
    return c


class PolicyTests(unittest.TestCase):
    def setUp(self):self.c=config()
    def bad(self):
        with self.assertRaises((ValueError,TypeError)):validate(self.c)
    def test_old_config_unchanged(self):validate(json.loads((ROOT/'config/sdwan.json').read_text()))
    def test_group_protocol_ports_interface_match(self):
        validate(self.c);r=match_flow(self.c,'192.168.50.101','198.19.0.1','udp',12345,5060,'vlan-voice');self.assertEqual(r['policy'],'sip')
    def test_disjoint_port_falls_to_client(self):self.assertEqual(match_flow(self.c,'192.168.50.101','198.19.0.1','udp',12345,443,'vlan-voice')['policy'],'client101')
    def test_wrong_interface_not_matched(self):self.assertEqual(match_flow(self.c,'192.168.50.101','198.19.0.1','udp',12345,5060,'ether5')['policy'],'client101')
    def test_protocol_not_application_guess(self):self.assertEqual(match_flow(self.c,'192.168.50.101','198.19.0.1','tcp',12345,5060,'vlan-voice')['policy'],'client101')
    def test_destination_group_not_matched(self):self.assertEqual(match_flow(self.c,'192.168.50.101','203.0.113.1','udp',12345,5060,'vlan-voice')['policy'],'client101')
    def test_group_nonmember_falls_to_default(self):self.assertEqual(match_flow(self.c,'192.168.50.110','198.19.0.1','udp',12345,5060,'vlan-voice')['policy'],'default')
    def test_local_network_precedes_app(self):self.assertTrue(match_flow(self.c,'192.168.50.101','192.168.50.102','udp',12345,5060,'vlan-voice')['bypass'])
    def test_priority_order_independent_of_json_order(self):self.assertEqual(ordered(self.c)[0]['name'],'sip');self.assertFalse(ordered(self.c)[-1]['source'])
    def test_explicit_overlaps_reported(self):validate(self.c);self.assertTrue(any(x['first']=='sip' and x['later']=='client101' for x in conflicts(self.c)))
    def test_overlap_without_priority_rejected(self):self.c['policies'][1].pop('priority');self.bad()
    def test_duplicate_priority_rejected(self):self.c['policies'][1]['priority']=10;self.bad()
    def test_boolean_priority_rejected(self):self.c['policies'][-1]['priority']=True;self.bad()
    def test_unknown_group_rejected(self):self.c['policies'][-1]['source_group']='missing';self.bad()
    def test_empty_group_rejected(self):self.c['groups']['phones']=[];self.bad()
    def test_overlapping_group_members_rejected(self):self.c['groups']['phones'].append('192.168.50.0/24');self.bad()
    def test_ports_require_transport_protocol(self):self.c['policies'][-1]['protocol']='any';self.bad()
    def test_invalid_port_ranges_rejected(self):
        for ports in ('0','65536','20-10','80,80','80-90,85','80;443','-1','80,'):
            with self.subTest(ports=ports):self.c['policies'][-1]['dst_ports']=ports;self.bad()
    def test_empty_group_intersection_rejected(self):self.c['policies'][-1]['source']='10.0.0.0/8';self.bad()
    def test_default_cannot_be_repurposed(self):self.c['policies'][0]['protocol']='tcp';self.bad()
    def test_selected_wan_not_ingress(self):self.c['policies'][-1]['in_interface']='ether2';self.bad()
    def test_plan_has_exact_guard_and_group_lists(self):
        o=objects(validate(self.c));a=o[('ip/firewall/mangle','sdwan:v1:classify:sip:wan2')];b=o[('ip/firewall/mangle','sdwan:v1:guard:sip')]
        for key in ('src-address','src-address-list','dst-address-list','in-interface','protocol','dst-port'):self.assertEqual(a[key],b[key])
        self.assertIn(('ip/route','sdwan:v1:policy-blackhole:sip'),o);self.assertNotIn(('routing/rule','sdwan:v1:client:sip'),o)
        self.assertIn(('ip/firewall/address-list','sdwan:v1:group:phones:0'),o)
    def test_signature_ignores_default_json_position(self):
        other=copy.deepcopy(self.c);other['policies']=ordered(other);self.assertEqual(signature(self.c),signature(other))
    def test_signature_tracks_group_selector_and_order(self):
        for mutate in (lambda c:c['groups']['phones'].append('192.168.50.111/32'),lambda c:c['policies'][-1].update(dst_ports='5061'),lambda c:c['policies'][-1].update(priority=900)):
            other=copy.deepcopy(self.c);mutate(other);self.assertNotEqual(signature(self.c),signature(other))
    def test_signature_does_not_include_wan_health_configuration(self):
        other=copy.deepcopy(self.c);other['health']['hold_down_seconds']=50;self.assertEqual(signature(self.c),signature(other))
    def test_diagnostic_view_allowlists_secrets(self):
        s={'uptime_seconds':10,'enabled':True,'revision':self.c['revision'],'password':'secret','samples':{'wan1':{'password':'secret','rtt_us':2000}},'events':[{'seq':1,'type':'policy','password':'secret'}]}
        report=view(s,self.c,router_uptime=30);self.assertTrue(report['telemetry_stale']);self.assertNotIn('secret',json.dumps(report))
    def test_flow_explainer_uses_active_policy_and_runtime_wan(self):
        r=view({'selected':{'sip':'wan2'}},self.c);e=explain(self.c,r,source='192.168.50.101',destination='198.19.0.1',protocol='udp',src_port=50000,dst_port=5060,in_interface='vlan-voice');self.assertEqual((e['policy'],e['selected']),('sip','wan2'))
    def test_empty_native_maps_and_disabled_scheduler_are_not_healthy(self):
        report=view({'enabled':False,'last_cleanup':[],'states':[],'samples':[],'policies':[]},self.c)
        self.assertTrue(report['telemetry_stale']);self.assertEqual(len(report['policies']),5)
    def test_wan_availability_uses_sla_not_only_carrier(self):
        report=view({'enabled':True,'revision':self.c['revision'],'samples':{'wan1':{'link_ready':True,'warming':False,'rtt_us':200000,'jitter_us':1000,'loss_basis_points':0}},'states':{'default/wan1':{'state':'down','verdict':'degraded','reason':'SLA threshold exceeded'}}},self.c)
        self.assertEqual(report['wans'][0]['state'],'down');self.assertIn('RTT',report['wans'][0]['reason'])
    def test_full_shadow_reported_after_priority_change(self):
        self.c['policies'][-1]['priority']=900;self.c['groups']['phones']=['192.168.50.101/32']
        self.assertTrue(any(x['later']=='sip' and x['shadowed'] for x in conflicts(self.c)))
    def test_narrow_application_rule_does_not_shadow_client_fallback(self):
        self.assertFalse(any(x['first']=='sip' and x['shadowed'] for x in conflicts(self.c)))
    def test_wan_ingress_is_not_a_client_application(self):
        self.assertTrue(match_flow(self.c,'203.0.113.1','192.168.50.101',in_interface='ether2')['bypass'])
    def test_router_primary_wan_ip_bypasses_client_policy(self):
        self.assertTrue(match_flow(self.c,'192.168.50.101','172.20.1.2')['bypass'])
    def test_diagnostic_dynamic_and_alias_ip_are_local(self):
        report=view({},self.c,router_addresses=['172.21.1.2'])
        result=explain(self.c,report,source='192.168.50.101',destination='172.21.1.2')
        self.assertTrue(result['bypass']);self.assertIn('локальная',result['reason'])
    def test_duration_parser(self):self.assertEqual(seconds('1w2d3h4m5s'),788645);self.assertEqual(seconds('1d02:03:04'),93784)

if __name__=='__main__':unittest.main()
