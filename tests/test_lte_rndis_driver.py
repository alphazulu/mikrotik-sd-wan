"""Fault injection and ownership checks must fail before an acceptance claim."""
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

if os.name!='nt':
    from lte_rndis_acceptance import Fixture


@unittest.skipIf(os.name=='nt','The isolated QEMU fixture requires POSIX locks')
class RNDISDriverGuards(unittest.TestCase):
    def fixture(self):return Fixture(Path('/nonexistent/sdwan-test'))
    def test_gate_sends_actual_mutable_field_and_checks_data_plane(self):
        fixture=self.fixture()
        response=io.BytesIO(json.dumps({'registration_status':'searching','gate':True,'forwarding':False}).encode())
        with patch('lte_rndis_acceptance.urllib.request.urlopen',return_value=response) as open_:
            self.assertFalse(fixture.gate('searching')['forwarding'])
        request=open_.call_args.args[0]
        self.assertEqual(request.full_url,'http://127.0.0.1:24321/lte')
        self.assertEqual(json.loads(request.data),{'registration_status':'searching'})
    def test_ignored_or_ineffective_fault_is_rejected(self):
        for state,gate,forwarding in [('registered',True,True),('searching',False,False),('searching',True,True)]:
            response=io.BytesIO(json.dumps({'registration_status':state,'gate':gate,'forwarding':forwarding}).encode())
            with patch('lte_rndis_acceptance.urllib.request.urlopen',return_value=response):
                with self.assertRaises(AssertionError):self.fixture().gate('searching')
    def test_rejected_ownership_never_rolls_back_an_existing_router(self):
        fixture=self.fixture();router=Mock();fixture.routers={'x86':router}
        with patch.object(fixture,'gate') as gate,patch.object(fixture,'rollback') as rollback:
            fixture.close()
        gate.assert_not_called();rollback.assert_not_called();router.call.assert_not_called();router.close.assert_called_once()
        self.assertFalse(fixture.report['cleanup']['mutation_started'])
    def test_failed_rollback_keeps_recovery_baseline_and_managed_apn(self):
        fixture=self.fixture();fixture.cleanup_armed=True;fixture.applied=True
        fixture.a=Mock();fixture.c=Mock();fixture.c.call.return_value=[]
        fixture.routers={'x86':fixture.a,'chr':fixture.c};fixture.lock=Mock()
        fixture.created=[(fixture.a,'interface/lte/apn','*1')]
        fixture.restore=[(fixture.a,'interface/lte','*2',{'apn-profiles':'original'})]
        with patch.object(fixture,'gate'),patch.object(fixture,'rollback',side_effect=RuntimeError('rollback failed')):
            fixture.close()
        fixture.a.call.assert_not_called()
        self.assertFalse(fixture.report['pass'])
        self.assertTrue(fixture.report['cleanup']['baseline_preserved'])
        self.assertTrue(fixture.report['cleanup']['recovery_required'])


if __name__=='__main__':unittest.main()
