"""Benchmark failure handling must preserve a recoverable router state."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

if os.name!='nt':
    from tools.performance_lab import Benchmark


@unittest.skipIf(os.name=='nt','Owned QEMU benchmark uses POSIX locks')
class BenchmarkGuards(unittest.TestCase):
    def test_cleanup_enumerates_actual_ids_and_verifies_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Benchmark(Path(tmp));router=Mock();b.a=router;b.created=[('ip/address','*A')]
            router.call.side_effect=lambda path,data=None,method=None: ([{'.id':'*A'}] if path=='ip/address/print' and data=={'.proplist':'.id'} else [])
            b.close()
            router.call.assert_any_call('ip/address/*A',method='DELETE')
            self.assertTrue(b.report['cleanup']['pass'])

    def test_residual_fixture_prevents_false_cleanup_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Benchmark(Path(tmp));router=Mock();b.a=router
            b.created=[('ip/address','*A')]
            router.call.return_value=[{'.id':'*A','comment':'sdwan-perf-fixture'}]
            b.close()
            self.assertFalse(b.report['cleanup']['pass'])

    def test_failed_product_rollback_keeps_topology_and_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Benchmark(Path(tmp));b.a=Mock();b.applied=True;b.topology_changed=True
            b.created=[('ip/address','*1')];b.changed=[('interface/lte','*2',{'disabled':'false'})]
            with patch.object(b,'rollback',side_effect=RuntimeError('rollback failed')),patch('tools.performance_lab.stop_vm') as stop:
                b.close()
            b.a.call.assert_not_called();stop.assert_not_called()
            self.assertTrue(b.report['cleanup']['baseline_preserved'])
            self.assertFalse(b.report['cleanup']['pass'])

    def test_unstarted_fixture_never_mutates_router_or_stops_vm(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Benchmark(Path(tmp));b.a=Mock();router=b.a
            with patch('tools.performance_lab.stop_vm') as stop:b.close()
            router.call.assert_not_called()
            stop.assert_not_called();self.assertTrue(b.report['cleanup']['pass'])

    def test_pinned_backend_failure_precedes_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            b=Benchmark(Path(tmp));b.cfg={};b.a=Mock();b.cli=Mock()
            path=b.lte/'runtime/sdwan-container-test-config.json';path.parent.mkdir(parents=True);path.write_text('{"container":{}}')
            b.a.call.return_value=[{'name':'sdwan-container-controller','image-id':'wrong-image'}]
            with self.assertRaisesRegex(ValueError,'pinned'):b.apply('container')
            b.cli.apply.assert_not_called();self.assertFalse(b.applied)


if __name__=='__main__':unittest.main()
