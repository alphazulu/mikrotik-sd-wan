#!/usr/bin/env python3
"""Destructive-to-lab-only integration checks; always restore injected faults."""
import importlib.util
import json
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sdwan_lab', ROOT / 'lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


def counters():
    result = {}
    for i in (1, 2, 3):
        rules = lab.api(f'isp{i}', 'ip/firewall/filter/print', {'stats': ''}, 'POST')
        result[f'wan{i}'] = int(next(r for r in rules if r.get('comment') == 'path-proof')['packets'])
    return result


def path(source, expected):
    before = counters()
    results, ok = lab.ping('client', '198.19.0.1', source, count=4)
    after = counters()
    increments = {wan: after[wan] - before[wan] for wan in before}
    passed = ok and increments[expected] > 0 and all(v == 0 for k, v in increments.items() if k != expected)
    if not passed:
        raise AssertionError({'source': source, 'expected': expected, 'counters': increments, 'ping': results})
    return {'source': source, 'expected': expected, 'counter_delta': increments}


def wait_route(comment, table='main', timeout=45):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        routes = lab.api('edge', 'ip/route')
        if any(r.get('comment') == comment and r.get('routing-table') == table and r.get('active') == 'true' for r in routes):
            return
        time.sleep(1)
    raise AssertionError(f'Route {comment} did not become active in {table}')


def milliseconds(value):
    # RouterOS duration can be 1ms234us, 123us or 00:00:00.123.
    import re
    units = {'s': 1000, 'ms': 1, 'us': .001, 'ns': .000001}
    if ':' in value:
        h, m, s = value.split(':')
        return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000
    return sum(float(n) * units[u] for n, u in re.findall(r'([\d.]+)(ms|us|ns|s)', value))


def main():
    if lab.api('edge', 'system/scheduler?name=sdwan-controller'):
        raise RuntimeError('Native SD-WAN is installed: use tests/native_acceptance.py, or rollback before baseline acceptance.')
    report = {'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'checks': []}
    def record(name, detail):
        report['checks'].append({'check': name, 'pass': True, 'detail': detail})
        print(f'PASS {name}', flush=True)
    try:
        lab.proxy_request({'reset': True})
        for i in (1, 2, 3):
            lab.qmp('edge', 'set_link', {'name': f'nic{i+1}', 'up': True})
        wait_route('baseline-wan1')
        wait_route('client102-wan2', 'prefer-wan2')
        record('client .101 uses WAN1', path('192.168.50.101', 'wan1'))
        record('client .102 uses WAN2', path('192.168.50.102', 'wan2'))

        started = time.monotonic()
        lab.qmp('edge', 'set_link', {'name': 'nic2', 'up': False})
        wait_route('baseline-wan2')
        detail = path('192.168.50.101', 'wan2')
        detail['observed_recovery_seconds'] = round(time.monotonic() - started, 3)
        record('physical WAN1 outage: .101 switches to WAN2', detail)
        record('.102 remains on WAN2', path('192.168.50.102', 'wan2'))
        lab.qmp('edge', 'set_link', {'name': 'nic2', 'up': True})
        wait_route('baseline-wan1')

        started = time.monotonic()
        lab.proxy_request({'wan': 'wan1', 'set': {'blackhole': True}})
        wait_route('baseline-wan2')
        detail = path('192.168.50.101', 'wan2')
        detail['observed_recovery_seconds'] = round(time.monotonic() - started, 3)
        record('silent WAN1 blackhole triggers gateway-check fallback', detail)
        lab.proxy_request({'reset': True})
        wait_route('baseline-wan1')

        result, ok = lab.ping('edge', '198.18.3.1')
        baseline = [milliseconds(r['time']) for r in result if 'time' in r and not r.get('status')]
        if not ok or not baseline:
            raise AssertionError('Baseline WAN3 ping failed')
        lab.proxy_request({'wan': 'wan3', 'set': {'delay': 60.0}})
        result, ok = lab.ping('edge', '198.18.3.1')
        delayed = [milliseconds(r['time']) for r in result if 'time' in r and not r.get('status')]
        if not ok or not delayed or sum(delayed)/len(delayed) - sum(baseline)/len(baseline) < 90:
            raise AssertionError({'baseline_ms': baseline, 'delayed_ms': delayed})
        record('WAN3 bidirectional delay adds at least 90ms to RTT', {'baseline_ms': baseline, 'delayed_ms': delayed})
        lab.proxy_request({'reset': True})

        for i in (1, 2, 3):
            lab.qmp('edge', 'set_link', {'name': f'nic{i+1}', 'up': False})
        time.sleep(1)
        _, ok = lab.ping('client', '198.19.0.1', '192.168.50.101', count=2)
        if ok:
            raise AssertionError('Traffic unexpectedly escaped with all WANs down')
        for n in lab.NODES:
            lab.api(n, 'system/resource')
        record('all WANs down: transit stops, management survives', {})
    except Exception as exc:
        report['checks'].append({'check': 'acceptance interrupted', 'pass': False, 'detail': str(exc)})
        raise
    finally:
        lab.proxy_request({'reset': True})
        for i in (1, 2, 3):
            lab.qmp('edge', 'set_link', {'name': f'nic{i+1}', 'up': True})
        wait_route('baseline-wan1')
        wait_route('client102-wan2', 'prefer-wan2')
        lab.save(lab.RUN / 'acceptance.json', report)


if __name__ == '__main__':
    main()
