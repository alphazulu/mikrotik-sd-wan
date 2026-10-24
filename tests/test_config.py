import copy
import json
from pathlib import Path
import unittest
from sdwan.config import validate, objects

ROOT=Path(__file__).resolve().parents[1]

class ConfigTests(unittest.TestCase):
    def setUp(self):self.c=json.loads((ROOT/'config/sdwan.json').read_text())
    def invalid(self):
        with self.assertRaises((ValueError,KeyError,TypeError)):validate(self.c)
    def test_unknown_fields_rejected(self):self.c['health']['intervall_seconds']=2;self.invalid()
    def test_fractional_sla_supported(self):self.c['sla_profiles']['voice']['loss_percent']=0.5;validate(self.c)
    def test_excessive_fraction_precision_rejected(self):self.c['sla_profiles']['voice']['loss_percent']=0.005;self.invalid()
    def test_plan_contains_only_owned_objects(self):
        planned=objects(validate(self.c))
        self.assertTrue(planned)
        self.assertTrue(all(tag.startswith('sdwan:v1:') for menu,tag in planned))
        self.assertTrue(all(menu in ('ip/route','routing/rule','tool/netwatch','ip/firewall/mangle','ip/firewall/address-list') for menu,tag in planned))
    def test_valid_lab(self):validate(self.c)
    def test_quorum_cannot_exceed_targets(self):self.c['health']['quorum']=4;self.invalid()
    def test_probe_train_must_fit(self):self.c['health']['timeout_ms']=2000;self.invalid()
    def test_duplicate_target_does_not_count_as_independent(self):self.c['wans'][0]['probes'][1]=dict(self.c['wans'][0]['probes'][0],name='other');self.invalid()
    def test_client_source_overlap_is_rejected(self):self.c['policies'][1]['source']='192.168.50.0/24';self.invalid()
    def test_strict_cannot_have_backup(self):self.c['policies'][-1]['wans'].append('wan1');self.invalid()
    def test_unknown_wan_is_rejected(self):self.c['policies'][1]['wans']=['typo'];self.invalid()
    def test_shared_tables_rejected(self):self.c['policies'][2]['table']=self.c['policies'][1]['table'];self.invalid()
    def test_local_default_bypass_rejected(self):self.c['local_networks'].append('0.0.0.0/0');self.invalid()
    def test_nan_threshold_rejected(self):self.c['sla_profiles']['voice']['loss_percent']=float('nan');self.invalid()
    def test_boolean_timing_rejected(self):self.c['health']['fail_windows']=True;self.invalid()
    def test_negative_hold_rejected(self):self.c['health']['hold_down_seconds']=-1;self.invalid()
    def test_duplicate_probe_name_rejected(self):self.c['wans'][0]['probes'][1]['name']='a';self.invalid()
    def test_zero_fail_windows_rejected(self):self.c['health']['fail_windows']=0;self.invalid()
    def test_foreign_table_rejected(self):self.c['wans'][0]['probe_table']='main';self.invalid()

if __name__=='__main__':unittest.main()
