from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_policy_snapshot import test_source

ROOT = Path(__file__).resolve().parents[2]


class NativeSnapshotBuilderTests(unittest.TestCase):
    def test_actual_helpers_are_used_without_live_menu_queries(self):
        generated = test_source(ROOT)
        self.assertIn(':local indexManaged do={', generated)
        self.assertIn(':local requireManaged do={', generated)
        self.assertIn('sdwanSnapshotSelfTestJSON', generated)
        self.assertIn('"pass"=false', generated)
        self.assertNotIn('/ip/route/', generated)
        self.assertNotIn('/ip/firewall/', generated)
        self.assertNotIn('/file/', generated)

    def fixture(self, directory, source):
        root = Path(directory)
        (root / 'native').mkdir()
        (root / 'native/sdwan-controller.rsc').write_text(source)
        (root / 'tests').mkdir()
        (root / 'tests/native_policy_snapshot_cases.rsc').write_text(':error "sentinel"\n')
        return root

    def test_removed_boundary_requires_review_instead_of_stale_helper_copy(self):
        source = (ROOT / 'native/sdwan-controller.rsc').read_text().replace(':local indexManaged do={', ':local renamed do={')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'boundaries changed'):
                test_source(self.fixture(directory, source))

    def test_ambiguous_boundary_is_rejected(self):
        source = (ROOT / 'native/sdwan-controller.rsc').read_text() + '\n    :local requireManaged do={\n'
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'boundaries changed'):
                test_source(self.fixture(directory, source))

    def test_reordered_boundaries_are_rejected(self):
        source = '    :local policyRoutes \n    :local indexManaged do={\n    :local requireManaged do={\n    :local defaultAdmissionClosed false\n'
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'order changed'):
                test_source(self.fixture(directory, source))

    def test_missing_cases_cannot_produce_a_passing_empty_test(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory, (ROOT / 'native/sdwan-controller.rsc').read_text())
            (root / 'tests/native_policy_snapshot_cases.rsc').unlink()
            with self.assertRaises(FileNotFoundError):
                test_source(root)


if __name__ == '__main__':
    unittest.main()
