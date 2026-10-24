#!/usr/bin/env python3
"""CHR only: autonomous full backup recovery, including loss of API access."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.config import load
from sdwan.deployment import start,wait,read_state
from sdwan.router import Router

spec=importlib.util.spec_from_file_location('deploy_cli',ROOT/'sdwan.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    r=Router(ROOT,'api://127.0.0.1:18728');cfg=load(ROOT/'config/sdwan.json')
    assert r.call('system/identity')['name']=='sdwan-edge'
    resume='--resume-negatives' in sys.argv
    prior=json.loads((ROOT/'runtime/protected-deployment-acceptance.json').read_text()) if resume else {}
    if resume:assert prior['checks'][0]['pass'] and prior['checks'][0]['check'].startswith('scheduler installation commits')
    report={'checks':prior['checks'][:1] if resume else []}
    def record(name):
        report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def restored(token,previous):
        try:wait(r,token,'sdwan-edge',timeout=120,confirm=False)
        except RuntimeError as error:assert 'rolled-back' in str(error),str(error)
        else:raise AssertionError('Unconfirmed transaction committed')
        assert read_state(r,token)['phase']=='rolled-back'
        for name,text in previous.items():assert r.read_file(name)==text,'File not restored: '+name
        end=time.monotonic()+45
        while time.monotonic()<end:
            s=r.status()
            if s.get('revision')==cfg['revision'] and s.get('selected',{}).get('default')=='wan1':return
            time.sleep(.5)
        raise AssertionError('Previous controller did not recover')
    try:
        with tempfile.TemporaryDirectory(prefix='sdwan-protected-test-') as folder:
            package=cli.bundle(cfg,folder)
            if not resume:
                # Positive installation uses the public SDK default. All scenarios use
                # the public SDK default deadline on this long-lived CHR.
                # Long-lived CHR accumulates transaction archives, making a 40s
                # end-to-end positive deadline insufficient for verified uploads.
                prepared_at=time.monotonic()
                token=start(r,package,'sdwan-edge',revision=cfg['revision'],default_policy='default',timeout=120)
                print('Positive installation preparation seconds: '+str(round(time.monotonic()-prepared_at,2)),flush=True)
                result=wait(r,token,'sdwan-edge',timeout=120)
                assert result['phase']=='committed'
                secret=json.loads(r.read_file('sdwan-deploy-request.json'))['password']
                assert not any(secret in x.get('message','') for x in r.call('log/print',{'.proplist':'message'},'POST'))
                record('scheduler installation commits after a fresh API connection; backup password absent from logs')
            else:print('Reusing passed positive installation; resuming negative scenarios',flush=True)

            previous={name:r.read_file(name) for name in ('sdwan-config.json','sdwan-active.json','sdwan-backup.json','sdwan-controller.rsc','sdwan-install.rsc','sdwan-rollback.rsc','sdwan-dataplane.rsc','sdwan-links.rsc')}
            for name in ('sdwan-controller.rsc','sdwan-install.rsc','sdwan-rollback.rsc','sdwan-dataplane.rsc','sdwan-links.rsc'):
                file=package/name;file.write_text(file.read_text()+'\n# unconfirmed changed package\n')
            token=start(r,package,'sdwan-edge',revision=cfg['revision'],default_policy='default',timeout=120)
            # Close the installing session. No external ACK or rollback commands.
            r.close();restored(token,previous)
            record('missing confirmation restores the encrypted backup and package through native watchdog and reboot')

            installer=package/'sdwan-install.rsc'
            original=installer.read_text()
            installer.write_text(original+'\n/ip/firewall/address-list/add list=sdwan-deployment-test address=198.18.0.1 comment="protected-deployment-test-only"\n/ip/service/disable [/ip/service/find where name="api"]\n:error "injected failure after API disabled"\n')
            token=start(r,package,'sdwan-edge',revision=cfg['revision'],default_policy='default',timeout=120)
            restored(token,previous)
            assert not any(x.get('list')=='sdwan-deployment-test' for x in r.call('ip/firewall/address-list'))
            api=r.call('ip/service/print',{'.proplist':'name,disabled','.query':['name=api']},'POST')
            assert api[0]['disabled']=='false'
            record('installer error after disabling API restores API and unrelated configuration without client intervention')
    except Exception as error:
        report['checks'].append({'check':'protected deployment interrupted','pass':False,'detail':str(error)});raise
    finally:
        (ROOT/'runtime/protected-deployment-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
