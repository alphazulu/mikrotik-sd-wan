import copy
import json
import unittest
from sdwan.lte import apn_binding,profile_names
from sdwan.discovery import FIELDS


class LTEAPNTests(unittest.TestCase):
    def setUp(self):
        self.radios=[{'name':'lte1','apn-profiles':'default'}]
        self.apns=[{'.id':'*1','name':'default','add-default-route':'true','default-route-distance':'2','use-peer-dns':'false','ip-type':'ipv4','password':'never-export-this','user':'private-user'}]
    def binding(self,**kwargs):return apn_binding('lte1',self.radios,self.apns,**kwargs)
    def test_uses_apn_metadata_without_credentials_or_mutation(self):
        before=copy.deepcopy(self.apns);out=self.binding()
        self.assertEqual(out['apn_profile'],'default');self.assertEqual(out['add_default_route'],'true');self.assertEqual(out['default_route_distance'],'2')
        self.assertNotIn('never-export-this',json.dumps(out));self.assertNotIn('private-user',json.dumps(out));self.assertEqual(self.apns,before)
    def test_disabled_autodefault_can_hide_distance(self):
        self.apns[0]['add-default-route']='false';self.apns[0].pop('default-route-distance')
        self.assertIsNone(self.binding()['default_route_distance'])
    def test_unknown_automatic_route_setting_rejected(self):
        for mode in (None,'unknown',2):
            self.apns[0]['add-default-route']=mode
            with self.assertRaisesRegex(ValueError,'unavailable'):self.binding()
    def test_native_boolean_automatic_route_setting(self):
        self.apns[0]['add-default-route']=False
        self.assertIs(self.binding()['add_default_route'],False)
    def test_peer_dns_requires_explicit_preparation_without_mutating_apn(self):
        for value in (True,'true','yes',None):
            self.apns[0]['use-peer-dns']=value;before=copy.deepcopy(self.apns)
            with self.assertRaisesRegex(ValueError,'configure router DNS explicitly'):self.binding()
            self.assertEqual(before,self.apns)
    def test_duplicate_apn_name_rejected(self):
        self.apns*=2
        with self.assertRaisesRegex(ValueError,'ambiguous'):self.binding()
    def test_explicit_none_passthrough_is_routed(self):
        self.apns[0]['passthrough-interface']='none'
        self.assertEqual(self.binding()['apn_profile'],'default')
    def test_new_and_legacy_profile_field(self):
        self.assertEqual(profile_names({'apn-profile':'new','apn-profiles':'old'}),['new'])
        self.assertEqual(profile_names({'apn-profiles':['default']}),['default'])
    def test_missing_or_ambiguous_radio_rejected(self):
        for radios in ([],self.radios*2):
            with self.assertRaisesRegex(ValueError,'LTE interface'):apn_binding('lte1',radios,self.apns)
    def test_multi_apn_rejected(self):
        self.radios[0]['apn-profiles']='default,another'
        with self.assertRaisesRegex(ValueError,'exactly one'):self.binding()
    def test_missing_apn_rejected(self):
        self.apns=[]
        with self.assertRaisesRegex(ValueError,'APN profile'):self.binding()
    def test_profile_drift_rejected(self):
        with self.assertRaisesRegex(ValueError,'changed'):self.binding(expected_profile='previous')
    def test_passthrough_rejected(self):
        self.apns[0]['passthrough-interface']='ether1'
        with self.assertRaisesRegex(ValueError,'passthrough'):self.binding()
    def test_ipv6_only_rejected(self):
        self.apns[0]['ip-type']='ipv6'
        with self.assertRaisesRegex(ValueError,'IPv4'):self.binding()
    def test_shared_profile_rejected_even_if_other_modem_disabled(self):
        self.radios.append({'name':'lte2','apn-profiles':'default','disabled':'true'})
        with self.assertRaisesRegex(ValueError,'unselected'):self.binding()
    def test_all_sharing_modems_can_be_managed_together(self):
        self.radios.append({'name':'lte2','apn-profiles':'default'})
        self.assertEqual(self.binding(managed_interfaces=['lte1','lte2'])['apn_id'],'*1')
    def test_unrelated_apn_not_affected(self):
        self.radios.append({'name':'lte2','apn-profiles':'separate'})
        self.assertEqual(self.binding()['apn_profile'],'default')
    def test_discovery_never_requests_apn_or_sim_credentials(self):
        for path in ('interface/lte','interface/lte/apn'):
            fields=set(FIELDS[path].split(','));self.assertFalse(fields&{'password','user','pin','modem-init','imsi','imei'})
        self.assertIn('add-default-route',FIELDS['interface/lte/apn'])


if __name__=='__main__':unittest.main()
