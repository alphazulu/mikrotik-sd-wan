import unittest
from unittest.mock import Mock
from sdwan.router import Router


class RouterFileTests(unittest.TestCase):
    def router(self, replies, prefix=''):
        router = Router.__new__(Router)
        router._prefix = prefix
        router.call = Mock(side_effect=replies)
        return router

    def test_read_sends_exact_name_query(self):
        r = self.router([[{'.id': '*1', 'name': 'config.json'}], {'ret': 'payload'}])
        self.assertEqual(r.read_file('config.json'), 'payload')
        self.assertEqual(r.call.call_args_list[0].args,
                         ('file/print', {'.proplist': '.id,name', '.query': ['name=config.json']}, 'POST'))

    def test_flash_precedes_root_even_when_rows_are_reversed(self):
        r = self.router([[{'.id': '*1', 'name': 'config.json'}, {'.id': '*2', 'name': 'flash/config.json'}], {'ret': 'flash'}], 'flash/')
        self.assertEqual(r.read_file('config.json'), 'flash')
        self.assertEqual(r.call.call_args_list[0].args[1]['.query'], ['name=flash/config.json', 'name=config.json', '#|'])
        self.assertEqual(r.call.call_args_list[1].args[1]['number'], '*2')

    def test_flash_detection_is_filtered_and_cached(self):
        r = self.router([[{'name': 'flash', 'type': 'directory'}]], None)
        self.assertEqual(r.storage_prefix, 'flash/')
        self.assertEqual(r.storage_prefix, 'flash/')
        r.call.assert_called_once_with('file/print', {'.proplist': 'name,type', '.query': ['name=flash']}, 'POST')

    def test_missing_file_does_not_request_other_contents(self):
        r = self.router([[]])
        with self.assertRaisesRegex(ValueError, 'Router file not found: missing'):
            r.read_file('missing')
        self.assertEqual(r.call.call_count, 1)

    def test_ambiguous_name_is_rejected(self):
        r = self.router([[{'.id': '*1', 'name': 'f'}, {'.id': '*2', 'name': 'f'}]])
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous'):
            r.read_file('f')

    def test_identical_upload_does_not_write(self):
        r = self.router([[{'.id': '*1', 'name': 'f'}], {'ret': 'same'}])
        self.assertFalse(r.upload('f', 'same'))
        self.assertEqual(r.call.call_count, 2)

    def test_changed_upload_sets_existing_file(self):
        r = self.router([[{'.id': '*1', 'name': 'f'}], {'ret': 'old'}, None])
        self.assertTrue(r.upload('f', 'new'))
        self.assertEqual(r.call.call_args_list[-1].args, ('file/*1', {'contents': 'new'}, 'PATCH'))

    def test_new_file_is_created_empty_before_setting_secret(self):
        r = self.router([[], None, [{'.id': '*1', 'name': 'dir/f'}], None])
        self.assertTrue(r.upload('dir/f', 'synthetic-value'))
        self.assertEqual(r.call.call_args_list[1].args, ('file', {'name': 'dir/f', 'type': 'file'}, 'PUT'))
        self.assertEqual(r.call.call_args_list[-1].args, ('file/*1', {'contents': 'synthetic-value'}, 'PATCH'))

    def test_exact_flash_write_never_overwrites_root_fallback(self):
        r = self.router([[], None, [{'.id': '*2', 'name': 'flash/f'}], None], 'flash/')
        r.upload('f', 'new')
        self.assertEqual(r.call.call_args_list[0].args[1]['.query'], ['name=flash/f'])

    def test_failed_creation_is_bounded(self):
        r = self.router([[], None, []])
        with self.assertRaisesRegex(RuntimeError, 'not visible'):
            r.upload('f', 'new')
        self.assertEqual(r.call.call_count, 3)
