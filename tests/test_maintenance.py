import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sdwan.maintenance import backup_plan, prune_backups, require_backup_space
from sdwan.config import load, validate


class Files:
    def __init__(self):
        self.rows = []
        self.states = {}
        self.removed = []
        for index, letter in enumerate('abc', 1):
            token = letter * 24
            self.states[token] = {'token': token, 'identity': 'edge', 'phase': 'committed', 'backup_ready': True, 'previous': {}}
            for suffix in ('txn-' + token + '.json', 'before-' + token + '.backup', 'prev-' + token + '-0', 'infra-prev-' + token + '-0'):
                self.rows.append({'.id': '*' + str(len(self.rows)), 'name': 'sdwan-' + suffix,
                                  'size': '100', 'last-modified': f'2026-10-0{index} 10:00:00'})
        self.current = copy.deepcopy(self.states['a' * 24])
        self.rows.append({'.id': '*unrelated', 'name': 'customer.backup', 'size': '100'})
        self.rows.append({'.id': '*orphan', 'name': 'sdwan-before-' + 'd' * 24 + '.backup', 'size': '100'})

    def call(self, path, data=None, method=None):
        if path == 'system/identity': return {'name': 'edge'}
        if path == 'file/print': return copy.deepcopy(self.rows)
        if path == 'file/get':
            row = next(r for r in self.rows if r['.id'] == data['number'])
            token = row['name'].removeprefix('sdwan-txn-').removesuffix('.json')
            return {'ret': json.dumps(self.states[token])}
        if method == 'DELETE':
            row = next(r for r in self.rows if 'file/' + r['.id'] == path)
            self.removed.append(row['name']); self.rows.remove(row); return
        raise AssertionError(path)

    def file_records(self, names):
        return [copy.deepcopy(r) for r in self.rows if r['name'] in names]


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.r = Files()
        self.pointer = patch('sdwan.maintenance.read_state', side_effect=lambda r: r.current)
        self.pointer.start(); self.addCleanup(self.pointer.stop)

    def test_plan_is_read_only_and_preserves_current_latest_and_unrelated(self):
        plan = prune_backups(self.r, 'edge', 1)
        self.assertFalse(plan['blocked']); self.assertEqual(len(plan['delete']), 4)
        self.assertTrue(all(row['token'] == 'b' * 24 for row in plan['delete']))
        self.assertEqual(self.r.removed, [])

    def test_execute_removes_only_obsolete_group_journal_last(self):
        result = prune_backups(self.r, 'edge', 1, execute=True)
        self.assertEqual(result['removed_files'], 4)
        self.assertEqual(self.r.removed[-1], 'sdwan-txn-' + 'b' * 24 + '.json')
        self.assertIn('customer.backup', [r['name'] for r in self.r.rows])

    def test_kept_manifest_dependency_protects_old_group(self):
        self.r.states['a' * 24]['previous'] = {'f': 'sdwan-prev-' + 'b' * 24 + '-0'}
        self.assertEqual(backup_plan(self.r, 'edge', 1)['delete'], [])

    def test_pending_or_failed_recovery_blocks_all_deletion(self):
        for phase in ('applying', 'prepared', 'restore-reboot', 'recovery-failed'):
            self.r.states['b' * 24]['phase'] = phase
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, 'blocked'):
                prune_backups(self.r, 'edge', 1, execute=True)
        self.assertEqual(self.r.removed, [])

    def test_journal_identity_mismatch_blocks_cleanup(self):
        self.r.states['b' * 24]['identity'] = 'other'
        self.assertTrue(backup_plan(self.r, 'edge', 1)['blocked'])

    def test_unknown_date_is_preserved(self):
        for row in self.r.rows:
            if row['name'] == 'sdwan-txn-' + 'b' * 24 + '.json':row.pop('last-modified')
        self.assertEqual(backup_plan(self.r, 'edge', 1)['delete'], [])

    def test_changed_deployment_aborts_before_delete(self):
        with patch('sdwan.maintenance.read_state', side_effect=[self.r.current, self.r.states['c' * 24]]):
            with self.assertRaisesRegex(RuntimeError, 'Deployment changed'):
                prune_backups(self.r, 'edge', 1, execute=True)
        self.assertEqual(self.r.removed, [])

    def test_failed_preparation_does_not_displace_real_backup(self):
        self.r.states['c' * 24].update(phase='preparation-failed', backup_ready=False)
        plan = backup_plan(self.r, 'edge', 1)
        self.assertIn('b' * 24, plan['protected_tokens'])
        self.assertTrue(all(row['token'] == 'c' * 24 for row in plan['delete']))

    def test_rebound_file_id_is_not_deleted(self):
        original = self.r.file_records
        self.r.file_records = lambda names: [dict(row, **{'.id': '*changed'}) for row in original(names)]
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            prune_backups(self.r, 'edge', 1, execute=True)
        self.assertEqual(self.r.removed, [])

    def test_wrong_router_or_invalid_keep_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            backup_plan(self.r, 'other', 1)
        for keep in (0, 21, True):
            with self.assertRaises(ValueError):backup_plan(self.r, 'edge', keep)

    def test_not_enough_space_fails_before_any_write(self):
        class Resource:
            def call(self, path):
                if path != 'system/resource':raise AssertionError(path)
                return {'free-hdd-space': '100'}
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'payload').write_text('sample')
            with self.assertRaisesRegex(ValueError, 'Not enough'):
                require_backup_space(Resource(), directory)


class MaintenanceConfigTests(unittest.TestCase):
    def test_legacy_config_does_not_enable_cleanup(self):
        cfg = load(Path(__file__).resolve().parents[1] / 'config/sdwan.json')
        self.assertNotIn('maintenance', cfg)

    def test_retention_is_explicit_and_bounded(self):
        cfg = load(Path(__file__).resolve().parents[1] / 'config/sdwan.json')
        cfg['maintenance'] = {'backup_keep': 3}
        validate(cfg)
        for value in (0, 21, True, '3'):
            cfg['maintenance']['backup_keep'] = value
            with self.assertRaises(ValueError): validate(cfg)

    def test_unknown_maintenance_fields_are_rejected(self):
        cfg = load(Path(__file__).resolve().parents[1] / 'config/sdwan.json')
        cfg['maintenance'] = {'backup_keep': 3, 'delete_anything': True}
        with self.assertRaises(ValueError): validate(cfg)
