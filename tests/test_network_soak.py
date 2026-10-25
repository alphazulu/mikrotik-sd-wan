"""Offline safety checks for the CHR-only long-running observer."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if sys.platform == 'win32':
    soak = None
else:
    import fcntl
    spec = importlib.util.spec_from_file_location('network_soak', ROOT / 'tools/network_soak.py')
    soak = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(soak)


@unittest.skipIf(soak is None, 'CHR soak uses POSIX locks on Linux/WSL')
class NetworkSoakSafety(unittest.TestCase):
    def invoke(self, root, *arguments):
        with patch.object(sys, 'argv', ['network_soak.py', *arguments, '--lab-root', str(root)]):
            soak.main()

    def test_short_window_cannot_claim_release_soak(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(soak, 'VPNLab') as lab:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.invoke(Path(folder), 'run', '--hours', '1')
            lab.assert_not_called()
            self.assertFalse((Path(folder) / 'runtime').exists())

    def test_tcp_handles_can_change_but_tuple_policy_and_counters_must_survive(self):
        baseline = {'.id': '*1', 'src-address': '192.0.2.1', 'src-port': '50000', 'dst-address': '198.51.100.1', 'dst-port': '80', 'reply-src-address': '198.51.100.1', 'reply-src-port': '80', 'reply-dst-address': '192.0.2.2', 'reply-dst-port': '50000', 'connection-mark': 'sdwan-out-default:wan1', 'orig-bytes': '100', 'repl-bytes': '1000', 'tcp-state': 'established', 'seen-reply': 'true'}
        current = dict(baseline, **{'.id': '*99', 'repl-bytes': '2000'})
        self.assertEqual(soak.tcp_stream(baseline, [current])['.id'], '*99')
        for key, value in [('src-port', '50001'), ('reply-dst-address', '192.0.2.3'), ('connection-mark', 'other'), ('repl-bytes', '999'), ('tcp-state', 'closed'), ('seen-reply', 'false')]:
            with self.subTest(field=key), self.assertRaises(AssertionError):
                soak.tcp_stream(baseline, [dict(current, **{key: value})])
        with self.assertRaises(AssertionError):
            soak.tcp_stream(baseline, [current, current])

    def test_existing_process_lock_preserves_report_without_router_access(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(soak, 'VPNLab') as lab:
            root = Path(folder)
            run = root / 'runtime/overlay-lab/runtime'
            run.mkdir(parents=True)
            report = run / 'network-soak.json'
            report.write_text('{"status":"running","samples":73}')
            with (run / 'network-soak.lock').open('a') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    self.invoke(root, 'run')
            self.assertEqual(json.loads(report.read_text()), {'status': 'running', 'samples': 73})
            lab.assert_not_called()

    def test_existing_acceptance_lock_preserves_report_without_router_access(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(soak, 'VPNLab') as lab:
            root = Path(folder)
            run = root / 'runtime/overlay-lab/runtime'
            run.mkdir(parents=True)
            report = run / 'network-soak.json'
            report.write_text('{"status":"not_started"}')
            with (run / 'lab.lock').open('a') as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaises(BlockingIOError):
                    self.invoke(root, 'run')
            self.assertEqual(report.read_text(), '{"status":"not_started"}')
            lab.assert_not_called()

    def test_status_does_not_create_or_start_a_lab(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(soak, 'VPNLab') as lab:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.invoke(Path(folder), 'status')
            self.assertEqual(json.loads(output.getvalue())['status'], 'not_started')
            lab.assert_not_called()
            self.assertFalse((Path(folder) / 'runtime').exists())


if __name__ == '__main__':
    unittest.main()
