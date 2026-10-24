#!/usr/bin/env python3
"""A healthy status lacking container metadata must never satisfy deployment readiness."""
import copy
import importlib.util
import json
from container_support import Lab,ROOT
from sdwan.deployment import start,wait
from sdwan.deployment import read_state

def main():
    env=Lab();r=env.router;report={'pass':False}
    spec=importlib.util.spec_from_file_location('missing_meta_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    try:
        env.start();baseline=json.loads(r.read_file('sdwan-active.json'))
        before={name:r.read_file(name) for name in cli.FILES};active=r.read_file('sdwan-active.json')
        cfg=copy.deepcopy(baseline);cfg['revision']='container-missing-metadata-fixture'
        cli.preflight(r,cfg,'sdwan-container-edge');package=cli.bundle(cfg,ROOT/'runtime/container-lab/missing-metadata-package')
        p=package/'sdwan-controller.rsc';source=p.read_text();anchor='    :set ($output->"container") $containerBridge\n';assert source.count(anchor)==1
        p.write_text(source.replace(anchor,''))
        # Exercise a NEW recovery-framework version as well: these files are
        # uploaded before bootstrap and must still roll back to their old bytes.
        infrastructure=('sdwan-deployment.rsc','sdwan-deploy-worker.rsc','sdwan-deploy-watchdog.rsc')
        for name in infrastructure:
            p=package/name;p.write_text(p.read_text()+'\n# candidate recovery framework version\n')
            assert p.read_text()!=before[name]
        token=start(r,package,'sdwan-container-edge',revision=cfg['revision'],default_policy='default',timeout=30)
        state=read_state(r,token)
        assert all(name in state['previous'] and r.read_file(state['previous'][name])==before[name] for name in infrastructure)
        env.wait(lambda s:s.get('revision')==cfg['revision'] and 'container' not in s and s.get('selected',{}).get('default') not in (None,'none'),timeout=25)
        fresh=r.fresh()
        try:fresh.upload('sdwan-deploy-ack.json',json.dumps({'token':token}))
        finally:fresh.close()
        try:wait(r,token,'sdwan-container-edge',timeout=30,confirm=False)
        except RuntimeError as error:assert 'rolled-back' in str(error) and 'deadline' in str(error),str(error)
        else:raise AssertionError('Missing lease metadata unexpectedly committed')
        assert all(r.read_file(name)==text for name,text in before.items()) and r.read_file('sdwan-active.json')==active
        env.start()
        report={'pass':True,'checks':1,'missing_metadata_rejected_despite_fresh_ack':True,'encrypted_backup_and_all_files_restored':True,'new_recovery_framework_version_rolled_back':True}
        print('PASS missing container metadata cannot satisfy typed watchdog readiness; full rollback/reboot restored backend',flush=True)
    finally:
        env.close();(ROOT/'runtime/container-missing-metadata-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
