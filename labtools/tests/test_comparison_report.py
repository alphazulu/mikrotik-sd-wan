"""Synthetic unit fixtures only; these are never actual DUT measurements."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from comparison import STAGES, build_plan, compare_baselines
from comparison_report import export, markdown, summarize


def fixture():
    plan = build_plan({}, {'controller_source_sha256': 'a' * 64,
                          'images': {key: {'image_config_sha256': 'b' * 64} for key in ('base', 'web')}})
    rows = []
    for stage in STAGES:
        for case in plan['workloads']:
            for repeat in range(5):
                rate = 20000000 + (repeat - 2) * 1000 if case['kind'] == 'tcp' else 3000 + repeat - 2
                metrics = {'pass': True, 'observed_mode': stage, 'rate_unit': {'tcp': 'bps', 'udp': 'pps', 'cps': 'cps'}[case['kind']],
                           'receiver_rate': rate, 'dut_cpu_mean_percent': 10 + repeat, 'dut_cpu_p95_percent': 20 + repeat,
                           'dut_memory_free_min_bytes': 1048576 + repeat * 100, 'generator_cpu_p95_max_percent': 5,
                           'host_steal_p95_percent': 0, 'container_memory_peak_bytes': 1000 + repeat if stage in ('container', 'container-web') else 0,
                           'write_sectors_delta': 0}
                if case['kind'] == 'tcp':
                    metrics['forward_receiver_bps'] = 0 if case['direction'] == 'reverse' else rate if case['direction'] == 'forward' else rate * .6
                    metrics['reverse_receiver_bps'] = rate - metrics['forward_receiver_bps']
                rows.append({'stage': stage, 'case': case['id'], 'repeat': repeat, 'metrics': metrics})
    switches = []
    for stage in STAGES[1:-1]:
        observations = {}
        for role in ('affected', 'pinned'):
            observations[role] = {}
            for protocol in ('udp', 'tcp'):
                lost = 50 if role == 'affected' else 0
                observations[role][protocol] = {'offered': 2000, 'received': 2000 - lost, 'unanswered': lost,
                    'established_sessions': (2 if role == 'affected' else 1) if protocol == 'tcp' else 0,
                    'disconnects': 1 if role == 'affected' and protocol == 'tcp' else 0, 'max_success_gap_ms': 1100 if role == 'affected' else 21}
        switches.append({'stage': stage, 'result': {'pass': True, 'pinned_flow_preserved': True,
                         'observer': 'sdwan_lab.continuity', 'observations': observations}})
    report = {'status': 'completed', 'pass': True, 'capacity_validated': False, 'cleanup_pass': True,
              'plan_sha256': hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
              'adapter_preflight': {'pass': True, 'scope': 'owned-isolated-lab', 'source_matches_plan': True,
                                   'generator_calibration_pass': True, 'cps_source_pool_validated': True,
                                   'dut_vcpu': 1, 'dut_memory_mib': 1024},
              'restoration': {'pass': True, 'verified': True, 'backing_chain_unchanged': True, 'resources_released': True},
              'runs': rows, 'switching': switches,
              'baseline_checks': compare_baselines(rows, plan['criteria']['baseline_variation_max_percent'])}
    return report, plan


class ComparisonReportTests(unittest.TestCase):
    def setUp(self):
        self.report, self.plan = fixture()

    def test_aggregates_all_five_repeats_and_preserves_units(self):
        result = summarize(self.report, self.plan)
        self.assertEqual(result['measurement_count'], 150)
        self.assertEqual(len(result['measurements']), 30)
        self.assertEqual(len(result['switching']), 12)
        row = next(row for row in result['measurements'] if row['case'] == 'tcp-forward' and row['stage'] == 'container')
        self.assertEqual(row['receiver_rate_median'], 20000000)
        self.assertEqual(row['dut_cpu_mean_percent_median'], 12)
        self.assertEqual(row['dut_cpu_p95_percent_max'], 24)
        self.assertEqual(row['dut_memory_free_min_bytes'], 1048576)
        self.assertEqual(row['container_memory_peak_bytes'], 1004)
        self.assertFalse(result['capacity_validated'])
        self.assertEqual(result['dut_allocation'], {'dut_vcpu': 1, 'dut_memory_mib': 1024})
        self.assertEqual({row['rate_unit'] for row in result['measurements']}, {'bps', 'pps', 'cps'})

    def test_distinct_bidir_counters_are_retained_and_summed(self):
        result = summarize(self.report, self.plan)
        row = next(row for row in result['measurements'] if row['case'] == 'tcp-bidir')
        self.assertEqual(row['forward_receiver_bps_median'], 12000000)
        self.assertEqual(row['reverse_receiver_bps_median'], 8000000)
        self.assertEqual(row['offered_rate_per_direction'], 20000000)
        self.assertEqual(row['offered_rate_total'], 40000000)
        self.report['runs'][0]['metrics']['reverse_receiver_bps'] = 1
        with self.assertRaisesRegex(ValueError, 'add up'): summarize(self.report, self.plan)

    def test_unavailable_write_counters_never_become_zero(self):
        self.report['runs'][0]['metrics']['write_sectors_delta'] = None
        result = summarize(self.report, self.plan)
        row = result['measurements'][0]
        self.assertIsNone(row['write_sectors_delta_median'])
        self.assertEqual(row['write_counter_known_samples'], 4)
        self.assertEqual(result['measurements'][1]['write_sectors_delta_median'], 0)
        self.assertIn('неизвестно', markdown(result, 'ru'))
        self.assertIn('unknown', markdown(result, 'en'))

    def test_missing_duplicate_and_boolean_repeats_are_rejected(self):
        variants = [self.report['runs'][:-1], [self.report['runs'][0]] * 150]
        for rows in variants:
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError): summarize(dict(self.report, runs=rows), self.plan)
        self.report['runs'][0]['repeat'] = False
        with self.assertRaisesRegex(ValueError, 'repeat'): summarize(self.report, self.plan)

    def test_failed_incomplete_and_unrestored_reports_are_rejected(self):
        for patch in ({'status': 'measuring'}, {'pass': False}, {'cleanup_pass': False}, {'capacity_validated': True},
                      {'restoration': dict(self.report['restoration'], verified=False)}):
            with self.subTest(patch=patch), self.assertRaises(ValueError): summarize(dict(self.report, **patch), self.plan)

    def test_plan_binding_and_full_matrix_shape_are_required(self):
        plan = copy.deepcopy(self.plan); plan['seconds'] += 1
        with self.assertRaisesRegex(ValueError, 'match'): summarize(self.report, plan)
        plan = copy.deepcopy(self.plan); plan['repeats'] = 3
        with self.assertRaisesRegex(ValueError, '150'): summarize(self.report, plan)
        plan = copy.deepcopy(self.plan); plan['bindings']['controller_source_sha256'] = 'invalid'
        self.report['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, 'pin'): summarize(self.report, plan)

    def test_rate_units_observed_mode_and_nonfinite_metrics_fail(self):
        for patch in ({'rate_unit': 'pps'}, {'observed_mode': 'wrong'}, {'receiver_rate': float('nan')},
                      {'dut_cpu_p95_percent': float('inf')}, {'write_sectors_delta': -1}):
            report = copy.deepcopy(self.report); report['runs'][0]['metrics'].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError): summarize(report, self.plan)

    def test_generator_and_host_reserve_remain_acceptance_gates(self):
        for patch in ({'generator_cpu_p95_max_percent': 80.01}, {'host_steal_p95_percent': 2.01}):
            report = copy.deepcopy(self.report); report['runs'][0]['metrics'].update(patch)
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, 'reserve'): summarize(report, self.plan)

    def test_baseline_drift_is_recomputed_even_if_stored_pass_is_forged(self):
        for row in self.report['runs']:
            if row['stage'] == 'baseline-after' and row['case'] == 'tcp-forward':
                for key in ('receiver_rate', 'forward_receiver_bps'): row['metrics'][key] *= 2
        with self.assertRaisesRegex(ValueError, 'drift'): summarize(self.report, self.plan)
        self.report, _ = fixture(); self.report['baseline_checks'] = []
        with self.assertRaisesRegex(ValueError, 'Stored'): summarize(self.report, self.plan)

    def test_simulation_flags_cannot_be_exported_as_actual_measurements(self):
        for location in ('report', 'preflight', 'restoration', 'measurement', 'switching'):
            report = copy.deepcopy(self.report)
            target = {'report': report, 'preflight': report['adapter_preflight'], 'restoration': report['restoration'],
                      'measurement': report['runs'][0]['metrics'], 'switching': report['switching'][0]['result']}[location]
            target['simulation'] = True
            with self.subTest(location=location), self.assertRaises(ValueError): summarize(report, self.plan)

    def test_switching_requires_all_modes_and_preserves_the_pinned_flow(self):
        with self.assertRaisesRegex(ValueError, 'Three'): summarize(dict(self.report, switching=self.report['switching'][:2]), self.plan)
        for protocol, changes in [('udp', {'received': 1999, 'unanswered': 1}), ('tcp', {'established_sessions': 2, 'disconnects': 1})]:
            report = copy.deepcopy(self.report); report['switching'][0]['result']['observations']['pinned'][protocol].update(changes)
            with self.subTest(protocol=protocol), self.assertRaisesRegex(ValueError, 'Pinned'): summarize(report, self.plan)

    def test_gap_is_optional_but_counters_must_be_consistent(self):
        row = self.report['switching'][0]['result']['observations']['affected']['udp']; row['max_success_gap_ms'] = None
        self.assertIn('unknown', markdown(summarize(self.report, self.plan), 'en'))
        row['received'] -= 1
        with self.assertRaisesRegex(ValueError, 'add up'): summarize(self.report, self.plan)

    def test_only_allowlisted_data_is_exported_and_inputs_are_preserved(self):
        marker = 'PRIVATE_OWNER_VALUE_MUST_NOT_APPEAR'
        self.report['private_data'] = {'password': marker}; self.report['restoration']['backing_chain'] = [{'path': marker}]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); report_path = root / 'report.json'; plan_path = root / 'plan.json'
            report_raw = json.dumps(self.report, indent=1).encode(); plan_raw = json.dumps(self.plan, indent=3).encode()
            report_path.write_bytes(report_raw); plan_path.write_bytes(plan_raw)
            summary = export(report_path, plan_path, root / 'summary')
            self.assertEqual(summary['provenance']['report_file_sha256'], hashlib.sha256(report_raw).hexdigest())
            self.assertEqual(summary['provenance']['plan_file_sha256'], hashlib.sha256(plan_raw).hexdigest())
            self.assertEqual(report_path.read_bytes(), report_raw); self.assertEqual(plan_path.read_bytes(), plan_raw)
            self.assertEqual({path.name for path in (root / 'summary').iterdir()}, {'summary.json', 'summary.ru.md', 'summary.en.md', 'measurements.csv'})
            for path in (root / 'summary').iterdir(): self.assertNotIn(marker, path.read_text())
            with (root / 'summary/measurements.csv').open(newline='') as stream: self.assertEqual(len(list(csv.DictReader(stream))), 30)
            with self.assertRaises(FileExistsError): export(report_path, plan_path, root / 'summary')

    def test_failed_validation_creates_no_output_directory(self):
        self.report['pass'] = False
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'report.json').write_text(json.dumps(self.report)); (root / 'plan.json').write_text(json.dumps(self.plan))
            with self.assertRaises(ValueError): export(root / 'report.json', root / 'plan.json', root / 'output')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()
