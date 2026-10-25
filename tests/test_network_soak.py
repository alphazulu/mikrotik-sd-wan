"""Offline safety checks for the CHR-only long-running observer."""
import contextlib
import fcntl
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('network_soak', ROOT / 'tools/network_soak.py')
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)


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
