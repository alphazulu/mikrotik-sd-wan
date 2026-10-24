#!/usr/bin/env python3
"""Optional live Internet check, separate from deterministic lab acceptance."""
import importlib.util
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sdwan_lab', ROOT / 'lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

report = {'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'checks': []}
try:
    for source in ('192.168.50.101', '192.168.50.102'):
        data = {'url': 'https://mikrotik.com/', 'output': 'none',
                'check-certificate': 'yes', 'src-address': source}
        result = lab.api('client', 'tool/fetch', data, 'POST')
        success = any(r.get('status') == 'finished' and r.get('code') == '200' for r in result)
        report['checks'].append({'source': source, 'url': data['url'], 'certificate_verified': True,
                                 'pass': success, 'detail': result})
        if not success:
            raise RuntimeError(f'{source}: HTTPS did not complete successfully')
        print(f'PASS {source}: DNS + HTTPS to mikrotik.com, certificate verified', flush=True)
except Exception as exc:
    report['checks'].append({'check': 'live Internet interrupted', 'pass': False, 'detail': str(exc)})
    raise
finally:
    lab.save(lab.RUN / 'internet.json', report)
