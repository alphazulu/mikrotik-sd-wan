"""Release retries must preserve reviewed bytes and human-written notes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publisher', ROOT / 'tools/publish_release.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class ReleasePublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.data = {name: ('fixture:' + name).encode() for name in publisher.NAMES - {'SHA256SUMS', 'build-report.json'}}
        self.data['build-report.json'] = json.dumps([{'version': '0.3.0'}] * 6).encode()
        self.data['SHA256SUMS'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                         for name, data in sorted(self.data.items())).encode()
        for name, data in self.data.items():
            (self.directory / name).write_bytes(data)
        self.release = {'tag_name': 'v0.3.0', 'draft': False, 'body': 'Human RU/EN notes',
                        'assets': [{'name': name, 'size': len(data)} for name, data in self.data.items()]}
        self.commands = []
        self.missing = False
        self.lookup_error = None
        self.corrupt = False
        self.download_error = False

    def run_gh(self, command):
        self.commands.append(command)
        if command[0] == 'api':
            if self.lookup_error:
                return subprocess.CompletedProcess(command, 1, '', self.lookup_error)
            if self.missing:
                return subprocess.CompletedProcess(command, 1, '', 'gh: Not Found (HTTP 404)')
            return subprocess.CompletedProcess(command, 0, json.dumps(self.release), '')
        if command[:2] == ['release', 'create']:
            self.missing = False
            # Simulates another publisher winning the race without overwriting its notes.
            return subprocess.CompletedProcess(command, 1, '', 'already exists')
        if command[:2] == ['release', 'download']:
            if self.download_error:
                return subprocess.CompletedProcess(command, 1, '', 'download failed')
            output = Path(command[command.index('--dir') + 1])
            for name, data in self.data.items():
                (output / name).write_bytes(data)
            if self.corrupt:
                name = 'sdwan-controller-amd64.tar.gz'
                data = (output / name).read_bytes()
                (output / name).write_bytes(b'X' + data[1:])  # Same size, wrong content.
            return subprocess.CompletedProcess(command, 0, '', '')
        self.fail('Unexpected mutation: ' + repr(command))

    def invoke(self):
        return publisher.publish(self.directory, 'example/sdwan', 'v0.3.0', self.run_gh)

    def test_existing_release_is_downloaded_and_verified_without_recreation(self):
        result = self.invoke()
        self.assertEqual(result['action'], 'verified-existing')
        self.assertFalse(result['existing_notes_or_assets_overwritten'])
        self.assertFalse(any(c[:2] == ['release', 'create'] for c in self.commands))
        self.assertEqual(self.release['body'], 'Human RU/EN notes')

    def test_concurrent_creation_is_accepted_only_after_actual_byte_verification(self):
        self.missing = True
        self.assertTrue(self.invoke()['pass'])
        self.assertIn('--verify-tag', self.commands[1])
        self.assertTrue(any(c[:2] == ['release', 'download'] for c in self.commands))

    def test_network_and_permission_errors_do_not_attempt_publication(self):
        for error in ('timeout', 'gh: Forbidden (HTTP 403)'):
            self.commands.clear(); self.lookup_error = error
            with self.assertRaisesRegex(RuntimeError, 'no publication'):
                self.invoke()
            self.assertEqual(len(self.commands), 1)

    def test_missing_extra_and_duplicate_remote_assets_are_rejected(self):
        original = self.release['assets']
        for assets in (original[:-1], original + [original[0]], original[:-1] + [original[0]]):
            self.release['assets'] = assets
            with self.assertRaisesRegex(ValueError, 'asset set'):
                self.invoke()

    def test_remote_size_and_same_size_content_changes_are_rejected(self):
        self.release['assets'][0]['size'] += 1
        with self.assertRaisesRegex(ValueError, 'size'):
            self.invoke()
        self.release['assets'][0]['size'] -= 1
        self.corrupt = True
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.invoke()

    def test_draft_wrong_tag_and_failed_download_are_not_success(self):
        for key, value in (('draft', True), ('tag_name', 'v0.2.0')):
            old = self.release[key]; self.release[key] = value
            with self.assertRaises(RuntimeError):
                self.invoke()
            self.release[key] = old
        self.download_error = True
        with self.assertRaisesRegex(RuntimeError, 'download'):
            self.invoke()

    def test_local_corruption_extra_files_and_checksum_traversal_fail_before_network(self):
        name = 'sdwan-controller-amd64.tar.gz'
        (self.directory / name).write_bytes(b'bad')
        with self.assertRaises(ValueError):
            self.invoke()
        (self.directory / name).write_bytes(self.data[name])
        extra = self.directory / 'private.backup'; extra.write_bytes(b'private fixture')
        with self.assertRaises(ValueError):
            self.invoke()
        extra.unlink()
        (self.directory / 'SHA256SUMS').write_text('a' * 64 + '  ../outside\n')
        with self.assertRaises(ValueError):
            self.invoke()
        self.assertFalse(self.commands)


if __name__ == '__main__':
    unittest.main()
