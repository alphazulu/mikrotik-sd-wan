import copy
import json
from pathlib import Path
import unittest
from sdwan.balance import allocation, admission_list, groups, pool_list, validate_budget, validate_policy
from sdwan.config import load, validate
from sdwan.dataplane import objects

ROOT = Path(__file__).resolve().parents[1]


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load(ROOT / 'config/sdwan.json')
        self.p = next(p for p in self.cfg['policies'] if p['name'] == 'client101')
        self.p['wans'] = ['wan1', 'wan2', 'wan3']
        self.p['balance'] = {'weights': {'wan1': 30, 'wan2': 10, 'wan3': 0}}

    def test_native_golden_subsets_cover_two_three_and_four_weighted_WANs(self):
        cases = json.loads((ROOT / 'tests/native_balance_cases.json').read_text())
        self.assertEqual([len(row['groups']) for row in cases['valid']], [3, 7, 15])
        for row in cases['valid']:
            validate_policy(row['policy'])
            self.assertEqual(groups(row['policy']), row['groups'])
        for policy in cases['invalid']:
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                validate_policy(policy)

    def test_optional_config_keeps_legacy_and_bounds_reserved_list_names(self):
        self.assertIs(validate(self.cfg), self.cfg)
        p = dict(self.p, name='p' * 31, wans=['w' * 31, 'b'])
        self.assertLessEqual(len(admission_list(p, 'w' * 31)), 64)
        self.assertLessEqual(len(pool_list(p, 15)), 64)
        del self.p['balance']; self.assertEqual(groups(self.p), [])
        validate_policy(self.p)

    def test_all_subsets_have_exact_normalized_ratios_and_exclude_reserve(self):
        self.assertEqual(groups(self.p), [{'mask': 1, 'slots': ['wan1']},
                                         {'mask': 2, 'slots': ['wan2']},
                                         {'mask': 3, 'slots': ['wan1', 'wan1', 'wan1', 'wan2']}])

    def test_pool_loss_and_recovery_change_members_without_selecting_reserve(self):
        admit = dict.fromkeys(self.p['wans'], True)
        healthy = dict.fromkeys(self.p['wans'], 'healthy')
        self.assertEqual(allocation(self.p, admit, healthy),
                         {'selected': 'wan1', 'mask': 3, 'active_wans': ['wan1', 'wan2'], 'weights': {'wan1': 3, 'wan2': 1}})
        admit['wan1'] = False
        self.assertEqual(allocation(self.p, admit, healthy)['active_wans'], ['wan2'])
        admit['wan1'] = True
        self.assertEqual(allocation(self.p, admit, healthy)['mask'], 3)

    def test_healthy_reserve_precedes_degraded_pool_and_all_down_closes(self):
        admit = dict.fromkeys(self.p['wans'], True)
        self.p['allow_degraded'] = True
        states = {'wan1': 'degraded', 'wan2': 'down', 'wan3': 'healthy'}
        self.assertEqual(allocation(self.p, admit, states), {'selected': 'wan3', 'mask': 0, 'active_wans': ['wan3'], 'weights': {'wan3': 1}})
        states['wan3'] = 'down'
        self.assertEqual(allocation(self.p, admit, states)['active_wans'], ['wan1'])
        self.p['allow_degraded'] = False
        self.assertEqual(allocation(self.p, admit, states), {'selected': 'none', 'mask': 0, 'active_wans': [], 'weights': {}})

    def test_invalid_contracts_rejected_before_generation(self):
        bad_values = [None, [], {}, {'weights': []}, {'weights': {'wan1': 1}},
                      {'weights': {'wan1': True, 'wan2': 1, 'wan3': 0}},
                      {'weights': {'wan1': -1, 'wan2': 1, 'wan3': 0}},
                      {'weights': {'wan1': 1.5, 'wan2': 1, 'wan3': 0}},
                      {'weights': {'wan1': 101, 'wan2': 1, 'wan3': 0}},
                      {'weights': {'wan1': 100, 'wan2': 1, 'wan3': 0}},
                      {'weights': {'wan1': 0, 'wan2': 1, 'wan3': 1}},
                      {'weights': {'wan1': 1, 'wan2': 0, 'wan3': 0}},
                      dict(self.p['balance'], classifier='random'), dict(self.p['balance'], unknown=True)]
        for value in bad_values:
            with self.subTest(value=value):
                p = copy.deepcopy(self.p); p['balance'] = value
                with self.assertRaises(ValueError): validate_policy(p)
        p = dict(self.p, mode='strict')
        with self.assertRaises(ValueError): validate_policy(p)

    def test_rule_budget_limits_total_and_positive_member_count(self):
        p = dict(self.p, wans=['a', 'b', 'c', 'd'], balance={'weights': {'a': 15, 'b': 13, 'c': 3, 'd': 1}})
        validate_policy(p)
        with self.assertRaisesRegex(ValueError, 'total PCC'):
            validate_budget({'policies': [p] * 10})
        p['wans'].append('e'); p['balance']['weights']['e'] = 1
        with self.assertRaisesRegex(ValueError, 'two to four'): validate_policy(p)
        with self.assertRaisesRegex(ValueError, 'at most four'): groups(p)

    def test_legacy_reference_retains_priority_and_strict_behavior(self):
        del self.p['balance']
        decision = allocation(self.p, {'wan1': True, 'wan2': True}, {'wan1': 'healthy', 'wan2': 'healthy'})
        self.assertEqual(decision['active_wans'], ['wan1']); self.assertEqual(decision['mask'], 0)

    def test_static_layouts_cover_hash_space_and_keep_policy_selectors_at_jump(self):
        self.p['source_list'] = 'Office clients'
        self.p['destination_list'] = 'Selected services'
        self.p['source'] = '0.0.0.0/0'
        self.p['priority'] = 1
        rules = objects(self.cfg)
        jump = rules['ip/firewall/mangle', 'sdwan:v1:policy-jump:client101']
        self.assertEqual((jump['src-address-list'], jump['dst-address-list']), ('Office clients', 'Selected services'))
        entries = [r for (menu, tag), r in rules.items() if tag.startswith('sdwan:v1:pcc:client101:')]
        self.assertEqual(len(entries), 6)
        for mask, denominator in ((1, 1), (2, 1), (3, 4)):
            subset = [r for r in entries if r['src-address-list'] == pool_list(self.p, mask)]
            self.assertEqual({r['per-connection-classifier'] for r in subset},
                             {f'both-addresses-and-ports:{denominator}/{i}' for i in range(denominator)})
            self.assertTrue(all(r['connection-mark'] == 'no-mark' for r in subset))
            self.assertTrue(all('wan3' not in r['new-connection-mark'] for r in subset))
        flow = rules['ip/firewall/mangle', 'sdwan:v1:flow:sdwan-pre:client101:wan2']
        self.assertEqual(flow['new-routing-mark'], 'sdwan-probe-wan2')
        self.assertEqual(flow['connection-mark'], 'sdwan-out-client101:wan2')


if __name__ == '__main__': unittest.main()
