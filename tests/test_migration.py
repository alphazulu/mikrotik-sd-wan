import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sdwan import migration
from test_discovery import fixture,build

ROOT=Path(__file__).resolve().parents[1]


class MigrationTests(unittest.TestCase):
    def inventory(self):
        inv=fixture();inv['ip/firewall/mangle']=[{'.id':'*A','chain':'branch-exit','action':'mark-connection','new-connection-mark':'old-provider','comment':'branch policy','src-address-list':'branch-users'}]
        return inv
    def test_explicit_draft_generation_keeps_existing_rules_and_config_schema(self):
        inv=self.inventory();before=copy.deepcopy(inv)
        with self.assertRaisesRegex(ValueError,'mangle'):build(inv)
        cfg=build(inv,allow_foreign_mangle=True)
        self.assertEqual(len(cfg['wans']),2);self.assertEqual(inv['ip/firewall/mangle'],before['ip/firewall/mangle'])
        self.assertNotIn('disable_mangle',cfg);self.assertNotIn('migration',cfg)
        report=migration.review(inv);self.assertEqual(report['status'],'review_required')
        self.assertEqual(report['blocking_rules'][0]['.id'],'*A')
        self.assertIn('old-provider',migration.text(report));self.assertIn('Не отключайте все mangle',migration.text(report))
    def test_draft_exception_does_not_relax_raw_or_unreadable_inventory(self):
        inv=self.inventory();inv['ip/firewall/raw']=[{'action':'notrack'}]
        with self.assertRaisesRegex(ValueError,'notrack'):build(inv,allow_foreign_mangle=True)
        inv.pop('ip/firewall/raw');inv['unreadable_paths']=['ip/firewall/mangle']
        with self.assertRaisesRegex(ValueError,'Недостаточно данных'):build(inv,allow_foreign_mangle=True)
    def test_qos_disabled_and_owned_rules_are_not_in_the_disable_list(self):
        rules=[{'action':kind} for kind in ('change-mss','change-dscp','mark-packet','jump','accept')]
        rules += [{'action':'mark-routing','disabled':value} for value in (True,'true','yes','1')]
        rules += [{'action':'mark-connection','comment':'sdwan:v1:in:wan1'}]
        self.assertEqual(migration.foreign_marks(rules),[])
        report=migration.review({'ip/firewall/mangle':rules});self.assertEqual(report['status'],'no_mark_conflicts')
        self.assertIn('не подтверждение готовности',migration.text(report))
    def test_report_does_not_copy_unrelated_sensitive_properties(self):
        inv=self.inventory();inv['ip/firewall/mangle'][0]['password']='must-never-be-copied'
        inv['credentials']={'password':'another-secret'}
        report=migration.review(inv)
        self.assertNotIn('secret',json.dumps(report));self.assertNotIn('must-never',json.dumps(report))
    def test_sidecar_roundtrip_and_bundle_report_keep_warning(self):
        report=migration.review(self.inventory())
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'draft.json';config.write_text('{}')
            migration.write(report,config.parent,basename=config.name+'.migration')
            self.assertEqual(migration.read(config),report)
            migration.write(report,Path(directory)/'bundle')
            text=(Path(directory)/'bundle/MIGRATION-REVIEW.txt').read_text(encoding='utf-8')
            self.assertIn('Установка заблокирована',text);self.assertIn('branch-exit',text)
            self.assertNotIn('/ip/firewall/mangle/disable',text)
    def test_missing_and_corrupt_sidecars_do_not_say_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            config=Path(directory)/'draft.json'
            self.assertEqual(migration.read(config)['status'],'not_checked')
            path=Path(str(config)+'.migration.json')
            for value in ([],{'schema_version':1,'blocking_rules':['wrong']},{'schema_version':9,'blocking_rules':[]}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):migration.read(config)
    def test_fresh_api_preflight_still_blocks_apply_before_payload_or_watchdog(self):
        inv=self.inventory();cfg=build(inv,allow_foreign_mangle=True)
        spec=importlib.util.spec_from_file_location('migration_test_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        class Router:
            def __init__(self):self.calls=[]
            def call(self,path,data=None,method=None):
                self.calls.append((path,method))
                if path=='system/identity':return inv['identity']
                if path=='system/resource':return inv['resource']
                return inv.get(path,[])
        router=Router()
        # Omitting a saved review cannot bypass the fresh installation guard.
        with patch('sdwan.deployment.start') as start:
            with self.assertRaisesRegex(ValueError,'old-provider'):cli.apply(router,cfg,inv['identity']['name'])
        start.assert_not_called();self.assertTrue(all(method is None for _,method in router.calls))


if __name__=='__main__':unittest.main()
