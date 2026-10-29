"""Portable, source-bound attestation of an already completed local soak.

This never starts a router/test, confirms a deployment or authorizes a release.
Run attest on the original soak host after its process and locks are released.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import subprocess
import types
from .runtime import atomic_json


def digest(data):return hashlib.sha256(data).hexdigest()
def finite(value):return type(value) in (int,float) and math.isfinite(value)


def completed(report):
    if not isinstance(report,dict):raise ValueError('Expected soak report object')
    phases=report.get('phase_samples',{})
    valid=(report.get('status')=='passed' and report.get('pass') is True and report.get('kind')=='release' and report.get('failures')==[]
           and finite(report.get('required_seconds')) and report['required_seconds']>=172800
           and finite(report.get('elapsed_seconds')) and report['elapsed_seconds']>=report['required_seconds']
           and finite(report.get('native_seconds')) and report['native_seconds']>=86400 and report['required_seconds']-report['native_seconds']>=86400
           and isinstance(phases,dict) and all(type(phases.get(key)) is int and phases[key]>0 for key in ('native','container')))
    if not valid:raise ValueError('Full original48h acceptance and restoration must finish before DUT comparison')
    if type(report.get('pid')) is not int or report['pid']<=0:raise ValueError('Soak PID missing')
    if not all(finite(report.get(key)) for key in ('measured_started_utc','container_started_utc','finished_utc')) or not report['measured_started_utc']<=report['container_started_utc']<=report['finished_utc']:raise ValueError('Soak phase timeline incomplete')


def match_attestation(attestation,report_bytes,plan):
    report=json.loads(report_bytes);completed(report)
    if type(attestation.get('schema_version')) is not int or attestation.get('schema_version')!=1 or attestation.get('ready') is not True or attestation.get('soak_report_sha256')!=digest(report_bytes):raise ValueError('Missing or stale acceptance attestation')
    if any(attestation.get(key) is not True for key in ('process_exited','locks_released','restoration_verified','coverage_verified','frozen_source_verified')):raise ValueError('Acceptance cleanup/source evidence incomplete')
    for key in ('commit','source_sha256','image_id','container_coverage_source_sha256','pid'):
        if attestation.get(key)!=report.get(key):raise ValueError('Attestation differs from this soak run: '+key)
    bindings=plan['bindings']
    if attestation['container_coverage_source_sha256']!=bindings['controller_source_sha256'] or attestation['image_id']!=bindings['images']['web']['image_config_sha256']:raise ValueError('Soak runtime image/covered source differs from comparison plan')
    if attestation.get('native_sources')!=bindings['native_sources']:raise ValueError('Native runtime differs from the accepted soak source')
    return True


def lock_free(path):
    try:
        with path.open('rb') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(handle,fcntl.LOCK_UN)
        return True
    except (OSError,BlockingIOError):return False


def attest(report_path,source,coverage_path):
    report_path=Path(report_path).resolve();source=Path(source).resolve();report_bytes=report_path.read_bytes();report=json.loads(report_bytes);completed(report)
    recovery=json.loads((report_path.parent/'network-soak-before.json').read_text())
    if recovery.get('status')!='restored' or recovery.get('pid')!=report['pid']:raise ValueError('Restoration not confirmed for this PID')
    if Path('/proc',str(report['pid'])).exists():raise ValueError('Original soak process is still alive')
    if not all(lock_free(report_path.parent/name) for name in ('network-soak.lock','lab.lock')):raise ValueError('Original soak/fabric locks are busy or missing')
    def git(*args):return subprocess.check_output(['git',*args],cwd=source)
    if git('rev-parse','HEAD').decode().strip()!=report['commit'] or git('status','--porcelain').strip():raise ValueError('Frozen source commit/worktree changed')
    names=sorted(filter(None,git('ls-files','-z').decode().split('\0')))
    manifest={name:digest((source/name).read_bytes()) for name in names}
    if digest(json.dumps(manifest,sort_keys=True).encode())!=report['source_sha256']:raise ValueError('Frozen source manifest differs from this soak')
    checker=source/'tools/container_checks.py';module=types.ModuleType('accepted_container_source');module.__file__=str(checker)
    exec(compile(checker.read_bytes(),str(checker),'exec'),module.__dict__)
    covered=module.source_digest(source);coverage_bytes=Path(coverage_path).read_bytes();coverage=json.loads(coverage_bytes)
    if covered!=report['container_coverage_source_sha256'] or coverage.get('pass') is not True or coverage.get('source_sha256')!=covered:raise ValueError('Exact-source unit coverage evidence differs')
    native={name.removeprefix('native/'):value for name,value in manifest.items() if name.startswith('native/') and name.endswith('.rsc')}
    return {'schema_version':1,'ready':True,'generated_utc':datetime.now(timezone.utc).isoformat(),'soak_report_sha256':digest(report_bytes),'coverage_report_sha256':digest(coverage_bytes),'process_exited':True,'locks_released':True,'restoration_verified':True,'coverage_verified':True,'frozen_source_verified':True,'native_sources':native,**{key:report[key] for key in ('commit','source_sha256','image_id','container_coverage_source_sha256','pid')},'scope':'completed source-bound soak and restoration; independent cleanup/release review remains separate'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--soak-report',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--coverage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    proof=attest(a.soak_report,a.source,a.coverage)
    if a.output.exists():raise FileExistsError('Use a new attestation filename')
    a.output.parent.mkdir(parents=True,exist_ok=True);atomic_json(a.output,proof);print(json.dumps({'ready':True,'soak_report_sha256':proof['soak_report_sha256']}));return 0

if __name__=='__main__':raise SystemExit(main())
