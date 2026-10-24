#!/usr/bin/env python3
"""LAB ONLY: failed migration from the previous package without mangle."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.config import load
from sdwan.router import Router
from sdwan.deployment import start,wait

spec=importlib.util.spec_from_file_location('deploy_cli',ROOT/'sdwan.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('legacy_package',type=Path)
    folder=parser.parse_args().legacy_package
    legacy={name:(folder/name).read_text() for name in ('sdwan-config.json','sdwan-controller.rsc','sdwan-install.rsc','sdwan-rollback.rsc')}
    assert 'sdwan-dataplane.rsc' not in legacy['sdwan-install.rsc'],'A genuine previous installer is required'
    legacy_revision=json.loads(legacy['sdwan-config.json'])['revision']
    r=Router(ROOT,'api://127.0.0.1:18728');cfg=load(ROOT/'config/sdwan.json')
    backup=r.read_file('sdwan-backup.json');report={'checks':[]}
    def healthy(revision):
        end=time.monotonic()+40
        while time.monotonic()<end:
            s=r.status()
            if s.get('revision')==revision and s.get('states') and all(v['state']=='healthy' for v in s['states'].values()):return
            time.sleep(.3)
        raise AssertionError('Native controller did not recover: '+json.dumps(r.status()))
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    try:
        with contextlib.redirect_stdout(io.StringIO()):cli.rollback(r,'sdwan-edge')
        with tempfile.TemporaryDirectory(prefix='sdwan-legacy-install-') as folder:
            package=Path(folder)
            for name,text in legacy.items():(package/name).write_text(text)
            for name in ('sdwan-deployment.rsc','sdwan-deploy-worker.rsc','sdwan-deploy-watchdog.rsc'):
                (package/name).write_text((ROOT/'native'/name).read_text())
            policy=next(p['name'] for p in json.loads(legacy['sdwan-config.json'])['policies'] if not p['source'])
            token=start(r,package,'sdwan-edge',revision=legacy_revision,default_policy=policy)
            wait(r,token,'sdwan-edge');healthy(legacy_revision)
        for file in r.call('file/print',{'.proplist':'.id,name'},'POST'):
            if file['name'] in ('sdwan-dataplane.rsc','sdwan-links.rsc'):r.call('file/'+file['.id'],method='DELETE')
        assert not any(x.get('comment','').startswith('sdwan:v1:') for x in r.call('ip/firewall/mangle'))
        record('previous native routing-rule package runs without managed mangle')
        original_bundle=cli.bundle
        with tempfile.TemporaryDirectory(prefix='sdwan-failed-migration-') as tmp:
            def broken_bundle(config,output):
                out=original_bundle(config,tmp)
                payload=json.dumps({'error':'injected migration failure'}).replace('"',r'\"')
                (out/'sdwan-controller.rsc').write_text(f':global sdwanStatusJSON "{payload}"\n')
                return out
            cli.bundle=broken_bundle
            try:
                try:
                    with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,cfg,'sdwan-edge')
                except RuntimeError as error:assert 'injected migration failure' in str(error),str(error)
                else:raise AssertionError('Injected migration failure was accepted')
            finally:cli.bundle=original_bundle
        healthy(legacy_revision)
        assert r.read_file('sdwan-controller.rsc')==legacy['sdwan-controller.rsc']
        assert not any(x.get('comment','').startswith('sdwan:v1:') for x in r.call('ip/firewall/mangle'))
        assert not any(x.get('comment','').startswith('sdwan:v1:') for x in r.call('ip/firewall/address-list'))
        assert not any(x['name']=='sdwan-dataplane.rsc' for x in r.call('file/print',{'.proplist':'name'},'POST'))
        assert not any(x['name']=='sdwan-links.rsc' for x in r.call('file/print',{'.proplist':'name'},'POST'))
        record('failed migration restores the previous native package and removes new mangle jumps/lists')
    except Exception as error:
        report['checks'].append({'check':'legacy migration acceptance interrupted','pass':False,'detail':str(error)});raise
    finally:
        r.upload('sdwan-backup.json',backup)
        try:
            with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,cfg,'sdwan-edge')
            healthy(cfg['revision'])
        finally:
            (ROOT/'runtime/legacy-update-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
