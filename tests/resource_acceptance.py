#!/usr/bin/env python3
"""Loopback CHR only: exact file queries, no-op writes and retention guards.

Uses synthetic files on isp1, never changes its network configuration. Timing
reads use edge's existing catalog. No worker/script is installed by this suite.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sdwan.router import Router
from sdwan.maintenance import prune_backups


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credentials', type=Path, default=ROOT/'runtime/credentials.json')
    args = parser.parse_args()
    credentials = json.loads(args.credentials.read_text())
    edge = Router(ROOT, 'api://127.0.0.1:18728', credentials_data=credentials['edge'])
    provider = Router(ROOT, 'http://127.0.0.1:18081', credentials_data=credentials['isp1'])
    checks = []
    owned = []
    report = {'pass': False, 'checks': checks, 'production_modified': False}

    def passed(name):
        checks.append({'check': name, 'pass': True})
        print('PASS ' + name, flush=True)

    def write(name, text):
        if name not in owned:
            assert not provider.file_records([name]), 'Fixture would replace an existing file'
            owned.append(name)
        return provider.upload(name, text)

    try:
        assert edge.call('system/identity')['name'] == 'sdwan-edge'
        assert provider.call('system/identity')['name'] == 'sdwan-isp1'
        assert not provider.file_records(['sdwan-deploy-current.json'])
        full = []
        exact = []
        for _ in range(3):
            begin = time.monotonic()
            rows = edge.call('file/print', {'.proplist': '.id,name'}, 'POST')
            full.append(time.monotonic() - begin)
            begin = time.monotonic()
            edge.read_file('sdwan-deploy-current.json')
            exact.append(time.monotonic() - begin)
        report['timing'] = {'catalog_files': len(rows), 'full_catalog_median_seconds': statistics.median(full),
                            'filtered_read_median_seconds': statistics.median(exact)}
        passed('native API reads current journal pointer through exact name queries')

        unrelated = 'sdwan-resource-preserve-' + secrets.token_hex(5) + '.txt'
        assert write(unrelated, 'synthetic-unchanged-data') is True
        changes = []
        original = provider.call

        def counted(path, data=None, method=None):
            if method in ('PATCH', 'PUT', 'DELETE'): changes.append((path, method))
            return original(path, data, method)

        provider.call = counted
        assert provider.upload(unrelated, 'synthetic-unchanged-data') is False
        assert not changes
        passed('identical REST upload performs no create/set/delete operation')

        tokens = [secrets.token_hex(12) for _ in range(4)]
        states = {}
        start = datetime.now(timezone.utc)
        for index, token in enumerate(tokens):
            state = {'token': token, 'identity': 'sdwan-isp1', 'phase': 'committed', 'backup_ready': True,
                     'created_utc': (start + timedelta(seconds=index)).isoformat(), 'previous': {}}
            states[token] = state
            write('sdwan-txn-' + token + '.json', json.dumps(state))
            write('sdwan-before-' + token + '.backup', 'synthetic-backup-fixture')
            write('sdwan-prev-' + token + '-0', 'synthetic-previous-fixture')
            write('sdwan-infra-prev-' + token + '-0', 'synthetic-framework-fixture')
        pointer = {'token': tokens[0], 'path': 'sdwan-txn-' + tokens[0] + '.json'}
        write('sdwan-deploy-current.json', json.dumps(pointer))
        changes.clear()
        plan = prune_backups(provider, 'sdwan-isp1', 2)
        assert not changes and not plan['blocked']
        assert len(plan['delete']) == 4 and {r['token'] for r in plan['delete']} == {tokens[1]}
        passed('dry-run writes nothing and protects current plus two newest backup groups')

        states[tokens[1]]['phase'] = 'applying'
        write('sdwan-txn-' + tokens[1] + '.json', json.dumps(states[tokens[1]]))
        changes.clear()
        try: prune_backups(provider, 'sdwan-isp1', 2, execute=True)
        except ValueError as error: assert 'blocked' in str(error)
        else: raise AssertionError('Pending journal did not block deletion')
        assert not changes
        passed('pending synthetic transaction blocks execute before any deletion')
        states[tokens[1]]['phase'] = 'committed'
        write('sdwan-txn-' + tokens[1] + '.json', json.dumps(states[tokens[1]]))

        states[tokens[0]]['previous'] = {'previous-file': 'sdwan-prev-' + tokens[1] + '-0'}
        write('sdwan-txn-' + tokens[0] + '.json', json.dumps(states[tokens[0]]))
        assert not prune_backups(provider, 'sdwan-isp1', 2)['delete']
        passed('kept recovery manifest protects dependencies in another transaction')
        states[tokens[0]]['previous'] = {}
        write('sdwan-txn-' + tokens[0] + '.json', json.dumps(states[tokens[0]]))
        result = prune_backups(provider, 'sdwan-isp1', 2, execute=True)
        assert result['removed_files'] == 4
        assert provider.read_file(unrelated) == 'synthetic-unchanged-data'
        assert provider.read_file(pointer['path'])
        for token in (tokens[0], tokens[2], tokens[3]):
            assert provider.file_records(['sdwan-before-' + token + '.backup'])
        passed('execute removes only obsolete owned group and preserves unrelated/current files')
        report['pass'] = True
    finally:
        for name in reversed(owned):
            for row in provider.file_records([name]):
                provider.call('file/' + row['.id'], method='DELETE')
        report['fixtures_removed'] = not provider.file_records(owned)
        edge.close(); provider.close()
        (ROOT/'runtime').mkdir(exist_ok=True)
        (ROOT/'runtime/resource-acceptance.json').write_text(json.dumps(report, indent=2) + '\n')
    assert report['fixtures_removed']


if __name__ == '__main__': main()
