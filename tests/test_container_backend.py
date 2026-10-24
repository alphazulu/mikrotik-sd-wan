import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from sdwan.config import load,validate
from sdwan.container_backend import controller_source
from sdwan.diagnostics import view

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('container_unit_cli',ROOT/'sdwan.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class ContainerBackendTests(unittest.TestCase):
    def setUp(self):self.cfg=load(ROOT/'config/sdwan.json')
    def container(self):
        c=copy.deepcopy(self.cfg);c['controller_backend']='container';c['container']={'subnet':'192.168.244.0/30'};c['local_networks'].append('192.168.244.0/30');return c
    def test_default_bundle_preserves_all_canonical_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out=cli.bundle(self.cfg,directory)
            self.assertEqual(len(list(out.iterdir())),9)
            for name in cli.FILES:self.assertEqual((out/name).read_bytes(),(ROOT/'native'/name).read_bytes())
    def test_container_bundle_is_single_controller_with_protected_initial_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            c=self.container();validate(c);out=cli.bundle(c,directory)
            self.assertEqual(len(list(out.iterdir())),9)
            controller=(out/'sdwan-controller.rsc').read_text()
            self.assertIn('192.168.244.2',controller)
            self.assertNotIn('172.31.255.2',controller)
            self.assertIn('container adapter unavailable',controller)
            self.assertIn('start-on-boot=yes',(out/'sdwan-install.rsc').read_text())
            self.assertIn('($status->"container")->"active"',(out/'sdwan-deploy-watchdog.rsc').read_text())
            for name in set(cli.FILES)-{'sdwan-controller.rsc','sdwan-install.rsc','sdwan-deploy-watchdog.rsc'}:
                self.assertEqual((out/name).read_bytes(),(ROOT/'native'/name).read_bytes())
    def test_credentials_and_unknown_container_options_rejected(self):
        for key in ('password','api_password','username','endpoint','extra'):
            with self.subTest(key=key):
                c=self.container();c['container'][key]='should-not-be-public'
                with self.assertRaises(ValueError):validate(c)
    def test_subnet_and_heartbeat_budget_must_be_safe(self):
        for field,value in [('subnet','8.8.8.0/30'),('subnet','172.31.255.0/24'),('poll_ms',10000),('poll_ms',True),('storage','disk1/../root'),('image_file','image.rsc'),('memory_max_bytes',1048576)]:
            with self.subTest(field=field,value=value):
                c=self.container();c['container'][field]=value
                with self.assertRaises(ValueError):validate(c)
    def test_container_management_bypass_is_explicit(self):
        c=self.container();c['local_networks'].remove('192.168.244.0/30')
        with self.assertRaisesRegex(ValueError,'local_networks'):validate(c)
    def test_unknown_backend_rejected(self):
        self.cfg['controller_backend']='external'
        with self.assertRaisesRegex(ValueError,'controller_backend'):validate(self.cfg)
    def test_diagnostics_distinguishes_container_fallback_and_stale_and_excludes_secrets(self):
        c=self.container();status={'backend':'container','enabled':True,'revision':c['revision'],'uptime_seconds':100,'container':{'active':True,'owner_instance':'a'*32,'password':'secret'}}
        actual=view(status,c,router_uptime=100);self.assertEqual(actual['controller_mode'],'container');self.assertNotIn('password',actual['container'])
        status['container']['active']=False;self.assertEqual(view(status,c,router_uptime=100)['controller_mode'],'routeros-fallback')
        self.assertEqual(view(status,c,router_uptime=200)['controller_mode'],'unknown')

if __name__=='__main__':unittest.main()
