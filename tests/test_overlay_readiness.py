import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from overlay_readiness import forwarding_state, read_forwarding_state

PREFIX = '198.51.100.0/24'
NEIGHBORS = [{'state': 'Full'}, {'state': 'Full'}]
ROUTE = {'dst-address': PREFIX, 'routing-table': 'main', 'active': 'true',
         'ospf': 'true', 'gateway': '192.0.2.1%wireguard1'}


class OverlayForwardingReadinessTests(unittest.TestCase):
    def test_full_neighbors_with_only_the_remote_blackhole_are_not_ready(self):
        guard = dict(ROUTE, ospf='false', blackhole='true', gateway='')
        state = forwarding_state(NEIGHBORS, [guard], [PREFIX], 2)
        self.assertFalse(state['ready'])
        self.assertEqual(state['full_neighbors'], 2)
        self.assertEqual(state['missing_prefixes'], [PREFIX])

    def test_active_ospf_return_route_finishes_preparation(self):
        state = forwarding_state(NEIGHBORS, [ROUTE], [PREFIX], 2)
        self.assertTrue(state['ready'])
        self.assertEqual(state['missing_prefixes'], [])

    def test_invalid_or_non_forwarding_routes_do_not_satisfy_the_gate(self):
        for changes in ({'active': 'false'}, {'ospf': 'false'},
                        {'routing-table': 'another-vrf'}, {'blackhole': 'true'},
                        {'gateway': ''}):
            with self.subTest(changes=changes):
                route = dict(ROUTE, **changes)
                self.assertFalse(forwarding_state(NEIGHBORS, [route], [PREFIX], 2)['ready'])

    def test_all_remote_prefixes_are_required(self):
        state = forwarding_state(NEIGHBORS, [ROUTE], [PREFIX, '203.0.113.0/24'], 2)
        self.assertFalse(state['ready'])
        self.assertEqual(state['missing_prefixes'], ['203.0.113.0/24'])

    def test_active_routes_do_not_replace_full_adjacency_checks(self):
        for neighbors in ([{'state': 'Loading'}, {'state': 'Full'}],
                          NEIGHBORS + [{'state': 'Full'}]):
            with self.subTest(neighbors=neighbors):
                self.assertFalse(forwarding_state(neighbors, [ROUTE], [PREFIX], 2)['ready'])

    def test_native_and_rest_flags_agree_without_mutating_rows(self):
        rows = [dict(ROUTE, active=True, ospf=True, blackhole=False)]
        before = copy.deepcopy(rows)
        self.assertTrue(forwarding_state(NEIGHBORS, rows, [PREFIX], 2)['ready'])
        self.assertEqual(rows, before)

    def test_reader_requests_only_routing_evidence(self):
        class Router:
            def __init__(self): self.calls = []
            def call(self, path, data, method):
                self.calls.append((path, data, method))
                return NEIGHBORS if path.startswith('routing/') else [ROUTE]
        router = Router()
        self.assertTrue(read_forwarding_state(router, [PREFIX], 2)['ready'])
        self.assertEqual([row[0] for row in router.calls],
                         ['routing/ospf/neighbor/print', 'ip/route/print'])
        self.assertTrue(all(method == 'POST' and set(data) == {'.proplist'}
                            for _, data, method in router.calls))


if __name__ == '__main__':
    unittest.main()
