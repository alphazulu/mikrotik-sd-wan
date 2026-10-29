from __future__ import annotations
import hashlib
import ipaddress
import json
import math
from pathlib import Path
import re
import statistics
import struct
import threading
import time

from .runtime import checked, atomic_json


def cpu_snapshot():
    return {p[0]: list(map(int, p[1:9])) for p in map(str.split, Path('/proc/stat').read_text().splitlines())
            if p and p[0].startswith('cpu') and p[0] != 'cpu'}


class Sampler:
    def __init__(self):
        self.rows = []; self.event = threading.Event(); self.thread = threading.Thread(target=self.loop)

    def loop(self):
        before = cpu_snapshot()
        while not self.event.wait(.2):
            after = cpu_snapshot(); cores = {}
            for name in before.keys() & after.keys():
                delta = [b-a for a,b in zip(before[name], after[name])]; total = sum(delta)
                cores[name] = {'busy': 100 * (total-delta[3]-delta[4])/total if total else 0,
                               'steal': 100 * delta[7]/total if total else 0}
            self.rows.append({'monotonic': time.monotonic(), 'cores': cores}); before = after

    def __enter__(self): self.thread.start(); return self
    def __exit__(self, *args): self.event.set(); self.thread.join()

    def summary(self):
        if not self.rows: raise RuntimeError('Missing CPU samples')
        result = {}
        for name in self.rows[0]['cores']:
            values = sorted(r['cores'][name]['busy'] for r in self.rows)
            result[name] = {'p95': values[math.ceil(.95*len(values))-1], 'max': max(values),
                            'steal_max': max(r['cores'][name]['steal'] for r in self.rows)}
        return result


def wait_until(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.05)
    raise RuntimeError('Readiness deadline expired')


def wait_child(child, timeout):
    code = child.wait(timeout=timeout)
    if code: raise RuntimeError(f'Child {child.pid} exited with {code}; inspect raw logs')


def pcap_metrics(path, warmup, seconds):
    first = last = None; count = measured = totalbytes = 0; sizes = {}
    with Path(path).open('rb') as stream:
        if stream.read(24)[:4] != b'\xd4\xc3\xb2\xa1': raise ValueError('Expected little-endian Ethernet pcap')
        while header := stream.read(16):
            if len(header) != 16: raise ValueError('Truncated pcap header')
            sec, usec, captured, original = struct.unpack('<IIII', header)
            if captured > 65535: raise ValueError('Invalid pcap record length')
            frame = stream.read(captured)
            if len(frame) != captured or frame[12:14] != b'\x88\xb5': raise ValueError('Unexpected capture data')
            stamp = sec + usec / 1e6
            if first is None: first = stamp
            if last is not None and stamp < last: raise ValueError('Capture clock regressed')
            last = stamp; count += 1
            if first + warmup <= stamp < first + warmup + seconds:
                measured += 1; totalbytes += original; sizes[str(original)] = sizes.get(str(original), 0) + 1
    if first is None or last < first + warmup + seconds: raise ValueError('Incomplete receive window')
    return {'capture_packets': count, 'receiver_pps': measured / seconds,
            'receiver_l2_bytes_per_second': totalbytes / seconds, 'size_distribution': sizes}


class Network:
    def __init__(self, run, subnet):
        self.run = run
        self.names = [run.namespace('a'), run.namespace('b')]
        self.ips = list(map(str, ipaddress.ip_network(subnet).hosts()))
        # Create both ends INSIDE already-journaled namespaces; no host veth is left behind.
        checked(['ip', '-n', self.names[0], 'link', 'add', 'eth0', 'type', 'veth', 'peer', 'name', 'eth0', 'netns', self.names[1]])
        for i in range(2):
            self.call(i, ['sysctl', '-qw', 'net.ipv6.conf.eth0.disable_ipv6=1'])
            self.call(i, ['ip', 'link', 'set', 'lo', 'up'])
            self.call(i, ['ip', 'link', 'set', 'eth0', 'address', f'02:00:00:50:00:0{i+1}'])
            self.call(i, ['ip', 'addr', 'add', self.ips[i]+'/30', 'dev', 'eth0'])
            self.call(i, ['ip', 'link', 'set', 'eth0', 'up'])
            self.call(i, ['ethtool', '-K', 'eth0', 'tso', 'off', 'gso', 'off', 'gro', 'off'])

    def argv(self, i, args): return ['ip', 'netns', 'exec', self.names[i]] + list(map(str, args))
    def call(self, i, args): return checked(self.argv(i, args))
    def stats(self, i): return json.loads(self.call(i, ['ip', '-j', '-s', 'link', 'show', 'eth0']).stdout)[0]['stats64']
    def delay(self, ms):
        for i in range(2):
            if ms: self.call(i, ['tc', 'qdisc', 'replace', 'dev', 'eth0', 'root', 'netem', 'delay', str(ms)+'ms'])
            else: self.call(i, ['tc', 'qdisc', 'replace', 'dev', 'eth0', 'root', 'pfifo', 'limit', '1000'])


