import unittest
from sdwan.discovery import candidates,FIELDS
from test_lte_integration import inventory
from sdwan.wan import adopted_dynamic_route


class RNDISInventoryTests(unittest.TestCase):
    def test_router_owned_dhcp_keeps_lte_type_and_apn(self):
        inv=inventory();inv['ip/dhcp-client']=[{'interface':'ether2','dynamic':'true','disabled':'false'}]
        row=next(row for row in candidates(inv) if row['interface']=='ether2')
        self.assertEqual((row['kind'],row['apn_profile'],row['kind_error']),('lte','cellular',''))
        self.assertIn('dynamic',FIELDS['ip/dhcp-client'].split(','))
        self.assertTrue(adopted_dynamic_route({'dynamic':'true','dhcp':'true','vrf-interface':'ether2'},[{'interface':'ether2','kind':'lte'}]))
    def test_user_dhcp_conflict_does_not_turn_into_a_permission_error(self):
        inv=inventory();inv['ip/dhcp-client']=[{'interface':'ether2','dynamic':'false','disabled':'false'}]
        row=next(row for row in candidates(inv) if row['interface']=='ether2')
        self.assertEqual((row['kind'],row['apn_profile']),('lte','cellular'))
        self.assertIn('Ambiguous',row['kind_error']);self.assertNotIn('прав',row['kind_error'])
    def test_missing_inventory_keeps_original_api_reason(self):
        inv=inventory();inv['interface/lte']=[];inv['warnings']=['interface/lte: permission denied']
        row=next(row for row in candidates(inv) if row['interface']=='ether2')
        self.assertIn('permission denied',row['kind_error'])


if __name__=='__main__':unittest.main()
