"""Cross-check RouterOS replay fixtures against existing policy semantics."""
import ipaddress
import json
from pathlib import Path
import unittest
from sdwan.config import validate
from sdwan.policies import match_flow

ROOT=Path(__file__).resolve().parents[1]
class LiveConfigurationCases(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'tests/native_config_state_cases.json').read_text())
    def test_replay_configs_pass_the_real_schema(self):
        for name,cfg in self.data['configs'].items():
            with self.subTest(name=name):validate(cfg)
        self.assertLess((ROOT/'tests/native_config_state_cases.json').stat().st_size,60000)
    def test_each_held_flow_was_owned_by_the_claimed_original_policy(self):
        for case in self.data['flow_cases']:
            with self.subTest(case=case['name']):
                cfg=self.data['configs'][case['previous']];f=case['flow'];lists={}
                for name,values in case['initial_lists'].items():
                    networks=[]
                    for value in values:
                        try:
                            if '-' in value:
                                first,last=value.split('-');networks.extend(str(n) for n in ipaddress.summarize_address_range(ipaddress.IPv4Address(first),ipaddress.IPv4Address(last)))
                            else:networks.append(str(ipaddress.IPv4Network(value,strict=False)))
                        except ValueError:pass # DNS parent: only resolved child IPs match.
                    lists[name]=networks
                policy=next(p for p in cfg['policies'] if p['name']==case['policy'])
                actual=match_flow(cfg,f['source'],f['destination'],f['protocol'],f['src_port'],f['dst_port'],in_interface=policy.get('in_interface',''),address_lists=lists)
                self.assertEqual(actual['policy'],case['policy'])
if __name__=='__main__':unittest.main()
