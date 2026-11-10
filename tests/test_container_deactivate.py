import unittest
from sdwan.container_runtime import deactivate
from sdwan.platform_support import assess
from test_platform_support import fixture

class DeactivateTests(unittest.TestCase):
    def test_native_rollback_without_installed_container_never_calls_its_menu(self):
        for packages in ([],[{'name':'container','version':'','available':'true','disabled':'true'}],[{'name':'container','version':'7.25.1','disabled':'true'}]):
            calls=[]
            class Router:
                def call(self,path,*args):
                    calls.append(path)
                    if path=='system/package':return packages
                    raise AssertionError('Unavailable container menu used: '+path)
            with self.subTest(packages=packages):
                deactivate(Router());self.assertEqual(calls,['system/package'])

    def test_only_owned_installed_running_container_is_stopped(self):
        for comment in ('sdwan-container:controller','someone-else'):
            calls=[]
            class Router:
                def call(self,path,data=None,method=None):
                    calls.append((path,data,method))
                    if path=='system/package':return [{'name':'container','version':'7.25.1','available':'false','disabled':'false'}]
                    if path=='container/print':return [{'.id':'*1','name':'sdwan-container-controller','comment':comment,'running':'true'}]
            deactivate(Router())
            mutations=[c for c in calls if c[0]!='system/package' and c[0]!='container/print']
            self.assertEqual(mutations,[('container/*1',{'start-on-boot':'no'},'PATCH'),('container/stop',{'numbers':'*1'},'POST')] if comment=='sdwan-container:controller' else [])

    def test_download_catalog_is_missing_prerequisite_not_installed_package(self):
        resource,caps,cfg=fixture();caps['system/package'][1]={'name':'container','version':'','available':'true','disabled':'true'}
        result=assess(resource,caps,cfg)
        self.assertFalse(result['ready']);self.assertEqual(result['missing_packages'],['container'])
