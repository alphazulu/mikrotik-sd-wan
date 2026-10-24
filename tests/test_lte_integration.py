import copy
from pathlib import Path
import unittest
from sdwan.wan import addressing_kind,inferred_kind,adopted_dynamic_route
from sdwan.config import load,validate,objects
from sdwan.discovery import candidates,generate,validate_wan_choices
from test_discovery import fixture,choices,build
ROOT=Path(__file__).resolve().parents[1]


def inventory():
    inv=fixture();inv['interface'][1]['type']='lte'
    inv['ip/address'][1]={'interface':'ether2','address':'100.64.1.2/32','dynamic':'true'}
    inv['ip/route'][1].update(gateway='ether2',dynamic='true',modem='true')
    inv['interface/lte']=[{'.id':'*A','name':'ether2','apn-profiles':'cellular','disabled':'false','running':'true'}]
    inv['interface/lte/apn']=[{'.id':'*B','name':'cellular','add-default-route':'true','default-route-distance':'2','ip-type':'ipv4'}]
    inv['candidates']=candidates(inv);return inv


class LTEIntegrationTests(unittest.TestCase):
    def config(self):
        c=load(ROOT/'config/sdwan.json');w=c['wans'][2];w.update(kind='lte',interface='lte1',apn_profile='cellular');w.pop('address');w.pop('gateway');return c
    def test_full_config_and_interface_gateway_plan(self):
        c=validate(self.config());planned=objects(c)
        self.assertEqual(planned[('ip/route','sdwan:v1:pinroute:wan3')]['gateway'],'lte1')
        self.assertEqual(planned[('ip/route','sdwan:v1:route:strict103:wan3')]['gateway'],'lte1')
        self.assertNotIn('src-address',planned[('routing/rule','sdwan:v1:pinrule:wan3')])
    def test_explicit_apn_reference_required(self):
        for value in (None,'','a,b','a\nsecret'):
            c=self.config();c['wans'][2]['apn_profile']=value
            with self.assertRaisesRegex(ValueError,'apn_profile'):validate(c)
    def test_lease_snapshot_not_accepted(self):
        for key in ('address','gateway'):
            c=self.config();c['wans'][2][key]='100.64.1.2'
            with self.assertRaisesRegex(ValueError,'snapshot'):validate(c)
    def test_apn_field_not_silently_accepted_for_other_modes(self):
        c=load(ROOT/'config/sdwan.json');c['wans'][0]['apn_profile']='cellular'
        with self.assertRaisesRegex(ValueError,'only valid for LTE'):validate(c)
    def test_native_identity_is_not_inferred_from_interface_name(self):
        self.assertEqual(inferred_kind('lte1',[],[]),'static')
        self.assertEqual(inferred_kind('renamed modem',[],[],[{'name':'renamed modem'}]),'lte')
        with self.assertRaisesRegex(ValueError,'Ambiguous'):inferred_kind('lte1',[{'interface':'lte1'}],[],[{'name':'lte1'}])
    def test_dynamic_route_requires_modem_protocol_and_interface(self):
        w=self.config()['wans'];route={'dynamic':'true','modem':'true','gateway':'lte1'}
        self.assertTrue(adopted_dynamic_route(route,w))
        self.assertTrue(adopted_dynamic_route(dict(route,gateway='100.64.0.1%lte1'),w))
        for changed in ({'dynamic':'false'},{'modem':'false'},{'gateway':'lte-other'}):self.assertFalse(adopted_dynamic_route(dict(route,**changed),w))
    def test_discovery_detects_lte_and_copies_apn_not_lease(self):
        inv=inventory();c=build(inv);w=c['wans'][1]
        self.assertEqual((w['kind'],w['apn_profile']),('lte','cellular'))
        self.assertNotIn('address',w);self.assertNotIn('gateway',w)
        self.assertEqual(c['takeover_routes'][0]['.id'],'*1')
    def test_unregistered_lte_can_be_selected(self):
        inv=inventory();inv['ip/address']=inv['ip/address'][:1]+inv['ip/address'][2:];inv['ip/route']=inv['ip/route'][:1]
        inv['interface'][1]['running']='false';inv['interface/lte'][0]['running']='false';inv['candidates']=candidates(inv)
        selected=choices(inv);selected[1]['priority']=2
        c=build(inv,selected);self.assertEqual(c['wans'][1]['kind'],'lte')
    def test_shared_apn_rejected_before_generation(self):
        inv=inventory();inv['interface/lte'].append({'name':'unselected','apn-profiles':['cellular'],'disabled':'true'})
        with self.assertRaisesRegex(ValueError,'shared'):build(inv)
    def test_profile_drift_rejected_during_selection(self):
        inv=inventory();cs=choices(inv);cs[1]['apn_profile']='previous'
        with self.assertRaisesRegex(ValueError,'changed'):validate_wan_choices(inv,cs)
    def test_passthrough_rejected(self):
        inv=inventory();inv['interface/lte/apn'][0]['passthrough-interface']='ether3'
        with self.assertRaisesRegex(ValueError,'passthrough'):build(inv)
    def test_native_lte_unreadable_is_not_offered_as_static(self):
        inv=inventory();inv['interface/lte']=[];inv['candidates']=candidates(inv)
        self.assertTrue(inv['candidates'][1]['kind_error'])
        with self.assertRaises(ValueError):build(inv)
    def test_multi_apn_not_silently_flattened(self):
        inv=inventory();inv['interface/lte'][0]['apn-profiles']='cellular,second';inv['candidates']=candidates(inv)
        with self.assertRaises(ValueError):build(inv)


if __name__=='__main__':unittest.main()
