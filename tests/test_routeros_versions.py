import os
import unittest
from unittest.mock import patch
from sdwan.routeros_versions import allowed,require
from sdwan.platform_support import assess
from test_platform_support import fixture

class RouterOSVersionsTests(unittest.TestCase):
    def test_new_hardware_does_not_silently_expand_supported_versions(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertTrue(allowed('7.24.5'))
            for version in ('7.25.1','7.25.2','7.26','','7.24.5beta1'):
                self.assertFalse(allowed(version))
                with self.assertRaises(ValueError):require({'version':version})
    def test_explicit_lab_opt_in_is_exact_and_keeps_actual_version(self):
        with patch.dict(os.environ,{'SDWAN_EXPERIMENTAL_ROUTEROS':'7.25.1'}):
            self.assertEqual(require({'version':'7.25.1 (stable)'}),'7.25.1')
            self.assertTrue(allowed('7.24.5'))
            self.assertFalse(allowed('7.25.2'))
        with patch.dict(os.environ,{'SDWAN_EXPERIMENTAL_ROUTEROS':'7.26'}):self.assertFalse(allowed('7.26'))
    def test_lab_readiness_still_requires_packages_matching_actual_device(self):
        resource,caps,cfg=fixture();resource['version']='7.25.1'
        with patch.dict(os.environ,{'SDWAN_EXPERIMENTAL_ROUTEROS':'7.25.1'}):
            self.assertFalse(assess(resource,caps,cfg)['ready'])
            for row in caps['system/package']:row['version']='7.25.1'
            result=assess(resource,caps,cfg)
            self.assertTrue(result['ready'])
            self.assertIn('экспериментальный',result['checks'][0]['detail'])
            self.assertEqual(result['recommendation']['confidence'],'unmeasured')
