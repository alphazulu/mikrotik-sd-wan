import importlib.util,itertools,json,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('traffic_identity',ROOT/'tests/vpn_traffic.py');traffic=importlib.util.module_from_spec(spec);spec.loader.exec_module(traffic)
class TrafficIdentityTests(unittest.TestCase):
 def baseline(self):return {'.id':'*1','src-address':'192.0.2.1','src-port':'50000','dst-address':'198.51.100.1','dst-port':'80','reply-src-address':'198.51.100.1','reply-src-port':'80','reply-dst-address':'192.0.2.2','reply-dst-port':'50000','connection-mark':'sdwan-out-default:wan1','orig-bytes':'100','repl-bytes':'1000','tcp-state':'established','seen-reply':'true'}
 def fixture(self):
  value=traffic.VPNTraffic.__new__(traffic.VPNTraffic);value.a=SimpleNamespace(status=lambda:{});flow=traffic.Flow(self.baseline(),{'requests':1,'active':1,'error':None});return value,flow
 def test_absent_flow_cannot_pass_only_because_api_handle_changed(self):
  value,flow=self.fixture();renamed=dict(flow.snapshot,**{'.id':'*99'});value.connections=Mock(return_value=[renamed])
  with patch.object(traffic.time,'monotonic',side_effect=itertools.count(0,.1).__next__),patch.object(traffic.time,'sleep'),self.assertRaisesRegex(AssertionError,'unexpected'):
   value.assert_sessions(absent=[flow])
  self.assertTrue(traffic.same_path(flow,renamed));self.assertFalse(traffic.same_path(flow,dict(renamed,**{'connection-mark':'sdwan-out-default:wan2'})))
 def test_retained_flow_survives_handle_change_with_same_tuple_and_http(self):
  value,flow=self.fixture();first=dict(flow.snapshot,**{'.id':'*99','orig-bytes':'200','repl-bytes':'2000'});second=dict(first,**{'repl-bytes':'3000'});value.connections=Mock(side_effect=[[first],[second]])
  with patch.object(traffic.time,'monotonic',side_effect=itertools.count(0,.1).__next__),patch.object(traffic.time,'sleep'):
   value.assert_sessions(retained=[flow])
  self.assertEqual(flow.last['.id'],'*99');self.assertEqual(flow.last['repl-bytes'],'3000');self.assertEqual(flow.snapshot['.id'],'*1');self.assertEqual(json.dumps(flow),'"*1"')
if __name__=='__main__':unittest.main()
