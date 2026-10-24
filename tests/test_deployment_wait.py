import itertools,json,unittest
from unittest.mock import patch
from sdwan.deployment import wait


class RouterFixture:
    def __init__(self,sequence):self.sequence=iter(sequence);self.last=None;self.close_calls=0;self.paths=[]
    def read_file(self,path):
        self.paths.append(path)
        try:self.last=next(self.sequence)
        except StopIteration:pass
        if isinstance(self.last,Exception):raise self.last
        return json.dumps(self.last)
    def close(self):self.close_calls+=1
    def upload(self,*args):raise AssertionError('Read-only recovery wait must not write')
    def fresh(self):raise AssertionError('No confirmation while restoring')


class DeploymentWaitTests(unittest.TestCase):
    def run_wait(self,router):
        with patch('sdwan.deployment.time.monotonic',side_effect=itertools.count()),patch('sdwan.deployment.time.sleep'):
            return wait(router,'fixture','sdwan-edge',timeout=30)
    def test_restore_wait_survives_missing_or_incomplete_journal(self):
        r=RouterFixture([{'phase':'restoring'},ValueError('Router file not found: sdwan-txn-fixture.json'),json.JSONDecodeError('boot read not ready','',0),{'phase':'rolled-back','error':'injected error'}])
        with self.assertRaisesRegex(RuntimeError,'rolled-back: injected error'):self.run_wait(r)
        self.assertEqual(r.close_calls,2);self.assertEqual(set(r.paths),{'sdwan-txn-fixture.json'})
    def test_unrelated_value_error_is_not_hidden(self):
        r=RouterFixture([ValueError('Router file not found: another-file.json')])
        with self.assertRaisesRegex(ValueError,'another-file'):self.run_wait(r)
        self.assertEqual(r.close_calls,0)
    def test_missing_journal_still_has_a_bounded_deadline(self):
        r=RouterFixture([ValueError('Router file not found: sdwan-txn-fixture.json')])
        with self.assertRaisesRegex(RuntimeError,'Deployment status unavailable'):self.run_wait(r)
        self.assertGreater(r.close_calls,0)
    def test_fresh_confirmation_waits_for_container_lease(self):
        r=RouterFixture([{'phase':'await-confirm','revision':'fixture','default_policy':'default','operation':'apply'},{'phase':'await-confirm','revision':'fixture','default_policy':'default','operation':'apply'},{'phase':'committed','backup_name':'fixture'}])
        sent=[];states=iter([False,True])
        class Fresh:
            def call(self,path):return {'name':'sdwan-edge'}
            def status(self):return {'backend':'container','container':{'active':next(states)},'revision':'fixture','selected':{'default':'wan1'}}
            def upload(self,path,data):sent.append(path)
            def close(self):pass
        r.fresh=lambda:Fresh()
        self.assertEqual(self.run_wait(r)['phase'],'committed')
        self.assertEqual(sent,['sdwan-deploy-ack.json'])

if __name__=='__main__':unittest.main()
