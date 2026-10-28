import copy,json,tempfile,unittest
from pathlib import Path
from comparison import STAGES,build_plan,execute,gate,validate_measurement,validate_plan
from sdwan_lab.runtime import Lease,Run

class FakeAdapter:
 def __init__(self,drift=0,restore=True,wrong=False):self.modes=[];self.drift=drift;self.restore_ok=restore;self.restores=0;self.wrong=wrong
 def preflight(self,plan,run):return dict(pass_=True,**{'pass':True,'scope':'owned-isolated-lab','source_matches_plan':True,'generator_calibration_pass':True,'cps_source_pool_validated':True,'simulation':True})
 def snapshot(self,*args):return {'synthetic':True,'original_mode':'baseline'}
 def set_mode(self,mode,*args):self.modes.append(mode)
 def measure(self,mode,case,repeat,*args):return {'pass':True,'observed_mode':'wrong' if self.wrong else mode,'rate_unit':{'tcp':'bps','udp':'pps','cps':'cps'}[case['kind']],'receiver_rate':100+(self.drift if mode=='baseline-after' else 0),'dut_cpu_mean_percent':20,'dut_cpu_p95_percent':30,'dut_memory_free_min_bytes':1000000,'generator_cpu_p95_max_percent':10,'host_steal_p95_percent':0,'container_memory_peak_bytes':0,'write_sectors_delta':None,'simulation':True}
 def switching(self,*args):return {'pass':True,'pinned_flow_preserved':True,'observer':'sdwan_lab.continuity','simulation':True}
 def restore(self,*args):self.restores+=1;return {'pass':self.restore_ok,'verified':self.restore_ok,'simulation':True}

class ComparisonTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.plan=build_plan({}, {'synthetic':True},repeats=3)
 def run_adapter(self,adapter):
  with Lease(self.root/'workspace',self.root/'host.lock') as lease:
   run=Run(lease,'synthetic',{});result=execute(self.plan,adapter,run);return result,run
 def test_fixed_sequential_modes_and_baseline_controls(self):
  adapter=FakeAdapter();result,run=self.run_adapter(adapter)
  self.assertTrue(result['pass']);self.assertEqual(adapter.modes,list(STAGES));self.assertEqual(adapter.restores,1);self.assertEqual(len(result['runs']),90);self.assertEqual(len(result['switching']),3);self.assertFalse(result['capacity_validated'])
 def test_source_port_pool_is_required_for_cps_window(self):self.assertTrue(next(w for w in self.plan['workloads'] if w['kind']=='cps')['requires_source_pool'])
 def test_original_soak_must_pass_both_phases(self):
  d={'status':'passed','pass':True,'kind':'release','elapsed_seconds':172800,'failures':[],'phase_samples':{'native':1,'container':1}};gate(d)
  for patch in [{'status':'running'},{'elapsed_seconds':172799},{'phase_samples':{'native':1,'container':0}},{'failures':['failed']}]:
   with self.assertRaises(ValueError):gate(dict(d,**patch))
 def test_changed_order_and_l2_imix_rejected(self):
  for plan in [dict(self.plan,stages=list(reversed(STAGES))),dict(self.plan,workloads=[{'id':'raw','kind':'imix'}])]:
   with self.assertRaises(ValueError):validate_plan(plan)
 def test_baseline_drift_invalidates_comparison(self):
  result,_=self.run_adapter(FakeAdapter(drift=50));self.assertFalse(result['pass']);self.assertEqual(result['status'],'invalid_baseline_drift');self.assertTrue(result['cleanup_pass'])
 def test_wrong_observed_backend_fails_and_restores(self):
  adapter=FakeAdapter(wrong=True);result,_=self.run_adapter(adapter);self.assertFalse(result['pass']);self.assertTrue(result['cleanup_pass']);self.assertEqual(adapter.restores,1)
 def test_unverified_restore_blocks_next_run_and_recovery_preserves_raw(self):
  result,run=self.run_adapter(FakeAdapter(restore=False));self.assertFalse(result['cleanup_pass']);self.assertEqual(run.data['state'],'cleanup_failed');original=(run.folder/'report.json').read_bytes()
  with Lease(self.root/'workspace',self.root/'host.lock') as lease:
   with self.assertRaises(RuntimeError):Run(lease,'new',{})
   recovered=Run(lease,'synthetic',recover=True);out=execute(self.plan,FakeAdapter(),recovered,recover=True);self.assertTrue(out['recovery_pass'])
  self.assertEqual((run.folder/'report.json').read_bytes(),original)
 def test_zero_receiver_and_nonfinite_metrics_rejected(self):
  row=FakeAdapter().measure('routeros',self.plan['workloads'][0],0)
  for changes in [{'receiver_rate':0},{'dut_cpu_mean_percent':float('nan')},{'write_sectors_delta':-1}]:
   with self.assertRaises(ValueError):validate_measurement(dict(row,**changes),'routeros')
