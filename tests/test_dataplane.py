from pathlib import Path
import unittest
from sdwan.config import load
from sdwan.dataplane import objects

ROOT=Path(__file__).resolve().parents[1]


class DataplaneTests(unittest.TestCase):
    def setUp(self):self.config=load(ROOT/'config/sdwan.json')
    def test_client_classifiers_precede_default(self):
        tags=[tag for (menu,tag) in objects(self.config) if 'classify:' in tag]
        self.assertLess(tags.index('sdwan:v1:classify:client102:wan2'),tags.index('sdwan:v1:classify:default:wan1'))
    def test_inbound_dnat_and_router_replies_share_a_wan_mark(self):
        rules=objects(self.config)
        incoming=rules[('ip/firewall/mangle','sdwan:v1:in:wan3')]
        for chain in ('sdwan-pre','sdwan-output'):
            reply=rules[('ip/firewall/mangle','sdwan:v1:reply:'+chain+':wan3')]
            self.assertEqual(reply['connection-mark'],incoming['new-connection-mark'])
            self.assertEqual(reply['new-routing-mark'],'sdwan-probe-wan3')
    def test_same_wan_different_policies_have_different_conntrack_marks(self):
        marks=[v['new-connection-mark'] for (menu,tag),v in objects(self.config).items() if 'new-connection-mark' in v and ':probe-classify:' not in tag]
        self.assertEqual(len(marks),len(set(marks)))
        self.assertIn('sdwan-out-client101:wan2',marks);self.assertIn('sdwan-out-client102:wan2',marks)
    def test_every_pinned_table_has_fail_closed_route(self):
        rules=objects(self.config)
        for wan in self.config['wans']:
            route=rules[('ip/route','sdwan:v1:pin-blackhole:'+wan['name'])]
            self.assertEqual(route['blackhole'],'true');self.assertEqual(route['routing-table'],wan['probe_table'])
    def test_no_enabled_wan_classifier_does_not_fall_through_to_default(self):
        rule=objects(self.config)[('ip/firewall/mangle','sdwan:v1:guard:strict103')]
        self.assertEqual(rule['src-address'],'192.168.50.103/32')
        self.assertEqual(rule['new-routing-mark'],'sdwan-strict103')
        self.assertEqual(rule['passthrough'],'false')
    def test_generated_rules_do_not_open_input_services(self):
        self.assertFalse(any(menu=='ip/firewall/filter' for menu,_ in objects(self.config)))
    def test_router_originated_flows_have_separate_marks(self):
        rules=objects(self.config)
        for wan in self.config['wans']:
            outgoing=rules[('ip/firewall/mangle','sdwan:v1:router-origin:'+wan['name'])]
            self.assertEqual(outgoing['src-address-type'],'local')
            self.assertEqual(outgoing['out-interface'],wan['interface'])
            reply=rules[('ip/firewall/mangle','sdwan:v1:router-reply:'+wan['name'])]
            self.assertEqual(reply['connection-mark'],outgoing['new-connection-mark'])
    def test_unmarked_established_client_flow_can_be_classified_after_a_transition(self):
        rule=objects(self.config)[('ip/firewall/mangle','sdwan:v1:classify:client102:wan1')]
        self.assertIn('established',rule['connection-state'].split(','))
        self.assertEqual(rule['connection-mark'],'no-mark')
    def test_health_probes_use_a_separate_mark_from_router_sessions(self):
        rules=objects(self.config)
        probe=rules[('ip/firewall/mangle','sdwan:v1:probe-classify:wan1:no-mark')]
        router=rules[('ip/firewall/mangle','sdwan:v1:router-origin:wan1')]
        self.assertNotEqual(probe['new-connection-mark'],router['new-connection-mark'])
        self.assertEqual(probe['dst-address-list'],'sdwan-probes-wan1')


if __name__=='__main__':unittest.main()
