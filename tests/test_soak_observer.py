"""Portable regressions: real policy failover must not be mistaken for failure."""
import copy
import json
import unittest
from tools.soak_observer import EventCursor, expected_selection, validate_intent


def fixture():
    cfg={'revision':'test-v1','wans':[{'name':n} for n in ('wan1','vpn1','vpn2')],
         'policies':[{'name':'default','profile':'default','wans':['wan1'],'allow_degraded':False},
                     {'name':'vpn','profile':'strict','wans':['vpn1','vpn2','wan1'],'allow_degraded':False}]}
    state={'revision':'test-v1','uptime_seconds':100,'selected':{'default':'wan1','vpn':'vpn1'},
           'states':{p+'/'+n:{'state':'healthy'} for p in ('default','strict') for n in ('wan1','vpn1','vpn2')},
           'samples':{n:{'stale':False} for n in ('wan1','vpn1','vpn2')},
           'maintenance':{n:{'admit':True} for n in ('wan1','vpn1','vpn2')},'events':[]}
    return cfg,state


def event(seq,source,target,policy='vpn'):
    return {'type':'policy','seq':seq,'policy':policy,'from':source,'to':target,'revision':'test-v1','removed':1,'uptime_seconds':101}


class SelectionTests(unittest.TestCase):
    def test_priority_and_policy_profiles_are_independent(self):
        cfg,state=fixture();state['states']['strict/vpn1']['state']='degraded'
        self.assertEqual(expected_selection(cfg,state),{'default':'wan1','vpn':'vpn2'})
        state['states']['default/wan1']['state']='down'
        self.assertEqual(expected_selection(cfg,state),{'default':'none','vpn':'vpn2'})

    def test_degraded_only_when_opted_in_and_after_all_healthy(self):
        cfg,state=fixture();cfg['policies'][1]['allow_degraded']=True
        state['states']['strict/vpn1']['state']='degraded'
        self.assertEqual(expected_selection(cfg,state)['vpn'],'vpn2')
        state['states']['strict/vpn2']['state']='down';state['states']['strict/wan1']['state']='recovering'
        self.assertEqual(expected_selection(cfg,state)['vpn'],'vpn1')
        cfg['policies'][1]['allow_degraded']=False
        self.assertEqual(expected_selection(cfg,state)['vpn'],'none')

    def test_administrative_drain_and_down_close_admission(self):
        for mode in ('drain','down'):
            cfg,state=fixture();cfg['wans'][1]['admin_state']=mode;state['maintenance']['vpn1']['admit']=False
            self.assertEqual(expected_selection(cfg,state)['vpn'],'vpn2')
            state['maintenance']['vpn1']['admit']=True
            with self.assertRaises(AssertionError):expected_selection(cfg,state)

    def test_raw_probe_staleness_does_not_bypass_confirmed_hysteresis(self):
        cfg,state=fixture();state['samples']['vpn1']['stale']=True
        self.assertEqual(expected_selection(cfg,state)['vpn'],'vpn1')
        state['states']['strict/vpn1']['state']='down'
        self.assertEqual(expected_selection(cfg,state)['vpn'],'vpn2')

    def test_missing_stale_and_unknown_evidence_never_passes(self):
        for key in ('states','samples','maintenance'):
            cfg,state=fixture();state.pop(key)
            with self.subTest(key=key),self.assertRaises(AssertionError):expected_selection(cfg,state)
        for stale in (None,):
            cfg,state=fixture();state['samples']['vpn1']['stale']=stale
            with self.assertRaises(AssertionError):expected_selection(cfg,state)
        cfg,state=fixture();state['states']['strict/vpn1']['state']='surprise'
        with self.assertRaises(AssertionError):expected_selection(cfg,state)


