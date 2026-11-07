import base64
import copy
from pathlib import Path
import unittest
from sdwan.config import load
from sdwan.overlay import validate,effective_networks

ROOT=Path(__file__).resolve().parents[1]
def key(n):return base64.b64encode(bytes([n])*32).decode()
def config():
    cfg=load(ROOT/'config/sdwan.json');cfg['overlay']={'enabled':True,'role':'site','router_id':'10.202.0.1','local_prefixes':['10.201.1.0/24'],'remote_prefixes':['10.201.2.0/24'],'tunnels':[{'name':'hub-wan1','wan':'wan1','listen_port':51821,'address':'10.203.1.0/31','peer_address':'10.203.1.1','local_public_key':key(1),'peer_public_key':key(2),'peer_prefixes':['10.201.2.0/24'],'cost':10,'endpoint':'198.18.100.1','endpoint_port':51821}]};return cfg

class OverlayTests(unittest.TestCase):
    def test_dual_cgnat_sites_require_a_reachable_hub_and_keep_local_control(self):
        cfg=config();validate(cfg);second=copy.deepcopy(cfg['overlay']['tunnels'][0]);second.update(name='hub-wan2',wan='wan2',listen_port=51822,address='10.203.2.0/31',peer_address='10.203.2.1',local_public_key=key(3),peer_public_key=key(4),cost=20);cfg['overlay']['tunnels'].append(second);validate(cfg)
        self.assertIn('10.201.2.0/24',effective_networks(cfg));self.assertIn('10.203.2.0/31',effective_networks(cfg))
        del second['endpoint']
        with self.assertRaisesRegex(ValueError,'reachable public hub'):validate(cfg)
    def test_private_keys_unknown_fields_and_invalid_public_keys_are_rejected(self):
        for patch in [{'private_key':key(9)},{'local_public_key':key(0)},{'peer_public_key':'bad'},{'peer_public_key':key(1)}]:
            cfg=config();cfg['overlay']['tunnels'][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate(cfg)
    def test_prefix_and_endpoint_recursion_fail_before_network_changes(self):
        for patch in [{'remote_prefixes':['0.0.0.0/0']},{'remote_prefixes':['10.201.1.0/24']},{'local_prefixes':['172.20.1.0/24']}]:
            cfg=config();cfg['overlay'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate(cfg)
        for patch in [{'address':'10.201.2.0/31','peer_address':'10.201.2.1'},{'endpoint':'10.201.2.5'},{'endpoint':'http://hub/'},{'address':'10.203.1.0/24'}]:
            cfg=config();cfg['overlay']['tunnels'][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate(cfg)
    def test_hub_never_initiates_toward_an_unreachable_cgnat_endpoint(self):
        cfg=config();cfg['overlay']['role']='hub';cfg['overlay']['local_prefixes']=[]
        with self.assertRaisesRegex(ValueError,'responder-only'):validate(cfg)
        tunnel=cfg['overlay']['tunnels'][0];del tunnel['endpoint'];del tunnel['endpoint_port'];validate(cfg)
    def test_disabled_overlay_allocates_no_derived_networks_and_cannot_hide_secrets(self):
        cfg=config();cfg['overlay']={'enabled':False};validate(cfg);self.assertEqual(effective_networks(cfg),cfg['local_networks'])
        cfg['overlay']['private_key']=key(9)
        with self.assertRaises(ValueError):validate(cfg)
    def test_mtu_and_probe_budget_are_bounded(self):
        for patch in [{'mtu':1500},{'mtu':True},{'health':{'packet_count':20,'interval_seconds':1}},{'health':{'stale_seconds':2}}]:
            cfg=config();cfg['overlay'].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate(cfg)

if __name__=='__main__':unittest.main()