def iperf_case(run, net, cfg, w, label):
    tool = cfg['tools']['iperf3']
    server = run.spawn(net.argv(1, [tool, '-s', '-1', '-B', net.ips[1], '-p', '5201', '-J']), label+'-server')
    wait_until(lambda: server.poll() is None and ':5201' in net.call(1, ['ss', '-H', '-ltn']).stdout)
    args = [tool, '-c', net.ips[1], '-B', net.ips[0], '-p', '5201', '-t', str(cfg['seconds']), '-O', str(cfg['warmup_seconds']), '-J', '--get-server-output']
    if w['direction'] == 'reverse': args.append('-R')
    if w['direction'] == 'bidir': args.append('--bidir')
    if w['kind'] == 'udp': args += ['-u', '-l', str(w['payload_bytes']), '-b', str(w['offered_pps'] * w['payload_bytes'] * 8)]
    else: args += ['-P', str(w['parallel']), '-b', str(w['offered_bps']//w['parallel'])]
    child = run.spawn(net.argv(0, args), label+'-client')
    wait_child(child, cfg['seconds']+cfg['warmup_seconds']+15); wait_child(server, 5)
    value = json.loads((run.folder/(label+'-client.stdout')).read_text())
    if value.get('error'): raise RuntimeError(value['error'])
    end = value['end']
    if w['kind'] == 'udp':
        row = end['sum_received']
        metrics = {'receiver_pps': (row['packets']-row['lost_packets'])/row['seconds'], 'loss_percent': row['lost_percent']}
        return metrics, metrics['receiver_pps'] >= w['minimum_pps'] and metrics['loss_percent'] <= cfg['criteria']['loss_percent_max']
    metrics = {'receiver_bps': end['sum_received']['bits_per_second']}
    if w['direction'] == 'bidir': metrics['reverse_receiver_bps'] = end['sum_received_bidir_reverse']['bits_per_second']
    return metrics, all(v >= w['minimum_bps'] for v in metrics.values())


def cps_build(run, cfg, w, label):
    source = Path(__file__).with_name('cps.c'); binary = run.folder/(label+'-cps')
    defines = {'BENCH_RATE': w['rate'], 'BENCH_WARMUP': cfg['warmup_seconds'],
               'BENCH_SECONDS': cfg['seconds'], 'BENCH_CONCURRENCY': w['concurrency']}
    result = checked([cfg['tools']['cc'], '-O2', '-Wall', '-Wextra', '-Werror'] +
                     [f'-D{k}={v}' for k,v in defines.items()] + [source, '-o', binary], timeout=60)
    (run.folder/(label+'-compile.log')).write_text(result.stdout+result.stderr)
    atomic_json(run.folder/(label+'-build.json'), {'defines': defines, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest()})
    return binary


def cps_case(run, net, cfg, w, label, binary, port):
    direction = int(w['direction'] == 'reverse')
    server = run.spawn(net.argv(1-direction, [binary, 'server', net.ips[1-direction], port]), label+'-server')
    wait_until(lambda: server.poll() is None and 'ready' in (run.folder/(label+'-server.stdout')).read_text())
    child = run.spawn(net.argv(direction, [binary, 'client', net.ips[1-direction], port]), label+'-client')
    wait_child(child, cfg['seconds']+cfg['warmup_seconds']+10); run.stop(server.pid)
    value = json.loads((run.folder/(label+'-client.stdout')).read_text())
    peer = json.loads((run.folder/(label+'-server.stdout')).read_text().splitlines()[-1])
    if peer['accepted'] != value['attempts'] or peer['completed'] != value['echo_success']: raise RuntimeError('CPS endpoint counts disagree')
    metrics = {k: value[k] for k in ('successful_cps', 'peak_active', 'error_count', 'maximum_schedule_lateness_seconds')}
    return metrics, value['successful_cps'] >= w['minimum_cps'] and not value['error_count'] and not peer['errors'] and value['maximum_schedule_lateness_seconds'] <= .1 and value['peak_active'] <= w['concurrency']


def imix_case(run, net, cfg, w, label):
    direction = int(w['direction'] == 'reverse'); sizes = [n-4 for n in w['frame_sizes_with_fcs']]
    source = run.folder/(label+'-source.pcap'); capture = run.folder/(label+'-receive.pcap')
    count = len(sizes)*100
    with source.open('wb') as f:
        f.write(struct.pack('<IHHIIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for i in range(count):
            n = sizes[i%len(sizes)]; dst = bytes.fromhex(f'02000050000{2-direction}'); src = bytes.fromhex(f'02000050000{1+direction}')
            frame = dst+src+b'\x88\xb5'+struct.pack('!I', i)+bytes(n-18)
            f.write(struct.pack('<IIII', 0, i, n, n)+frame)
    receiver = run.spawn(net.argv(1-direction, ['tcpdump', '-n', '-i', 'eth0', '-s', '96', '-B', '4096', '-w', capture, 'ether', 'proto', '0x88b5']), label+'-receiver')
    wait_until(lambda: receiver.poll() is None and 'listening on' in (run.folder/(label+'-receiver.stderr')).read_text())
    before = net.stats(direction)['tx']['packets']
    loops = math.ceil(w['offered_pps']*(cfg['warmup_seconds']+cfg['seconds']+1)/count)
    child = run.spawn(net.argv(direction, [cfg['tools']['tcpreplay'], '-i', 'eth0', '-K', '--timer=nano', '--pps='+str(w['offered_pps']), '--pps-multi='+str(w['batch']), '--loop='+str(loops), source]), label+'-sender')
    wait_child(child, cfg['seconds']+cfg['warmup_seconds']+15)
    time.sleep(2); run.stop(receiver.pid)
    value = pcap_metrics(capture, cfg['warmup_seconds'], cfg['seconds'])
    sent = net.stats(direction)['tx']['packets']-before
    if sent <= 0 or value['capture_packets'] > sent: raise RuntimeError('Invalid IMIX counters')
    value['loss_percent'] = 100*(sent-value['capture_packets'])/sent
    match = re.search(r'(\d+) packets dropped by kernel', (run.folder/(label+'-receiver.stderr')).read_text())
    if not match: raise RuntimeError('Missing kernel capture drop counter')
    value['capture_kernel_drops'] = int(match[1])
    return value, value['receiver_pps'] >= w['minimum_pps'] and value['loss_percent'] <= cfg['criteria']['loss_percent_max'] and not value['capture_kernel_drops']


def execute(run, cfg):
    report = {'status': 'starting', 'pass': False, 'capacity_validated': False, 'physical_wire_pps_measured': False,
              'scope': 'External isolated generator calibration only; no RouterOS controller or DUT changes', 'config': cfg, 'runs': [],
              'cpu_scope': 'Entire case including setup/warmup and receiver drain; raw monotonic samples retained',
              'tool_versions': run.data.get('tool_versions', {})}
    path = run.folder/'report.json'
    try:
        net = Network(run, cfg['subnet'])
        report['conditions'] = {'cpu': checked(['lscpu', '-J']).stdout, 'kernel': checked(['uname', '-a']).stdout,
                                'offloads': [net.call(i, ['ethtool', '-k', 'eth0']).stdout for i in range(2)],
                                'tcp_settings': [net.call(i, ['sysctl', 'net.ipv4.ip_local_port_range', 'net.ipv4.tcp_max_tw_buckets']).stdout for i in range(2)]}
        for index, w in enumerate(cfg['workloads']):
            net.delay(w.get('delay_ms', 0))
            binary = cps_build(run, cfg, w, 'case'+str(index)) if w['kind'] == 'cps' else None
            for repeat in range(cfg['repeats']):
                label = f'{index}-{repeat}'; report.update(status='running', current_case=label); atomic_json(path, report)
                with Sampler() as cpu:
                    if w['kind'] in ('tcp', 'udp'): metrics, passed = iperf_case(run, net, cfg, w, label)
                    elif w['kind'] == 'cps': metrics, passed = cps_case(run, net, cfg, w, label, binary, 5202+index*5+repeat)
                    else: metrics, passed = imix_case(run, net, cfg, w, label)
                cores = cpu.summary(); peak = max(v['p95'] for v in cores.values()); atomic_json(run.folder/(label+'-cpu.json'), cpu.rows)
                passed = passed and peak <= cfg['criteria']['cpu_p95_max']
                report['runs'].append({'case': index, 'repeat': repeat, 'metrics': metrics, 'cpu_per_core': cores, 'pass': passed})
                atomic_json(path, report)
                if not passed: raise RuntimeError('Declared calibration criterion failed: '+label)
        variations = {}
        for index in range(len(cfg['workloads'])):
            rows = [r['metrics'] for r in report['runs'] if r['case'] == index]
            for metric in ('receiver_bps', 'reverse_receiver_bps', 'receiver_pps', 'successful_cps'):
                if metric not in rows[0]: continue
                values = [r[metric] for r in rows]; median = statistics.median(values)
                variations[f'{index}/{metric}'] = 100*(max(values)-min(values))/median if median else math.inf
        report.update(status='completed', variations_percent=variations)
        report['pass'] = all(v <= cfg['criteria']['variation_percent_max'] for v in variations.values())
    except BaseException as error:
        report.update(status='failed', error=type(error).__name__+': '+str(error))
    finally:
        report['cleanup_pass'] = run.cleanup()
        if not report['cleanup_pass']: report.update(status='cleanup_failed', **{'pass': False})
        atomic_json(path, report)
    return report