class CursorTests(unittest.TestCase):
    def test_justified_sla_failover_then_failback(self):
        cfg,state=fixture();cursor=EventCursor(state,cfg)
        state['states']['strict/vpn1']['state']='degraded';state['selected']['vpn']='vpn2';state['events']=[dict(event(1,'healthy','degraded','strict/vpn1'),type='state'),event(2,'vpn1','vpn2')]
        self.assertEqual(len(cursor.advance(state,expected_selection(cfg,state))),1)
        state['states']['strict/vpn1']['state']='healthy';state['selected']['vpn']='vpn1';state['events'].extend([dict(event(3,'degraded','healthy','strict/vpn1'),type='state'),event(4,'vpn2','vpn1')])
        self.assertEqual(cursor.advance(state,expected_selection(cfg,state))[0]['to'],'vpn1')
        self.assertEqual(cursor.advance(state,expected_selection(cfg,state)),[])

    def test_out_and_back_is_not_a_steady_selection(self):
        cfg,state=fixture();cursor=EventCursor(state,cfg);state['events']=[dict(event(1,'healthy','degraded','strict/vpn1'),type='state'),event(2,'vpn1','vpn2'),dict(event(3,'degraded','healthy','strict/vpn1'),type='state'),event(4,'vpn2','vpn1')]
        self.assertEqual(len(cursor.advance(state,expected_selection(cfg,state))),2)

    def test_missing_or_reordered_events_and_broken_chain_fail(self):
        variants=[[event(2,'vpn1','vpn2')],[event(1,'vpn1','vpn2'),event(3,'vpn2','vpn1')],
                  [event(2,'vpn2','vpn1'),event(1,'vpn1','vpn2')],[event(1,'wan1','vpn1')]]
        for events in variants:
            cfg,state=fixture();cursor=EventCursor(state,cfg);state['events']=events
            with self.subTest(events=events),self.assertRaises(AssertionError):cursor.advance(state,expected_selection(cfg,state))

    def test_unrecorded_selection_priority_violation_reboot_revision_fail(self):
        for change in ('unrecorded','wrong_priority','reboot','revision'):
            cfg,state=fixture();cursor=EventCursor(state,cfg)
            if change=='unrecorded':state['selected']['vpn']='vpn2'
            if change=='wrong_priority':state['selected']['vpn']='vpn2';state['events']=[event(1,'vpn1','vpn2')]
            if change=='reboot':state['uptime_seconds']=99
            if change=='revision':state['revision']='other'
            with self.subTest(change=change),self.assertRaises(AssertionError):cursor.advance(state,expected_selection(cfg,state))


class IntentTests(unittest.TestCase):
    def fixture(self):
        cfg,state=fixture();state['container']={'active':True,'owner_instance':'owned','boot_id':'boot','generation':1,'lease_remaining_seconds':6}
        intent={'revision':cfg['revision'],'protocol':1,'release':False,'instance':'owned','boot_id':'boot','generation':1,'seq':1,'selected':state['selected'],'observed_uptime':100}
        return cfg,state,intent

    def test_unchanged_and_proved_claim_plan_change(self):
        cfg,state,intent=self.fixture();text=json.dumps(intent)
        self.assertIsNone(validate_intent(text,text,cfg,state))
        self.assertIsNotNone(validate_intent('',text,cfg,state,backend_start=True))
        new=dict(intent,seq=2)
        self.assertIsNotNone(validate_intent(text,json.dumps(new),cfg,state,transitions=[event(1,'vpn1','vpn2')]))

    def test_periodic_rewrite_owner_fence_and_stale_claim_fail(self):
        cfg,state,intent=self.fixture();text=json.dumps(intent)
        with self.assertRaises(AssertionError):validate_intent('',text,cfg,state)
        for key,value in [('instance','alien'),('boot_id','other'),('generation',2),('seq',0),('observed_uptime',80),('release',True),('selected',{'default':'none'})]:
            bad=dict(intent,**{key:value})
            with self.subTest(key=key),self.assertRaises(AssertionError):validate_intent('',json.dumps(bad),cfg,state,backend_start=True)
