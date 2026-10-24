#!/usr/bin/env python3
"""Read-only Rust smoke on the lab CHR; not in-container acceptance."""
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sdwan.router import Router

def main():
    post = json.loads((ROOT/'runtime/policies-postflight-results.json').read_text())
    assert len(post) == 6 and all(x['exit_code'] == 0 for x in post), 'Wait for native postflight'
    credentials = json.loads((ROOT/'runtime/credentials.json').read_text())['edge']
    run = ROOT/'runtime/container-shadow'
    run.mkdir(exist_ok=True)
    secret = run/'api-password'
    secret.write_text(credentials['password'])
    secret.chmod(0o600)
    settings = {'endpoint': '127.0.0.1:18728', 'identity': 'sdwan-edge',
                'username': credentials['username'], 'password_file': str(secret),
                'mode': 'shadow', 'poll_ms': 1000, 'metrics_every_seconds': 1}
    settings_path = run/'controller.json'
    settings_path.write_text(json.dumps(settings))
    executable = ROOT/'runtime/container-build/x86_64-unknown-linux-musl/release/sdwan-router-controller'
    router = Router(ROOT)
    def fingerprint():
        return {path: router.call(path) for path in
                ('ip/route', 'ip/firewall/mangle', 'ip/firewall/filter',
                 'routing/rule', 'system/scheduler', 'system/script', 'file')}
    before = fingerprint()
    initial_status = router.status()
    logfile = run/'stdout.jsonl'
    errfile = run/'stderr.txt'
    process = None
    try:
        with logfile.open('w') as out, errfile.open('w') as err:
            process = subprocess.Popen([str(executable), 'run', str(settings_path)], stdout=out, stderr=err)
            time.sleep(12)
            assert process.poll() is None, 'Rust controller exited unexpectedly'
            process.send_signal(signal.SIGTERM)
            process.wait(timeout=5)
            assert process.returncode == 0, 'SIGTERM did not exit cleanly'
        rows = [json.loads(line) for line in logfile.read_text().splitlines()]
        plans = [row for row in rows if row.get('mode') == 'shadow' and 'selected' in row]
        resources = [row['resources'] for row in rows if 'resources' in row]
        assert plans and plans[-1]['selected'] == initial_status['selected'], 'Rust/native decisions differ'
        assert all(row['writes'] == 0 for row in plans)
        assert resources and all(row['rss_bytes'] > 0 for row in resources)
        assert not errfile.read_text(), 'Inspect sanitized Rust error log'
        # Volatile counters/status fields are excluded; configuration only.
        volatile = {'bytes','packets','run-count','next-run','last-started','last-logged-in',
                    'expires-after','last-modified','creation-time','used','last-triggered',
                    'immediate-gw','active','unreachable','inactive','hw-offloaded'}
        def stable(value):
            if isinstance(value, list): return [stable(x) for x in value]
            if isinstance(value, dict): return {k: stable(v) for k,v in value.items() if k not in volatile}
            return value
        assert stable(before) == stable(fingerprint()), 'Router configuration changed during shadow run'
        report = {'pass': True, 'mode': 'shadow', 'execution': 'WSL static Linux binary talking read-only to CHR',
                  'in_container_acceptance': False, 'architecture': 'amd64',
                  'router_config_unchanged': True, 'plans_match_native': True,
                  'clean_sigterm': True, 'sample_count': len(resources),
                  'rss_min_bytes': min(r['rss_bytes'] for r in resources),
                  'rss_max_bytes': max(r['rss_bytes'] for r in resources),
                  'cpu_ticks_delta': resources[-1]['cpu_ticks'] - resources[0]['cpu_ticks'],
                  'ticks_per_second': os.sysconf('SC_CLK_TCK'), 'sample_interval_seconds': len(resources)-1}
        (ROOT/'runtime/container-shadow-validation.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report))
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        secret.unlink(missing_ok=True)
        settings_path.unlink(missing_ok=True)
        router.close()

if __name__ == '__main__': main()
