import unittest
from sdwan.container_runtime import api_service_access

class ContainerAPIAccessTests(unittest.TestCase):
    def test_restricted_new_service_field_is_not_mistaken_for_unrestricted(self):
        allowed,update=api_service_access({'available-from':'192.0.2.0/24','disabled':'false'},'172.31.255.2')
        self.assertFalse(allowed);self.assertEqual(update,{'available-from':'192.0.2.0/24,172.31.255.2/32'})
    def test_legacy_field_preserves_existing_ipv4_and_ipv6_management_prefixes(self):
        allowed,update=api_service_access({'address':'192.0.2.0/24,2001:db8::/32'},'172.31.255.2')
        self.assertFalse(allowed);self.assertEqual(update,{'address':'192.0.2.0/24,2001:db8::/32,172.31.255.2/32'})
    def test_repeated_prepare_does_not_duplicate_a_guest_already_covered(self):
        for field in ('address','available-from'):
            for prefix in ('172.31.255.2/32','172.31.255.0/30','0.0.0.0/0'):
                with self.subTest(field=field,prefix=prefix):self.assertEqual(api_service_access({field:prefix},'172.31.255.2'),(True,{}))
        self.assertEqual(api_service_access({'available-from':'192.0.2.0/24','address':''},'172.31.255.2')[0],False)
    def test_disabled_service_enables_only_needed_scope_and_preserves_old_prefixes(self):
        self.assertEqual(api_service_access({'available-from':'','disabled':'true'},'172.31.255.2'),(False,{'disabled':'no','available-from':'172.31.255.2/32'}))
        self.assertEqual(api_service_access({'address':'192.0.2.0/24','disabled':'true'},'172.31.255.2'),(False,{'disabled':'no','address':'192.0.2.0/24,172.31.255.2/32'}))
    def test_enabled_unrestricted_and_unreadable_access_lists_are_distinguished(self):
        self.assertEqual(api_service_access({'available-from':''},'172.31.255.2'),(True,{}))
        self.assertEqual(api_service_access({},'172.31.255.2'),(True,{}))
        for value in (None,[],123,'not-a-prefix'):
            with self.subTest(value=value),self.assertRaises(ValueError):api_service_access({'available-from':value},'172.31.255.2')
