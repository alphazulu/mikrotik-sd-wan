import re,sys,tempfile,time,unittest
from pathlib import Path
from sdwan_lab.runtime import Lease,Run
from sdwan_lab.continuity import measure

class SourceBindingTests(unittest.TestCase):
 def test_explicit_source_is_used_by_udp_and_persistent_tcp(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)
   with Lease(root/'workspace',root/'host.lock') as lease:
    run=Run(lease,'loopback-bind',{})
    try:
     server=run.spawn([sys.executable,'-m','sdwan_lab.continuity','serve','--listen','127.0.0.1','--port','0'],'echo')
     deadline=time.monotonic()+5;port=None
     while time.monotonic()<deadline:
      text=(run.folder/'echo.stdout').read_text()
      m=re.search(r'ready 127\.0\.0\.1:(\d+)',text)
      if m:port=int(m[1]);break
      self.assertIsNone(server.poll());time.sleep(.01)
     self.assertIsNotNone(port)
     result=measure('127.0.0.1',port,1,20,drain_seconds=.1,source_address='127.0.0.2')
     self.assertEqual(result['udp_tuple']['local'][0],'127.0.0.2')
     connected=[e for e in result['events'] if e['protocol']=='tcp' and e['event']=='connected']
     self.assertEqual(len(connected),1);self.assertEqual(connected[0]['local'][0],'127.0.0.2')
     self.assertGreater(result['protocols']['udp']['received'],0);self.assertGreater(result['protocols']['tcp']['received'],0)
    finally:self.assertTrue(run.cleanup())
 def test_wildcard_or_multicast_source_is_rejected_before_network(self):
  for address in ('0.0.0.0','224.0.0.1','not-an-ip'):
   with self.subTest(address=address),self.assertRaises(ValueError):measure('invalid.example.test',1,1,20,source_address=address)
