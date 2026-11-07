"""Blank assertions must retain their location and safe web state before rollback."""
import json
import unittest
from test_network_soak import soak


@unittest.skipIf(soak is None,'CHR soak uses POSIX locks on Linux/WSL')
class SoakFailureDiagnostics(unittest.TestCase):
    def test_blank_nested_assertion_keeps_innermost_location(self):
        def failing():
            assert False
        try:failing()
        except AssertionError as error:detail=soak.failure_details(error)
        self.assertEqual(detail['type'],'AssertionError');self.assertEqual(detail['message'],'')
        last=detail['traceback'][-1]
        self.assertEqual(last['file'],'test_soak_failure_diagnostics.py')
        self.assertEqual(last['function'],'failing');self.assertGreater(last['line'],0)

    def test_stale_web_and_overlay_are_saved_without_credentials_or_arbitrary_data(self):
        web={'request_started_utc':12,'read_utc':13,'http_status':200,'request_seconds':1,
             'headers':{'Authorization':'must-not-copy'},'data':{
                 'stale':True,'age_seconds':11,'history_points':12,'history_capacity':12,
                 'token':'must-not-copy','current':{'actor':'container','uptime_seconds':100,
                 'password':'must-not-copy','transports':[{},{}],
                 'overlay':[{'name':'branch','wan':'wan1','healthy':False,'sample_age_seconds':11,'secret':'must-not-copy'}]},
                 'resources':{'rss_bytes':900000,'cpu_ticks':10,'write_bytes':0,'secret':'must-not-copy'}}}
        result=soak.failure_details(AssertionError('web stale'),web)
        self.assertTrue(result['web']['stale']);self.assertEqual(result['web']['age_seconds'],11)
        self.assertEqual(result['web']['transports_count'],2)
        self.assertEqual(result['web']['overlay_count'],1)
        self.assertFalse(result['web']['overlay'][0]['healthy'])
        self.assertEqual(result['web']['resources']['rss_bytes'],900000)
        self.assertNotIn('must-not-copy',json.dumps(result))
        self.assertNotIn('Authorization',json.dumps(result))

    def test_http_failure_retains_status_and_last_successful_snapshot_time(self):
        result=soak.failure_details(TimeoutError('HTTP timeout'),{
            'request_started_utc':30,'read_utc':10,'http_status':None,
            'request_seconds':4,'data':{'stale':False,'current':None}})
        self.assertEqual(result['web']['request_started_utc'],30)
        self.assertEqual(result['web']['read_utc'],10)
        self.assertIsNone(result['web']['http_status'])
        self.assertNotIn('actor',result['web'])

    def test_missing_and_wrong_web_shapes_do_not_hide_the_original_exception(self):
        for value in [None,{}, {'data':None}, {'data':[]},
                      {'data':{'current':{'overlay':'invalid','transports':None},'resources':[]}}]:
            with self.subTest(value=value):
                result=soak.failure_details(ValueError('original failure'),value)
                self.assertEqual(result['message'],'original failure')
                self.assertEqual(result['type'],'ValueError')

    def test_overlay_diagnostic_is_bounded(self):
        result=soak.failure_details(AssertionError(),{'data':{'current':{'overlay':[{'healthy':True}]*20}}})
        self.assertEqual(result['web']['overlay_count'],20)
        self.assertEqual(len(result['web']['overlay']),16)
