import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .config import validate
from .runtime import Lease, Run, atomic_json, install_signals, checked


def main():
    p = argparse.ArgumentParser(description='Isolated external lab tools; no production router control')
    p.add_argument('command', choices=('check', 'run', 'status', 'recover'))
    p.add_argument('--config', type=Path)
    p.add_argument('--workspace', type=Path, default=Path('runtime/labtools'))
    p.add_argument('--run-id')
    p.add_argument('--json', action='store_true', help='Print the complete report instead of a summary')
    args = p.parse_args()
    if args.command == 'status':
        path = args.workspace/'owner.json'
        print(path.read_text() if path.exists() else '{"state":"not_started"}')
        return 0
    if args.command in ('check', 'run'):
        if not args.config: p.error('--config is required')
        cfg = validate(json.loads(args.config.read_text()))
        for key, value in cfg['tools'].items():
            if '/' in value and not Path(value).is_absolute(): value = str((args.config.parent/value).resolve())
            cfg['tools'][key] = shutil.which(value) or value
        needed = {'ip', 'ethtool', 'ss', 'tc'}
        for w in cfg['workloads']:
            if w['kind'] in ('tcp', 'udp'): needed.add(cfg['tools']['iperf3'])
            elif w['kind'] == 'cps': needed.add(cfg['tools']['cc'])
            else: needed.update(('tcpdump', cfg['tools']['tcpreplay']))
        missing = sorted(t for t in needed if not shutil.which(t))
        versions = {}
        for tool in set(cfg['tools'].values()) & needed:
            if shutil.which(tool):
                r = checked([tool, '--version'], timeout=5)
                versions[tool] = (r.stdout+r.stderr).strip()
        if args.command == 'check':
            print(json.dumps({'valid_config': True, 'missing_tools': missing, 'tool_versions': versions, 'config': cfg}, indent=2))
            return 1 if missing else 0
        if missing: raise RuntimeError('Missing tools: '+', '.join(missing))
        if os.geteuid(): raise RuntimeError('Network namespace calibration requires root on the dedicated lab host')
    if not args.run_id: p.error('--run-id is required')
    install_signals()
    with Lease(args.workspace) as lease:
        run = Run(lease, args.run_id, cfg if args.command == 'run' else None, recover=args.command == 'recover')
        if args.command == 'recover':
            passed = run.cleanup()
            result = {'recovery_pass': passed, 'original_report_preserved': True, 'errors': run.data['cleanup_errors']}
            atomic_json(run.folder/'recovery.json', result)
        else:
            from .bench import execute
            run.data['tool_versions'] = versions; run.save()
            result = execute(run, cfg)
        summary = {'run_id': args.run_id, 'report_folder': str(run.folder),
                   **{k: result[k] for k in ('status','pass','cleanup_pass','recovery_pass','error') if k in result}}
        print(json.dumps(result if args.json else summary, indent=2))
        return 0 if result.get('pass', result.get('recovery_pass')) else 1


if __name__ == '__main__':
    try: raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        raise SystemExit(2)
