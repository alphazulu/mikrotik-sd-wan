"""Payload replacement must wait for native durable preparation evidence."""
import unittest
from unittest.mock import Mock,patch
from sdwan.deployment import _prepared_barrier

class PreparedBarrierTests(unittest.TestCase):
    def test_only_native_readiness_releases_payload(self):
        states=[{'phase':'prepared','backup_ready':False}, {'phase':'prepared','backup_ready':True}]
        with patch('sdwan.deployment.read_state',side_effect=states) as read,patch('sdwan.deployment.time.sleep') as sleep:
            self.assertIs(_prepared_barrier(Mock(),'token','backup_ready','backup'),states[1])
        self.assertEqual(read.call_count,2);sleep.assert_called_once()

    def test_failure_or_phase_change_never_releases_payload(self):
        for phase in ('preparation-failed','recovery-failed','armed','committed',None):
            with self.subTest(phase=phase),patch('sdwan.deployment.read_state',return_value={'phase':phase,'backup_ready':True}):
                with self.assertRaisesRegex(RuntimeError,'payload was not uploaded'):_prepared_barrier(Mock(),'token','backup_ready','backup')

    def test_barrier_is_bounded_and_requires_json_boolean(self):
        for ready in (False,None,'true',1):
            with self.subTest(ready=ready),patch('sdwan.deployment.read_state',return_value={'phase':'prepared','manifest_ready':ready}),patch('sdwan.deployment.time.monotonic',side_effect=[0,60]):
                with self.assertRaisesRegex(RuntimeError,'storage barrier did not complete'):_prepared_barrier(Mock(),'token','manifest_ready','archive')

    def test_other_barrier_cannot_substitute_for_archive_readiness(self):
        with patch('sdwan.deployment.read_state',return_value={'phase':'prepared','backup_ready':True}),patch('sdwan.deployment.time.monotonic',side_effect=[0,60]):
            with self.assertRaises(RuntimeError):_prepared_barrier(Mock(),'token','manifest_ready','archive')

if __name__=='__main__':unittest.main()
