import unittest
from sdwan_lab.continuity import analyze,measure

class ContinuityTests(unittest.TestCase):
 def test_loss_duplicates_reordering_and_long_gap(self):
  events=[dict(protocol='udp',event='sent',seq=q,ns=q*10000000) for q in range(6)]
  events += [dict(protocol='udp',event='received',seq=q,ns=t*1000000) for q,t in [(0,1),(2,21),(1,22),(2,23),(5,101)]]
  r=analyze(events,120000000,10000000)['protocols']['udp']
  self.assertEqual((r['offered'],r['received'],r['unanswered'],r['duplicates'],r['reordered']),(6,4,2,1,1))
  self.assertEqual(r['max_success_gap_ms'],79);self.assertEqual(r['max_gap_above_interval_ms'],69);self.assertEqual(r['trailing_silence_ms'],19)
 def test_no_success_does_not_report_zero_outage(self):
  r=analyze([],100000000,10000000)['protocols']['udp'];self.assertIsNone(r['max_success_gap_ms']);self.assertEqual(r['trailing_silence_ms'],100)
 def test_tcp_reconnect_is_not_session_survival(self):
  r=analyze([dict(protocol='tcp',event='connected',session=1,ns=0),dict(protocol='tcp',event='disconnected',session=1,ns=1),dict(protocol='tcp',event='connected',session=2,ns=2)],100,10)
  self.assertEqual(r['protocols']['tcp']['established_sessions'],2);self.assertEqual(r['protocols']['tcp']['disconnects'],1)
 def test_unknown_reply_does_not_count_as_success(self):
  r=analyze([dict(protocol='udp',event='received',seq=9,ns=1)],100,10);self.assertEqual(r['protocols']['udp']['received'],0)
 def test_probe_budget_rejected_before_network(self):
  with self.assertRaises(ValueError):measure('invalid.example.test',1,3600,5)
