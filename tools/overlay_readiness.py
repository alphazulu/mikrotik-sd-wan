"""Read-only prerequisite for branch traffic, separate from WAN SLA admission."""


def enabled(value):
    return value is True or value == 'true'


def forwarding_state(neighbors, routes, prefixes, expected_neighbors):
    """Full adjacencies alone can precede installation of an OSPF return route."""
    full = sum(str(row.get('state', '')).lower() == 'full' for row in neighbors)
    active = {
        row.get('dst-address') for row in routes
        if row.get('routing-table') == 'main'
        and enabled(row.get('active')) and enabled(row.get('ospf'))
        and not enabled(row.get('blackhole')) and row.get('gateway')
    }
    missing = sorted(set(prefixes) - active)
    return {'ready': full == expected_neighbors and not missing,
            'full_neighbors': full, 'expected_neighbors': expected_neighbors,
            'missing_prefixes': missing}


def read_forwarding_state(router, prefixes, expected_neighbors):
    neighbors = router.call('routing/ospf/neighbor/print',
                            {'.proplist': 'state'}, 'POST')
    routes = router.call('ip/route/print',
                         {'.proplist': 'dst-address,routing-table,active,ospf,blackhole,gateway'},
                         'POST')
    return forwarding_state(neighbors, routes, prefixes, expected_neighbors)
