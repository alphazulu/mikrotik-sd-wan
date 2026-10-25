#!/usr/bin/env python3
"""Mandatory exact-source unit coverage for base Rust, web Rust and browser JS."""
from __future__ import annotations
import argparse,hashlib,json,os,re,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
COV_VERSION='0.9.1'
IGNORED={'target','runtime','build','dist','__pycache__'}

def source_digest(root=ROOT):
    folder=root/'container-controller'
    paths=[]
    for directory,children,names in os.walk(folder):
        children[:]=[name for name in children if name not in IGNORED]
        paths.extend(Path(directory)/name for name in names if not name.endswith('.pyc'))
    paths += [root/'tools/container_checks.py',root/'tools/node_coverage_reporter.cjs',root/'tools/install_container_test_tools.py']
    digest=hashlib.sha256()
    for path in sorted(paths):
        name=path.relative_to(root).as_posix().encode();data=path.read_bytes()
        digest.update(len(name).to_bytes(8,'big')+name+len(data).to_bytes(8,'big')+data)
    return digest.hexdigest()

def module_only(path):
    text=re.sub(r'//[^\n]*','',path.read_text())
    text=re.sub(r'#\[[^\]]*\]','',text)
    text=re.sub(r'(?:pub\s+)?mod\s+\w+\s*;','',text)
    return not text.strip()

def rust_summary(data,profile,root=ROOT):
    expected={p.resolve() for p in (root/'container-controller/src').rglob('*.rs') if not module_only(p) and not (profile=='base' and 'web' in p.relative_to(root/'container-controller/src').parts)}
    files={Path(f['filename']).resolve():f['summary'] for section in data['data'] for f in section['files'] if Path(f['filename']).resolve() in expected}
    if expected-files.keys():raise ValueError('Unmeasured Rust runtime files: '+', '.join(str(p.relative_to(root)) for p in sorted(expected-files.keys())))
    result={}
    for path,summary in files.items():
        for metric in ('lines','functions'):
            if not summary[metric]['count'] or summary[metric]['covered']!=summary[metric]['count']:raise ValueError(f'{path.relative_to(root)}: {metric} coverage {summary[metric]["covered"]}/{summary[metric]["count"]}, requires 100%')
        result[path.relative_to(root).as_posix()]={k:summary[k] for k in ('lines','functions','regions','branches')}
    return result

def js_summary(events,root=ROOT):
    expected={p.resolve() for p in (root/'container-controller/web').rglob('*') if p.suffix in ('.js','.mjs','.cjs')}
    summaries=[e['coverage'] for e in events if 'coverage' in e]
    if len(summaries)!=1 or any('failure' in e for e in events):raise ValueError('Missing/ambiguous Node coverage event or failed JS tests')
    files={Path(f['path']).resolve():f for f in summaries[0]['files'] if Path(f['path']).resolve() in expected}
    if expected-files.keys():raise ValueError('Unmeasured browser runtime files')
    for path,row in files.items():
        for label in ('Line','Function'):
            if not row['total'+label+'Count'] or row['covered'+label+'Count']!=row['total'+label+'Count']:raise ValueError(f'{path.relative_to(root)}: {label.lower()} coverage requires 100%')
    return {p.relative_to(root).as_posix():f for p,f in files.items()}

def tool_environment():
    env=os.environ.copy()
    for key,relative in {'CARGO_HOME':'runtime/toolchains/cargo','RUSTUP_HOME':'runtime/toolchains/rustup'}.items():env.setdefault(key,str(ROOT/relative))
    env['PATH']=str(Path(env['CARGO_HOME'])/'bin')+os.pathsep+env.get('PATH','')
    for key in ('RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS','LLVM_PROFILE_FILE'):env.pop(key,None)
    executable=env.get('SDWAN_LLVM_COV') or shutil.which('cargo-llvm-cov',path=env['PATH']) or str(ROOT/f'runtime/toolchains/coverage/{COV_VERSION}/cargo-llvm-cov')
    if not Path(executable).is_file():raise ValueError('Install pinned coverage tooling: python3 tools/install_container_test_tools.py')
    version=subprocess.check_output([executable,'llvm-cov','--version'],env=env,text=True).strip()
    if version!='cargo-llvm-cov '+COV_VERSION:raise ValueError('Coverage tool must be cargo-llvm-cov '+COV_VERSION)
    return env,executable

def run(output):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    receipt=output/'result.json';receipt.unlink(missing_ok=True)
    initial=source_digest();env,tool=tool_environment();results={};errors=[]
    for profile in ('base','web'):
        report=output/(profile+'.json');log=output/(profile+'.log');report.unlink(missing_ok=True)
        child_env=dict(env,CARGO_TARGET_DIR=str(output/('target-'+profile)))
        command=[tool,'llvm-cov','--manifest-path',str(ROOT/'container-controller/Cargo.toml'),'--locked','--ignore-filename-regex',r'/container-controller/tests/','--json','--output-path',str(report),'--fail-under-lines','100','--fail-under-functions','100']+(['--features','web'] if profile=='web' else ['--no-default-features'])
        with log.open('w') as stream:done=subprocess.run(command,cwd=ROOT,env=child_env,stdout=stream,stderr=subprocess.STDOUT)
        if done.returncode:errors.append(f'{profile} unit coverage failed; inspect {log}')
        try:
            results[profile]=rust_summary(json.loads(report.read_text()),profile)
        except (ValueError,OSError,json.JSONDecodeError) as error:errors.append(str(error))
        print(profile+(': FAILED' if profile not in results else ': every Rust runtime file has 100% lines/functions'),flush=True)
    log=output/'javascript.jsonl';child_env=dict(env,NODE_V8_COVERAGE=str(output/'v8'))
    with log.open('w') as stream:done=subprocess.run(['node','--test','--experimental-test-coverage','--test-reporter='+str(ROOT/'tools/node_coverage_reporter.cjs'),str(ROOT/'container-controller/tests/unit/web_app.cjs')],cwd=ROOT,env=child_env,stdout=stream,stderr=subprocess.STDOUT)
    if done.returncode:errors.append('Browser unit tests failed; inspect '+str(log))
    try:results['javascript']=js_summary([json.loads(line) for line in log.read_text().splitlines() if line.strip()])
    except (ValueError,OSError,json.JSONDecodeError) as error:errors.append(str(error))
    if source_digest()!=initial:errors.append('Container source changed during coverage; rerun before building')
    if errors:
        (output/'failure.json').write_text(json.dumps({'pass':False,'source_sha256':initial,'errors':errors},indent=2)+'\n')
        raise ValueError('; '.join(errors))
    (output/'failure.json').unlink(missing_ok=True)
    result={'pass':True,'source_sha256':initial,'tool':'cargo-llvm-cov '+COV_VERSION,'coverage':results}
    receipt.write_text(json.dumps(result,indent=2)+'\n');print('Browser runtime has 100% lines/functions; source SHA256 '+initial,flush=True)
    return result

def ensure_coverage(output=None):
    output=Path(output or os.environ.get('SDWAN_CONTAINER_COVERAGE',ROOT/'runtime/container-unit'))
    receipt=output/'result.json'
    if receipt.exists():
        value=json.loads(receipt.read_text())
        if value.get('pass') is True and value.get('source_sha256')==source_digest() and set(value.get('coverage',{}))=={'base','web','javascript'}:return value
    return run(output)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=Path(os.environ.get('SDWAN_CONTAINER_COVERAGE',ROOT/'runtime/container-unit')));args=parser.parse_args()
    try:run(args.output)
    except (ValueError,OSError,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);raise SystemExit(1)
if __name__=='__main__':main()
