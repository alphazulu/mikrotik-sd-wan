#!/usr/bin/env python3
"""One locked, host-observed CHR soak; decisions remain on the MikroTiks.

Default: 24 hours of native warm fallback, then 24 hours of the pinned local
scratch image, with the same configuration and three continuous TCP streams.
Reports/checkpoints live in the private lab, never on RouterOS flash.
"""
import argparse
import contextlib
import fcntl
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic, tcp_stream, same_path
from soak_observer import EventCursor, FlowObserver, expected_selection, validate_intent
from sdwan.container_runtime import paths, read_container
from sdwan.router import Router
from container_checks import source_digest


def digest(data):
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def source_manifest():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    return {name: digest((ROOT / name).read_bytes()) for name in sorted(filter(None, names))}


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def exclusive_lock(path):
    handle = path.open('a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        handle.close()
        raise
    return handle


def wait(predicate, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.5)
    raise AssertionError('CHR warm-up did not converge within its deadline')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('run', 'status'))
    parser.add_argument('--lab-root', type=Path, required=True)
    parser.add_argument('--hours', type=float, default=48)
    parser.add_argument('--native-hours', type=float, default=24)
    parser.add_argument('--sample-seconds', type=int, default=30)
    parser.add_argument('--control-seconds', type=float, default=2)
    parser.add_argument('--force-smoke-failover', action='store_true', help='Drop only synthetic VPN1 probe packets in BOTH smoke phases')
    parser.add_argument('--max-rss-mib', type=int, default=32, help='Lab process RSS ceiling, not a physical-router guarantee')
    parser.add_argument('--smoke-seconds', type=int, help='Short driver check, explicitly not a release soak')
    args = parser.parse_args()
    run = args.lab_root / 'runtime/overlay-lab/runtime'
    report_path = run / ('network-soak-smoke.json' if args.smoke_seconds else 'network-soak.json')
    if args.command == 'status':
        if not report_path.exists():
            print(json.dumps({'status': 'not_started'}))
            return
        report = json.loads(report_path.read_text())
        try:
            os.kill(report['pid'], 0)
            report['process_alive'] = True
        except (ProcessLookupError, PermissionError):
            report['process_alive'] = False
        print(json.dumps(report, indent=2))
        return
    if not 5 <= args.sample_seconds <= 300:
        parser.error('sample-seconds must be 5..300')
    if not .5 <= args.control_seconds <= 5:
        parser.error('control-seconds must be .5..5')
    if args.force_smoke_failover and not args.smoke_seconds:
        parser.error('forced transitions are only allowed in a labelled smoke test')
    if args.max_rss_mib < 1:
        parser.error('max-rss-mib must be positive')
    if args.smoke_seconds:
        if args.smoke_seconds < 120:
            parser.error('smoke-seconds must be at least 120')
        total = args.smoke_seconds
        native = total / 2
    else:
        if not 48 <= args.hours <= 72 or not 1 <= args.native_hours < args.hours:
            parser.error('release soak requires 48..72 total hours and a nonempty native/container phase')
        total = args.hours * 3600
        native = args.native_hours * 3600
    # Keep an independent process lock as well as the shared fabric lock. Never
    # truncate an existing progress report before both nonblocking locks succeed.
    run.mkdir(parents=True, exist_ok=True)
    owner = exclusive_lock(run / 'network-soak.lock')
    try:
        lock = exclusive_lock(run / 'lab.lock')
        try:
            if report_path.exists():
                prior = json.loads(report_path.read_text())
                if not args.smoke_seconds and prior.get('status') in ('running', 'passed'):
                    raise RuntimeError('Existing release soak requires review; do not overwrite it')
                archived = report_path.with_name(report_path.stem + '-' + str(time.time_ns()) + '.json')
                archived.write_bytes(report_path.read_bytes())
            v = VPNLab(args.lab_root)
        except BaseException:
            lock.close()
            raise
    except BaseException:
        owner.close()
        raise
    creds = json.loads((v.run / 'credentials.json').read_text())
    v.routers['siteb'] = Router(v.root, 'api://127.0.0.1:55730', credentials_data=creds['siteb'])
    a = v.routers['sitea']
    report = {'pass': False, 'status': 'preparing', 'kind': 'smoke' if args.smoke_seconds else 'release', 'pid': os.getpid(), 'started_utc': time.time(), 'required_seconds': total, 'native_seconds': native, 'max_rss_bytes': args.max_rss_mib * 1024 * 1024, 'samples': 0, 'phase_samples': {'native': 0, 'container': 0}, 'production_access': False, 'failures': []}
    traffic = None
    before = None
    applied = False
    forwarded = False
    nat = None
    token = None
    forced_rule = None
    forced_phases = {}
    manifest = source_manifest()
    cli_spec = importlib.util.spec_from_file_location('network_soak_cli', ROOT / 'sdwan.py')
    cli = importlib.util.module_from_spec(cli_spec)
    cli_spec.loader.exec_module(cli)
    def apply(cfg):
        with (run / 'network-soak-apply.log').open('a') as log, contextlib.redirect_stdout(log):
            cli.apply(a, cfg, 'sdwan-overlay-sitea')
    def stop_container():
        row = read_container(a)
        if row and row.get('stopped') != 'true':
            a.call('container/stop', {'numbers': row['.id']}, 'POST')
        wait(lambda: read_container(a).get('stopped') == 'true' and not a.status().get('container', {}).get('active'))
    def web():
        connection = http.client.HTTPConnection('127.0.0.1', 45880, timeout=4)
        try:
            connection.request('GET', '/api/status', headers={'Authorization': 'Bearer ' + token})
            response = connection.getresponse()
            body = response.read(300000)
            assert response.status == 200 and len(body) < 300000, 'Bounded authenticated web status failed'
            return json.loads(body)
        finally:
            connection.close()
    def ready(active):
        state = a.status()
        try:
            choice = expected_selection(cfg, state)
            return state.get('container', {}).get('active', False) == active and state['selected'] == choice and all(x != 'none' for x in choice.values()) and len(state.get('overlay', {})) == 2 and all(x['healthy'] for x in state['overlay'].values())
        except (AssertionError, KeyError):
            return False
    def summarize(state):
        return {key: state.get(key) for key in ('uptime_seconds', 'error', 'selected', 'states', 'samples', 'overlay', 'vpn_egress', 'last_cleanup', 'events')}
    def stable_native():
        deadline = time.monotonic() + 240
        stable = None
        previous = None
        report['warmup_changes'] = []
        while time.monotonic() < deadline:
            state = a.status()
            report['last_status'] = {'sitea': summarize(state)}
            qualities = {key: value['state'] for key, value in state.get('states', {}).items()}
            if qualities != previous:
                report['warmup_changes'].append({'utc': time.time(), 'states': qualities})
                previous = qualities
            healthy = ready(False) and len(qualities) == 4 and all(value == 'healthy' for value in qualities.values())
            if healthy:
                if stable is None:
                    stable = time.monotonic()
                if time.monotonic() - stable >= 60:
                    return
            else:
                stable = None
            write_json(report_path, report)
            time.sleep(5)
        raise AssertionError('Four native WANs did not hold healthy SLA for 60 seconds within the 240-second fixture warm-up')
    def interrupted(signum, _frame):
        raise InterruptedError('Soak interrupted by signal ' + str(signum))
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    write_json(report_path, report)
    try:
        for name, router in v.routers.items():
            assert router.call('system/identity')['name'] == 'sdwan-overlay-' + name
            assert router.call('system/resource')['version'].split()[0] == '7.24.5'
        assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT).strip(), 'Freeze a reviewed clean Git commit before running the soak'
        report['commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['source_sha256'] = digest(json.dumps(manifest, sort_keys=True))
        if not args.smoke_seconds:
            gates = json.loads((args.lab_root / 'runtime/publication/final-native-tail-validation.json').read_text())
            assert gates['pass'], 'Finish current native acceptance gates first'
        row = read_container(a)
        built = next(x for x in json.loads((ROOT / 'dist/container/build-report.json').read_text()) if x['profile'] == 'web' and x['architecture'] == 'amd64')
        assert row and row['stopped'] == 'true', 'Use the existing stopped prepared container'
        assert row.get('image-id', '').removeprefix('sha256:') == built['image_config_sha256'], 'Prepared image differs from the frozen build'
        assert built['unit_coverage_source_sha256'] == source_digest(), 'Container source differs from its covered build'
        report['image_id'] = built['image_config_sha256']
        report['container_coverage_source_sha256'] = built['unit_coverage_source_sha256']
        before = a.read_file('sdwan-active.json')
        recovery = run / ('network-soak-smoke-before.json' if args.smoke_seconds else 'network-soak-before.json')
        write_json(recovery, {'before': json.loads(before), 'status': 'pending', 'pid': os.getpid()})
        recovery.chmod(0o600)
        cfg = json.loads((v.root / 'config/overlay-sitea-container.json').read_text())
        assert len(cfg['wans']) == 4 and len(cfg['overlay']['tunnels']) == 2
        applied = True
        apply(cfg)
        stop_container()
        wait(lambda: ready(False))
        traffic = VPNTraffic(v)
        traffic.prepare()
        traffic.add(a, 'ip/firewall/address-list', {'list': 'network-container-future-list', 'address': '198.19.100.1'})
        # Startup convergence is not measured, and cannot invalidate a transfer
        # that has not yet been created.
        stable_native()
        initial = a.status()['selected']
        streams = {
            'ordinary': traffic.stream(59410, 'sdwan-out-default:' + initial['default'], target='198.19.100.2', content_length=1000000000),
            'vpn': traffic.stream(59412, 'sdwan-out-vpn-targets:' + initial['vpn-targets'], content_length=1000000000),
            'branch': traffic.stream(59419, 'no-mark', target='10.201.1.2', content_length=1000000000),
        }
        report['stream_tuples'] = {label: flow.snapshot for label, flow in streams.items()}
        # Applying the fixture may renegotiate a standby PPP tunnel. Do not
        # count startup/reconnect convergence as a measured steady-state soak.
        nat = a.call('ip/firewall/nat/add', {'chain': 'dstnat', 'in-interface': 'ether1', 'src-address': '10.78.1.2', 'protocol': 'tcp', 'dst-address': '10.78.1.15', 'dst-port': '58880', 'action': 'dst-nat', 'to-addresses': '172.31.255.2', 'to-ports': '8080', 'comment': 'sdwan-network-soak', 'place-before': '0'}, 'POST')['ret']
        result = v.lab.qmp('sitea', 'human-monitor-command', {'command-line': 'hostfwd_add n1 tcp:127.0.0.1:45880-10.78.1.15:58880'})
        assert not result, 'Soak observer forwarding port is occupied'
        forwarded = True
        token = a.read_file(paths(cfg)['web_token'])
        baseline_files = {}
        configurations = {}
        for name, router in v.routers.items():
            configuration = router.read_file('sdwan-active.json')
            configurations[name] = json.loads(configuration)
            baseline_files[name] = {'sdwan-active.json': digest(configuration)}
            with tempfile.TemporaryDirectory(prefix='network-soak-source-') as folder:
                package = cli.bundle(json.loads(configuration), folder)
                for filename in cli.FILES:
                    expected = digest((package / filename).read_text())
                    assert digest(router.read_file(filename)) == expected, name + ': installed runtime differs from frozen source'
                    baseline_files[name][filename] = expected
        intent = a.read_file('sdwan-container-intent.json')
        started = time.monotonic()
        report.update(status='running', measured_started_utc=time.time(), phase='native', stream_ids=streams)
        write_json(report_path, report)
        active = False
        writes = None
        last_handles = dict(streams)
        cursors = {name: EventCursor(router.status(), configurations[name]) for name,router in v.routers.items()}
        flow_observer = FlowObserver(streams, {'ordinary':'default', 'vpn':'vpn-targets'}, time.monotonic(), tcp_stream, same_path)
        next_sample = 0
        last_control = time.monotonic()
        pending_intent_events = []
        backend_claim = False
        report['stream_handle_changes'] = {label: 0 for label in streams}
        report['wan_quality_samples'] = {}
        last_uptime = {}
        resources = {'rss_min_bytes': None, 'rss_max_bytes': 0, 'container_memory_max_bytes': 0, 'history_points_max': 0, 'process_io_available': None}
        with (run / ('network-soak-smoke-samples.jsonl' if args.smoke_seconds else 'network-soak-samples.jsonl')).open('a') as samples:
            while True:
                elapsed = time.monotonic() - started
                if elapsed >= total:
                    break
                if not active and elapsed >= native:
                    a.call('container/start', {'numbers': read_container(a)['.id']}, 'POST')
                    wait(lambda: ready(True))
                    active = True
                    backend_claim = True
                    wait(lambda: not web()['stale'] and web()['current']['actor'] == 'container')
                    writes = web()['resources']['write_bytes']
                    # A fresh process must publish one fenced ownership claim.
                    # No-write assertions apply within each steady phase, not
                    # across that explicit controller start/instance change.
                    report.update(phase='container', container_started_utc=time.time())
                phase = 'container' if active else 'native'
                now = time.monotonic()
                assert now-last_control <= 20, 'Control observation gap exceeded 20s; evidence is inconclusive'
                if args.force_smoke_failover:
                    phase_elapsed = elapsed - (native if active else 0)
                    forced = forced_phases.setdefault(phase, {})
                    if phase_elapsed >= 10 and not forced:
                        forced_rule = a.call('ip/firewall/filter/add', {'chain':'output', 'out-interface':'vpn-exit-wg', 'dst-address':'198.19.100.1', 'protocol':'tcp', 'dst-port':'58081-58083', 'action':'drop', 'comment':'sdwan-network-soak-forced', 'place-before':'0'}, 'POST')['ret']
                        forced['failed_at_seconds'] = elapsed
                    elif forced_rule and phase_elapsed >= 32:
                        a.call('ip/firewall/filter/' + forced_rule, method='DELETE')
                        forced_rule = None
                        forced['recovered_at_seconds'] = elapsed
                frames = {name:router.status() for name,router in v.routers.items()}
                connections = traffic.connections()
                verify = a.status()
                # A cutover between status and conntrack reads needs another
                # observation, not permission to retire an unrelated transfer.
                if verify.get('selected') != frames['sitea'].get('selected') or verify.get('events') != frames['sitea'].get('events'):
                    time.sleep(min(.2, args.control_seconds))
                    continue
                events = {}
                for name,frame in frames.items():
                    choice = expected_selection(configurations[name], frame)
                    events[name] = cursors[name].advance(frame, choice)
                    report.setdefault('last_status', {})[name] = summarize(frame)
                flow_observer.tick(frames['sitea'], events['sitea'], connections, now, traffic)
                report['traffic_observer'] = flow_observer.summary()
                report['forced_transitions'] = forced_phases
                pending_intent_events.extend(events['sitea'])
                next_intent = a.read_file('sdwan-container-intent.json')
                if next_intent != intent:
                    receipt = validate_intent(intent, next_intent, cfg, frames['sitea'], pending_intent_events, backend_claim)
                    report.setdefault('intent_transitions', []).append(dict(receipt, elapsed_seconds=elapsed, before_sha256=digest(intent), after_sha256=digest(next_intent)))
                    intent = next_intent
                    pending_intent_events.clear()
                    backend_claim = False
                    if active:
                        writes = web()['resources']['write_bytes']
                last_control = now
                report['control_samples'] = report.get('control_samples', 0) + 1
                report.update(elapsed_seconds=round(elapsed,3), checkpoint_utc=time.time())
                write_json(report_path, report)
                if elapsed < next_sample:
                    time.sleep(min(args.control_seconds, max(0,total-(time.monotonic()-started))))
                    continue
                next_sample = elapsed + args.sample_seconds
                assert source_manifest() == manifest, 'Frozen runtime or fixture source changed during soak'
                observation = {'elapsed_seconds': round(time.monotonic() - started, 3), 'phase': phase, 'nodes': {}}
                for name, router in v.routers.items():
                    state = frames[name]
                    report.setdefault('last_status', {})[name] = summarize(state)
                    assert not state.get('error'), name + ': controller error'
                    assert state.get('enabled') is True, name + ': controller scheduler disabled'
                    expected = 4 if name == 'hub' else 2
                    assert len(state.get('overlay', {})) == expected and all(x['healthy'] for x in state['overlay'].values()), name + ': inner SLA closed'
                    neighbors = router.call('routing/ospf/neighbor/print', {'.proplist': 'state'}, 'POST')
                    assert sum(x.get('state', '').lower() == 'full' for x in neighbors) == expected, name + ': OSPF adjacency lost'
                    if name == 'sitea':
                        assert state.get('container', {}).get('active', False) == active, 'Unexpected active backend'
                        assert len(state['states']) == 4, 'One of four WAN SLA reports is missing'
                        for key, detail in state['states'].items():
                            counts = report['wan_quality_samples'].setdefault(key, {})
                            quality = detail['state']
                            counts[quality] = counts.get(quality, 0) + 1
                    if report['samples'] % 20 == 0:
                        for filename, expected_hash in baseline_files[name].items():
                            assert digest(router.read_file(filename)) == expected_hash, name + ': installed source/config changed'
                    resource = router.call('system/resource/print', {'.proplist': 'uptime,cpu-load,free-memory,free-hdd-space,write-sect-since-reboot,write-sect-total'}, 'POST')[0]
                    # The textual uptime is recorded alongside fresh live state;
                    # the controller's numeric uptime detects unexpected reboots.
                    uptime = state.get('uptime_seconds')
                    assert type(uptime) is int, name + ': missing controller uptime'
                    assert uptime > last_uptime.get(name, -1), name + ': controller stalled or router rebooted'
                    last_uptime[name] = uptime
                    observation['nodes'][name] = {'selected': state['selected'], 'resources': resource, 'full_neighbors': expected}
                    if name == 'sitea':
                        observation['nodes'][name].update(states=state['states'], samples=state['samples'], events=state.get('events', []))
                observation['tcp_reply_bytes'] = dict(flow_observer.last_bytes)
                observation['stream_handles'] = {label:str(flow) for label,flow in streams.items()}
                observation['http_streams'] = {port:dict(stats) for port,stats in traffic.stream_stats.items()}
                observation['http_generations'] = {port:[dict(stats) for stats in generations] for port,generations in traffic.stream_generations.items()}
                if active:
                    data = web()
                    assert not data['stale'] and data['current']['actor'] == 'container'
                    assert len(data['current']['transports']) == 4 and len(data['current']['overlay']) == 2
                    assert all(x['healthy'] for x in data['current']['overlay'])
                    assert data['history_points'] <= 12 and data['resources']['rss_bytes'] > 0
                    if type(writes) is int:
                        assert data['resources']['write_bytes'] == writes, 'Container process wrote to persistent storage'
                    rss = data['resources']['rss_bytes']
                    assert rss <= report['max_rss_bytes'], 'Container exceeded the declared lab RSS budget'
                    resources['rss_min_bytes'] = rss if resources['rss_min_bytes'] is None else min(resources['rss_min_bytes'], rss)
                    resources['rss_max_bytes'] = max(resources['rss_max_bytes'], rss)
                    resources['history_points_max'] = max(resources['history_points_max'], data['history_points'])
                    resources['process_io_available'] = type(writes) is int
                    container = read_container(a)
                    assert container.get('image-id', '').removeprefix('sha256:') == report['image_id']
                    measured = a.call('container/print', {'.proplist': 'memory-current,cpu-usage', '.query': ['name=sdwan-container-controller']}, 'POST')[0]
                    resources['container_memory_max_bytes'] = max(resources['container_memory_max_bytes'], int(measured.get('memory-current', 0)))
                    observation['web_resources'] = data['resources']
                    observation['history_points'] = data['history_points']
                    observation['container'] = measured
                samples.write(json.dumps(observation, separators=(',', ':')) + '\n')
                samples.flush()
                report['samples'] += 1
                report['phase_samples'][phase] += 1
                report.update(elapsed_seconds=round(time.monotonic() - started, 3), checkpoint_utc=time.time(), resources=resources)
                write_json(report_path, report)
                time.sleep(min(args.control_seconds, max(0, total - (time.monotonic() - started))))
        assert active and all(x > 0 for x in report['phase_samples'].values())
        assert not flow_observer.pending, 'Unverified transition remains at measurement end'
        if args.force_smoke_failover:
            assert set(forced_phases) == {'native','container'} and all('recovered_at_seconds' in row for row in forced_phases.values()), 'Both forced smoke phases must recover'
            assert len(flow_observer.transitions) >= 4, 'Forced smoke did not prove failover/failback in both phases'
        report.update(elapsed_seconds=round(time.monotonic() - started, 3), status='restoring')
    except BaseException as error:
        report['status'] = 'failed'
        report['failures'].append(type(error).__name__ + ': ' + str(error))
        if traffic:
            try:
                ports = set(map(str, traffic.stream_stats))
                report['traffic_failure'] = {
                    'connections': [x for x in traffic.connections() if x.get('dst-port') in ports],
                    'http_streams': {port: dict(stats) for port, stats in traffic.stream_stats.items()},
                    'client_jobs': [x for x in traffic.b.call('system/script/job/print', {'.proplist': '.id,trace'}, 'POST') if any('/script:' + name + '/' in x.get('trace', '') for name in traffic.tasks)],
                }
                report.setdefault('last_status', {})['sitea'] = summarize(a.status())
            except BaseException as diagnostic_error:
                report['traffic_diagnostic_error'] = type(diagnostic_error).__name__
    finally:
        # Preserve failed/incomplete evidence. Never infer success from the VM's
        # uptime or the mere existence of a background process.
        try:
            if forced_rule:
                a.call('ip/firewall/filter/' + forced_rule, method='DELETE')
            if applied:
                stop_container()
            if forwarded:
                v.lab.qmp('sitea', 'human-monitor-command', {'command-line': 'hostfwd_remove n1 tcp:127.0.0.1:45880'})
            if nat:
                a.call('ip/firewall/nat/' + nat, method='DELETE')
            if traffic:
                traffic.close()
            if applied and before is not None:
                apply(json.loads(before))
                def restored():
                    state = a.status()
                    count = len(json.loads(before).get('overlay', {}).get('tunnels', []))
                    return not state.get('error') and not state.get('container', {}).get('active', False) and len(state.get('overlay', {})) == count and all(x['healthy'] for x in state.get('overlay', {}).values()) and json.loads(a.read_file('sdwan-active.json')) == json.loads(before)
                wait(restored)
                with tempfile.TemporaryDirectory(prefix='network-soak-restore-') as folder:
                    package = cli.bundle(json.loads(before), folder)
                    for filename in cli.FILES:
                        assert a.read_file(filename) == (package / filename).read_text(), 'Restored runtime differs: ' + filename
                write_json(recovery, {'status': 'restored', 'pid': os.getpid()})
            if report['status'] == 'restoring':
                report['pass'] = True
                report['status'] = 'passed'
        except BaseException as error:
            report['status'] = 'cleanup_failed'
            report['failures'].append(type(error).__name__ + ': ' + str(error))
        report['finished_utc'] = time.time()
        write_json(report_path, report)
        v.close()
        lock.close()
        owner.close()
    print(json.dumps({'status': report['status'], 'kind': report['kind'], 'samples': report['samples'], 'report': str(report_path)}), flush=True)
    if not report['pass']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
