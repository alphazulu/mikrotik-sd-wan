#!/usr/bin/env python3
"""Real encrypted rollback/reboot for failed container backend deployments."""
import copy
import importlib.util
import json
import time
from container_support import Lab,ROOT
from sdwan.deployment import start,wait,read_state

def main():
    env=Lab();r=env.router;baseline=json.loads(r.read_file('sdwan-active.json'));report={'checks':[]}
    spec=importlib.util.spec_from_file_location('protected_container_cli',ROOT/'sdwan.py')
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def healthy_active(timeout=100):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            try:
                s=r.status()
                if s.get('container',{}).get('active') and s.get('revision')==baseline['revision'] and s.get('states') and all(x['state']=='healthy' for x in s['states'].values()):return s
            except (OSError,RuntimeError):r.close()
            time.sleep(.5)
        raise AssertionError('Restored local controller did not recover')
    def expect_rollback(token,timeout,pattern):
        try:wait(r,token,'sdwan-container-edge',timeout=timeout,confirm=False)
        except RuntimeError as error:assert 'rolled-back' in str(error) and pattern in str(error),str(error)
        else:raise AssertionError('Faulty container deployment unexpectedly committed')
        return read_state(r,token)
    try:
        env.start();healthy_active()
        before={name:r.read_file(name) for name in cli.FILES};before_config=r.read_file('sdwan-active.json')
        cfg=copy.deepcopy(baseline);cfg['revision']='container-missing-lease-fixture'
        cli.preflight(r,cfg,'sdwan-container-edge')
        package=cli.bundle(cfg,ROOT/'runtime/container-lab/protection-package')
        payload=(package/'sdwan-controller.rsc').read_text();assert payload.count('list="sdwan-container-live"')==1
        (package/'sdwan-controller.rsc').write_text(payload.replace('list="sdwan-container-live"','list="sdwan-test-never-live"'))
        token=start(r,package,'sdwan-container-edge',revision=cfg['revision'],default_policy='default',timeout=30)
        s=env.wait(lambda s:s.get('revision')==cfg['revision'] and s.get('selected',{}).get('default')=='wan1' and not s.get('container',{}).get('active'),timeout=25)
        fresh=r.fresh()
        try:
            assert fresh.call('system/identity')['name']=='sdwan-container-edge'
            fresh.upload('sdwan-deploy-ack.json',json.dumps({'token':token}))
        finally:fresh.close()
        journal=expect_rollback(token,30,'deadline')
        record('healthy native fallback plus a premature fresh API acknowledgement cannot commit without a live container lease')
        healthy_active()
        assert all(r.read_file(name)==source for name,source in before.items())
        assert r.read_file('sdwan-active.json')==before_config
        record('lease timeout restores all eight package files/configuration and the encrypted RouterOS backup, then reboots into the previous backend')
        cfg=copy.deepcopy(baseline);cfg['revision']='container-injected-worker-fixture'
        next(p for p in cfg['policies'] if p['name']=='client101')['wans']=['wan2','wan1']
        cli.preflight(r,cfg,'sdwan-container-edge');package=cli.bundle(cfg,ROOT/'runtime/container-lab/protection-package')
        p=package/'sdwan-install.rsc';p.write_text(p.read_text()+'\n:error "container injected after installer"\n')
        token=start(r,package,'sdwan-container-edge',revision=cfg['revision'],default_policy='default',timeout=60)
        expect_rollback(token,60,'container injected after installer');healthy_active()
        assert all(r.read_file(name)==source for name,source in before.items()) and r.read_file('sdwan-active.json')==before_config
        record('worker error after actual dataplane installation/container start restores the preceding container package and route preference')
        report['pass']=True
    finally:
        env.close();(ROOT/'runtime/container-protection-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
