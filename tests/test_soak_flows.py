"""Prove scoped retirement/restart, none admission, and race rejection."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parent))
from vpn_traffic import Flow, VPNTraffic, same_path, tcp_stream
from tools.soak_observer import FlowObserver


def flow(label,wan='wan1',generation=1):
    policy='vpn' if label=='vpn' else 'default'
    row={'.id':label,'src-address':'192.0.2.10','src-port':str(50000+len(label)),
         'dst-address':'198.51.100.1','dst-port':str(60000+len(label)),
         'reply-src-address':'198.51.100.1','reply-src-port':str(60000+len(label)),
         'reply-dst-address':'192.0.2.20','reply-dst-port':str(50000+len(label)),
         'connection-mark':'no-mark' if label=='branch' else 'sdwan-out-'+policy+':'+wan,
         'tcp-state':'established','seen-reply':'true','orig-bytes':'10','repl-bytes':'100'}
    item=Flow(row,{'generation':generation,'requests':1,'active':1,'error':None});item.port=int(row['dst-port']);return item


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.flows={'ordinary':flow('ordinary'),'vpn':flow('vpn','vpn1'),'branch':flow('branch')}
        self.observer=FlowObserver(self.flows,{'ordinary':'default','vpn':'vpn'},0,tcp_stream,same_path)
        self.rows=[dict(x.snapshot) for x in self.flows.values()]
        self.traffic=Mock();self.traffic.find_stream.return_value=None
        self.traffic.stream_stats={item.port:item.http for item in self.flows.values()}
        self.state={'selected':{'default':'wan1','vpn':'vpn2'}}
        self.event={'seq':1,'policy':'vpn','from':'vpn1','to':'vpn2'}

    def test_only_affected_flow_restarts_after_proved_retirement(self):
        old=self.flows['vpn'];saved=dict(old.snapshot);unaffected=self.flows['ordinary']
        self.rows=[r for r in self.rows if r['.id']!='vpn']
        self.observer.tick(self.state,[self.event],self.rows,1,self.traffic)
        self.traffic.stop_stream.assert_called_once_with(old)
        self.traffic.start_attempt.assert_called_once_with(old.port,'sdwan-out-vpn:vpn2')
        self.assertEqual(self.observer.pending['vpn']['stage'],'reconnecting')
        new=flow('vpn','vpn2',2);self.traffic.find_stream.return_value=new
        self.observer.tick(self.state,[],self.rows+[new.snapshot],2,self.traffic)
        self.assertIs(self.flows['vpn'],new);self.assertIs(self.flows['ordinary'],unaffected)
        self.assertEqual(old.snapshot,saved);self.assertFalse(self.observer.pending)
        self.assertEqual(self.observer.transitions[0]['http_generation'],2)
        self.assertEqual(self.traffic.stop_stream.call_count,1)

    def test_no_restart_before_absence_and_retirement_timeout_fails(self):
        self.observer.tick(self.state,[self.event],self.rows,1,self.traffic)
        self.traffic.start_attempt.assert_not_called()
        with self.assertRaisesRegex(AssertionError,'not retired'):
            self.observer.tick(self.state,[],self.rows,8,self.traffic)

    def test_missing_original_without_event_never_restarts(self):
        with self.assertRaises(AssertionError):
            self.observer.tick(self.state,[],self.rows[1:],1,self.traffic)
        self.traffic.start_attempt.assert_not_called()

    def test_none_stops_only_owned_client_then_waits_for_admission(self):
        self.state['selected']['vpn']='none';event=dict(self.event,to='none');self.rows=[r for r in self.rows if r['.id']!='vpn']
        self.observer.tick(self.state,[event],self.rows,1,self.traffic)
        self.traffic.stop_stream.assert_called_once_with(self.flows['vpn'])
        self.observer.tick(self.state,[],self.rows,2,self.traffic)
        self.traffic.start_attempt.assert_not_called()
        self.state['selected']['vpn']='vpn1'
        self.observer.tick(self.state,[dict(self.event,seq=2,**{'from':'none','to':'vpn1'})],self.rows,3,self.traffic)
        self.traffic.start_attempt.assert_called_once_with(self.flows['vpn'].port,'sdwan-out-vpn:vpn1')

    def test_race_cancels_only_unverified_attempt_without_claiming_recovery(self):
        self.rows=[r for r in self.rows if r['.id']!='vpn'];self.observer.tick(self.state,[self.event],self.rows,1,self.traffic)
        self.state['selected']['vpn']='vpn1'
        self.observer.tick(self.state,[dict(self.event,seq=2,**{'from':'vpn2','to':'vpn1'})],self.rows,2,self.traffic)
        self.traffic.cancel_attempt.assert_called_once_with(self.flows['vpn'].port)
        self.assertEqual(len(self.observer.transitions),1)
        self.assertEqual(self.observer.transitions[0]['outcome'],'superseded_unverified')
        self.assertNotIn('new_tuple',self.observer.transitions[0])
        self.assertEqual(self.traffic.start_attempt.call_count,2)

    def test_unrelated_reconnect_and_stalled_stream_fail(self):
        self.flows['branch'].http['requests']=2
        with self.assertRaisesRegex(AssertionError,'restarted'):self.observer.tick(self.state,[],self.rows,1,self.traffic)
        self.flows['branch'].http['requests']=1
        with self.assertRaisesRegex(AssertionError,'stalled'):self.observer.tick(self.state,[],self.rows,13,self.traffic)


class ReuseTests(unittest.TestCase):
    def test_restart_reuses_script_and_server_without_persistent_writes(self):
        traffic=VPNTraffic.__new__(VPNTraffic);old=flow('vpn','vpn1')
        traffic.stream_specs={old.port:{'port':old.port,'source':old.snapshot['src-address'],'name':'owned-script','script':'*123','stats':old.http,'stop':__import__('threading').Event(),'lock':__import__('threading').Lock(),'connections':set()}}
        old.http['active']=0;traffic.stream_generations={old.port:[old.http]};traffic.stream_stats={old.port:old.http};traffic.connections=lambda:[]
        traffic.b=Mock();traffic.b.call.return_value=[{'.id':'*own','trace':'api/script:owned-script/:execute:1'},{'.id':'*other','trace':'api/script:someone-else/:execute:1'}]
        self.assertIsNone(traffic.restart_stream(old,'sdwan-out-vpn:vpn2',timeout=None))
        calls=traffic.b.call.call_args_list
        self.assertEqual([c.args[0] for c in calls],['system/script/job/print','system/script/job/*own','system/script/run'])
        self.assertEqual(traffic.stream_stats[old.port]['generation'],2)
        self.assertEqual(old.http['generation'],1)
        traffic.connections=lambda:[old.snapshot]
        with self.assertRaisesRegex(AssertionError,'retirement'):traffic.restart_stream(old,'sdwan-out-vpn:vpn2',timeout=None)
