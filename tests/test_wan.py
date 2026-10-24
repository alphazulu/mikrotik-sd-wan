import unittest
import copy
from pathlib import Path
from sdwan.wan import addressing_kind,inferred_kind,adopted_dynamic_route
from sdwan.config import load,validate,objects


class WANAddressingTests(unittest.TestCase):
    def test_legacy_static_without_kind(self):
        self.assertEqual(addressing_kind({'address':'192.0.2.2','gateway':'192.0.2.1'}),'static')
    def test_dynamic_can_be_configured_before_first_session(self):
        for kind in ('dhcp','pppoe'):
            self.assertEqual(addressing_kind({'kind':kind}),kind)
            self.assertEqual(addressing_kind({'kind':kind,'address':'','gateway':''}),kind)
    def test_saved_dynamic_address_or_gateway_is_rejected(self):
        for kind in ('dhcp','pppoe'):
            for field in ('address','gateway'):
                with self.assertRaisesRegex(ValueError,'snapshot'):addressing_kind({'kind':kind,field:'192.0.2.1'})
    def test_static_needs_both_real_ipv4_values(self):
        for spec in ({},{'address':'192.0.2.2'},{'address':'::1','gateway':'192.0.2.1'},{'address':'0.0.0.0','gateway':'192.0.2.1'},{'address':'192.0.2.1','gateway':'192.0.2.1'}):
            with self.assertRaises(ValueError):addressing_kind(spec)
    def test_unknown_addressing_kind_is_rejected(self):
        for kind in ('auto','lte',None,1):
            with self.assertRaises(ValueError):addressing_kind({'kind':kind})
    def test_dhcp_is_detected_on_its_l3_vlan(self):
        self.assertEqual(inferred_kind('vlan-isp',[{'interface':'vlan-isp','disabled':'false'}],[]),'dhcp')
    def test_disabled_factory_dhcp_does_not_override_static_wan(self):
        self.assertEqual(inferred_kind('ether1',[{'interface':'ether1','disabled':'true'}],[]),'static')
    def test_pppoe_logical_interface_is_wan_not_its_parent(self):
        clients=[{'name':'pppoe-isp','interface':'ether1'}]
        self.assertEqual(inferred_kind('pppoe-isp',[],clients),'pppoe')
        self.assertEqual(inferred_kind('ether1',[],clients),'static')
    def test_ambiguous_clients_are_not_guessed(self):
        with self.assertRaisesRegex(ValueError,'Multiple'):inferred_kind('ether1',[{'interface':'ether1'},{'interface':'ether1'}],[])
        with self.assertRaisesRegex(ValueError,'Both'):inferred_kind('pppoe-isp',[{'interface':'pppoe-isp'}],[{'name':'pppoe-isp'}])
    def mixed_config(self):
        cfg=load(Path(__file__).resolve().parents[1]/'config/sdwan.json')
        for wan,kind in zip(cfg['wans'][1:],('dhcp','pppoe')):
            wan['kind']=kind;wan.pop('address');wan.pop('gateway')
        return cfg
    def test_full_config_allows_unbound_dynamic_wans_without_mutating_json(self):
        cfg=self.mixed_config();before=copy.deepcopy(cfg);validate(cfg);self.assertEqual(cfg,before)
    def test_full_config_rejects_dynamic_lease_snapshots(self):
        cfg=self.mixed_config();cfg['wans'][1]['address']='192.0.2.5'
        with self.assertRaisesRegex(ValueError,'snapshot'):validate(cfg)
    def test_plan_reserves_dynamic_bindings_without_invented_ip_addresses(self):
        cfg=self.mixed_config();plan=objects(validate(cfg))
        self.assertNotIn('gateway',plan[('ip/route','sdwan:v1:pinroute:wan2')])
        self.assertNotIn('src-address',plan[('routing/rule','sdwan:v1:pinrule:wan2')])
        self.assertNotIn('src-address',plan[('ip/firewall/mangle','sdwan:v1:source:wan2')])
        self.assertEqual(plan[('ip/route','sdwan:v1:pinroute:wan3')]['gateway'],cfg['wans'][2]['interface'])
    def test_only_routes_of_selected_dynamic_clients_are_adopted(self):
        wans=[{'kind':'dhcp','interface':'vlan-isp'},{'kind':'pppoe','interface':'pppoe-isp'}]
        route={'dynamic':'true','dhcp':'true','vrf-interface':'vlan-isp','gateway':'192.0.2.1'}
        self.assertTrue(adopted_dynamic_route(route,wans))
        for changed in ({'dhcp':'false'},{'dynamic':'false'},{'vrf-interface':'another-isp'}):self.assertFalse(adopted_dynamic_route(dict(route,**changed),wans))
        self.assertTrue(adopted_dynamic_route({'dynamic':'true','gateway':'pppoe-isp'},wans))
        self.assertFalse(adopted_dynamic_route({'dynamic':'true','gateway':'another-pppoe'},wans))
    def test_dynamic_route_delimiters_in_interface_name_are_rejected(self):
        for interface in ('isp@other-table','isp%other-interface'):
            cfg=self.mixed_config();cfg['wans'][1]['interface']=interface
            with self.assertRaisesRegex(ValueError,'delimiters'):validate(cfg)


if __name__=='__main__':unittest.main()
