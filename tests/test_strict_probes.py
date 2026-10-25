import copy
from pathlib import Path
import unittest
from sdwan.config import load,validate,objects
from sdwan.probes import validate_probe,native_type,http_codes,requires_fetch

ROOT=Path(__file__).resolve().parents[1]
class StrictProbeTests(unittest.TestCase):
    def test_dns_expected_answers_are_explicit_canonical_ipv4(self):
        p={'type':'dns','dns_expected_ips':['192.0.2.1','192.0.2.2']};self.assertEqual(validate_probe(p),p)
        for values in [[],['bad'],['::1'],['192.0.2.01'],['0.0.0.0'],['224.0.0.1'],['192.0.2.1']*2]:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):validate_probe(dict(p,dns_expected_ips=values))
    def test_http_codes_preserve_old_default_and_validate_types(self):
        self.assertEqual(http_codes({'type':'http-get'}),'200-299')
        self.assertEqual(http_codes({'http_codes':[204,200]}),'200,204')
        validate_probe({'type':'http-get','http_codes':[503]})
        with self.assertRaisesRegex(ValueError,'require 2xx'):validate_probe({'type':'http-get','http_path':'/health','http_codes':[503]})
        for values in [[],[True],[99],[600],[200,200],['200']]:
            with self.assertRaises(ValueError):validate_probe({'type':'https-get','http_codes':values})
    def test_path_and_body_require_bounded_separate_worker(self):
        for p in [{'type':'http-get','http_path':'/health?version=1'},{'type':'https-get','http_expected_body':'healthy\n'},{'type':'http-get','http_expected_body':''}]:
            validate_probe(p);self.assertTrue(requires_fetch(p));self.assertEqual(native_type(p),'tcp-conn')
        self.assertEqual(native_type({'type':'https-get','http_codes':[204]}),'https-get')
        for path in ['http://other/','//other/','/hello world','/x\r\n','/%0a','/%zz','/x#fragment']:
            with self.assertRaises(ValueError):validate_probe({'type':'http-get','http_path':path})
        for body in ['x'*1025,'\0','я'*513,False]:
            with self.assertRaises(ValueError):validate_probe({'type':'http-get','http_expected_body':body})
    def test_expectations_cannot_be_attached_to_wrong_probe_type(self):
        for p in [{'type':'tcp-conn','http_codes':[200]},{'type':'dns','http_path':'/'},{'type':'http-get','dns_expected_ips':['192.0.2.1']}]:
            with self.assertRaises(ValueError):validate_probe(p)
    def test_native_objects_use_tcp_primer_only_for_async_http_probe(self):
        cfg=load(ROOT/'config/sdwan.json');cfg['wans'][0]['probes'][0]['http_expected_body']='healthy\n';cfg['wans'][0]['probes'][1]['http_codes']=[204]
        validate(cfg);native=objects(cfg)
        self.assertEqual(native[('tool/netwatch','sdwan:v1:probe:wan1:a')]['type'],'tcp-conn')
        self.assertEqual(native[('tool/netwatch','sdwan:v1:probe:wan1:b')]['http-codes'],'204')
    def test_global_async_budget_and_timing_bounds(self):
        cfg=load(ROOT/'config/sdwan.json')
        for field,value in [('strict_probe_interval_seconds',4),('strict_probe_timeout_ms',2001),('strict_probe_timeout_ms',True)]:
            c=copy.deepcopy(cfg);c['health'][field]=value
            with self.assertRaises(ValueError):validate(c)
        for wan in cfg['wans']:
            wan['probes']=[dict(wan['probes'][0],name='p'+str(i),port=48000+i,http_expected_body='ok') for i in range(6)]
        with self.assertRaisesRegex(ValueError,'At most 16'):validate(cfg)

if __name__=='__main__':unittest.main()
