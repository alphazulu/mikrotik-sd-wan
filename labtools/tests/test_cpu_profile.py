import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cpu_profile import summarize_profile, usage


def fixture():
    rows = [(str(section), name, value) for section, name, value in
            [(0, 'total', '0'), (1, 'total', '0'), (2, 'console', '20'),
             (2, 'firewall', '10'), (2, 'total', '30'), (3, 'firewall', '10'),
             (3, 'total', '10'), (4, 'total', '0')]]
    return {'pass': True, 'started_monotonic': 10.0, 'finished_monotonic': 15.0,
            'raw': [{'.section': section, 'name': name, 'usage': value} for section, name, value in rows]}


class ProfileTests(unittest.TestCase):
    def test_warmup_is_excluded_and_valid_idle_frames_are_retained(self):
        record = fixture(); before = copy.deepcopy(record)
        result = summarize_profile(record)
        self.assertEqual(result['warmup_frames_skipped'], 2)
        self.assertEqual(result['frames_used'], 3)
        self.assertAlmostEqual(result['classifiers']['total']['mean_percent'], 40 / 3)
        self.assertAlmostEqual(result['classifiers']['console']['mean_percent'], 20 / 3)
        self.assertEqual(result['classifiers']['console']['p95_percent'], 20)
        self.assertEqual(record, before)

    def test_missing_invalid_or_failed_observations_never_become_zero_CPU(self):
        for mutate in (lambda x:x.update(pass_=False), lambda x:x.update(raw=[]),
                       lambda x:x.update(raw=x['raw'][:2]), lambda x:x.update(finished_monotonic=9)):
            record = fixture(); mutate(record)
            if 'pass_' in record: record['pass'] = record.pop('pass_')
            with self.assertRaises(ValueError): summarize_profile(record)

    def test_bad_usage_values_are_rejected(self):
        for value in (True, None, -1, 101, float('nan'), float('inf'), 'NaN', 'invalid', '1e3'):
            with self.subTest(value=value), self.assertRaises(ValueError): usage(value)
        self.assertEqual(usage('12.5%'), 12.5)
        self.assertEqual(usage('0'), 0)

    def test_duplicate_missing_and_out_of_order_frames_are_rejected(self):
        for kind in ('duplicate', 'missing', 'order', 'total', 'section'):
            record = fixture()
            if kind == 'duplicate': record['raw'].append(dict(record['raw'][-1]))
            elif kind == 'missing': record['raw'] = [r for r in record['raw'] if r['.section'] != '3']
            elif kind == 'order': record['raw'][0], record['raw'][-1] = record['raw'][-1], record['raw'][0]
            elif kind == 'total': record['raw'] = [r for r in record['raw'] if not (r['.section'] == '2' and r['name'] == 'total')]
            else: record['raw'][0].pop('.section')
            with self.subTest(kind=kind), self.assertRaises(ValueError): summarize_profile(record)

    def test_invalid_rows_and_classifier_labels_are_rejected(self):
        for value in (None, {'name':'total','usage':'0'}, {'.section':'0','name':'private label','usage':'0'}):
            record = fixture();record['raw'][0] = value
            with self.assertRaises(ValueError):summarize_profile(record)


if __name__ == '__main__':
    unittest.main()
