import ipaddress
import math
from pathlib import Path


def integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in {low}..{high}')
    return value


def validate(value):
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int or value.get('schema_version') != 1:
        raise ValueError('Expected schema_version 1 object')
    allowed = {'schema_version', 'warmup_seconds', 'seconds', 'repeats', 'subnet', 'tools', 'criteria', 'workloads'}
    if set(value) - allowed: raise ValueError('Unknown configuration fields: ' + ', '.join(sorted(set(value) - allowed)))
    c = dict(value)
    c['warmup_seconds'] = integer(c.get('warmup_seconds', 2), 'warmup_seconds', 1, 120)
    c['seconds'] = integer(c.get('seconds', 10), 'seconds', 2, 60)
    c['repeats'] = integer(c.get('repeats', 3), 'repeats', 1, 5)
    network = ipaddress.ip_network(c.get('subnet', '198.18.250.0/30'))
    if network.version != 4 or network.prefixlen != 30 or not network.subnet_of(ipaddress.ip_network('198.18.0.0/15')):
        raise ValueError('Use an isolated benchmark /30 within 198.18.0.0/15')
    c['subnet'] = str(network)
    tools = c.get('tools', {})
    if not isinstance(tools, dict) or set(tools) - {'iperf3', 'tcpreplay', 'cc'}: raise ValueError('Invalid tools object')
    c['tools'] = {key: tools.get(key, default) for key, default in (('iperf3', 'iperf3'), ('tcpreplay', 'tcpreplay'), ('cc', 'cc'))}
    if any(not isinstance(v, str) or not v or '\0' in v for v in c['tools'].values()): raise ValueError('Tool must be an executable name or path')
    limits = {'cpu_p95_max': 85, 'loss_percent_max': .1, 'variation_percent_max': 5}
    if not isinstance(c.get('criteria', {}), dict) or set(c.get('criteria', {})) - set(limits): raise ValueError('Unknown criterion')
    limits.update(c.get('criteria', {}))
    for key, v in limits.items():
        if type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 100: raise ValueError('Invalid criterion ' + key)
    c['criteria'] = limits
    if not isinstance(c.get('workloads'), list) or not 1 <= len(c['workloads']) <= 32: raise ValueError('Expected 1..32 workloads')
    cases = []
    for i, w in enumerate(c['workloads']):
        if not isinstance(w, dict): raise ValueError('Workload must be an object')
        fields = {'kind', 'direction', 'offered_bps', 'minimum_bps', 'parallel', 'payload_bytes', 'offered_pps', 'minimum_pps', 'rate', 'minimum_cps', 'delay_ms', 'concurrency', 'frame_sizes_with_fcs', 'batch'}
        if set(w) - fields: raise ValueError('Unknown workload fields')
        w = dict(w)
        if w.get('kind') not in ('tcp', 'udp', 'cps', 'imix'): raise ValueError('Unknown workload kind')
        per_kind = {'tcp': {'offered_bps','minimum_bps','parallel'},
                    'udp': {'payload_bytes','offered_pps','minimum_pps'},
                    'cps': {'rate','minimum_cps','delay_ms','concurrency'},
                    'imix': {'offered_pps','minimum_pps','frame_sizes_with_fcs','batch'}}
        if set(w)-per_kind[w['kind']]-{'kind','direction'}: raise ValueError('Field does not apply to this workload kind')
        if w.get('direction', 'forward') not in ('forward', 'reverse', 'bidir'): raise ValueError('Unknown direction')
        w.setdefault('direction', 'forward')
        if w['direction'] == 'bidir' and w['kind'] != 'tcp': raise ValueError('Only TCP supports bidir')
        if w['kind'] == 'tcp':
            w['parallel'] = integer(w.get('parallel', 1), 'parallel', 1, 16)
            for key, default in (('offered_bps', 150000000), ('minimum_bps', 125000000)):
                w[key] = integer(w.get(key, default), key, 1, 10000000000)
            if w['minimum_bps'] > w['offered_bps']: raise ValueError('Minimum exceeds offered rate')
        elif w['kind'] in ('udp', 'imix'):
            for key, default in (('offered_pps', 30000), ('minimum_pps', 25000)):
                w[key] = integer(w.get(key, default), key, 1, 1000000)
            if w['minimum_pps'] > w['offered_pps']: raise ValueError('Minimum exceeds offered rate')
            if w['kind'] == 'udp': w['payload_bytes'] = integer(w.get('payload_bytes', 64), 'payload_bytes', 16, 1472)
            else:
                sizes = w.get('frame_sizes_with_fcs', [64] * 7 + [570] * 4 + [1518])
                if not isinstance(sizes, list) or not 1 <= len(sizes) <= 100: raise ValueError('Invalid IMIX sequence')
                w['frame_sizes_with_fcs'] = [integer(n, 'frame size with FCS', 64, 1518) for n in sizes]
                w['batch'] = integer(w.get('batch', 60), 'batch', 1, 1000)
        else:
            for key, default, high in (('rate', 1250, 20000), ('minimum_cps', 1000, 20000), ('delay_ms', 0, 100), ('concurrency', 32, 64)):
                w[key] = integer(w.get(key, default), key, 0 if key == 'delay_ms' else 1, high)
            if w['rate'] * (c['seconds'] + c['warmup_seconds']) > 20000:
                raise ValueError('CPS case exceeds 20000 fresh connections per destination port; split the workload')
            if w['minimum_cps'] > w['rate']: raise ValueError('Minimum exceeds offered rate')
        cases.append(w)
    c['workloads'] = cases
    return c
