#!/usr/bin/env python3
"""CHR real APN sharing/baseline and binary restore with LTE device adapter."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lte_fixture import lte_wan,package_adapter,IFACE,PROFILE,STATE
from sdwan.config import load
from sdwan.deployment import start,wait as deployment_wait,read_state
from sdwan.router import Router
spec=importlib.util.spec_from_file_location('cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    real=Router(ROOT,'api://127.0.0.1:18728');r=real;base=load(ROOT/'config/sdwan.json');original_backup=r.read_file('sdwan-backup.json');report={'physical_modem_tested':False,'checks':[]}
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def wait(predicate,timeout=70):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=r.status()
            if predicate(state):return state
            time.sleep(.3)
        raise AssertionError(state)
    def healthy():return wait(lambda s:'error' not in s and s.get('states') and all(x['state']=='healthy' for x in s['states'].values()))
    def apply(cfg):
        with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,cfg,'sdwan-edge')
    try:
        with lte_wan(add_default=True) as (ids,metadata):
            r=metadata
            try:
                radios=json.loads(r.read_file(STATE));radios.append({'id':'*extra','name':'ether3','profiles':[PROFILE]});r.upload(STATE,json.dumps(radios))
                shared=copy.deepcopy(base);shared['revision']='lte-shared'
                for index,iface in [(1,'ether3'),(2,IFACE)]:
                    w=shared['wans'][index];w.update(kind='lte',interface=iface,apn_profile=PROFILE);w.pop('address');w.pop('gateway')
                with package_adapter(cli):
                    apply(shared);wait(lambda s:s.get('selected',{}).get('strict103')=='wan3')
                    snapshot=json.loads(r.read_file('sdwan-backup.json'))['lte_apns'];assert len(snapshot)==1
                    apn=snapshot[PROFILE];assert apn['original_add'] is True and set(apn['interfaces'])=={'ether3',IFACE}
                    actual=r.call('interface/lte/apn/'+apn['id']);assert actual['add-default-route']=='false'
                    record('two selected LTE interfaces sharing one APN create one original baseline and suppress the automatic route')
                    apply(shared);wait(lambda s:s.get('selected',{}).get('strict103')=='wan3')
                    snapshot2=json.loads(r.read_file('sdwan-backup.json'))['lte_apns'];assert snapshot2==snapshot
                    record('reapply keeps the shared APN original state and identities')
                    with contextlib.redirect_stdout(io.StringIO()):cli.rollback(r,'sdwan-edge')
                    actual=r.call('interface/lte/apn/'+apn['id']);assert actual['add-default-route']=='true' and actual['default-route-distance']=='77'
                    record('baseline rollback restores shared APN add=yes and the original distance')
                # Begin a separate installation from the ordinary static package.
                r.upload('sdwan-backup.json',original_backup);apply(base);healthy()
                r.upload(STATE,json.dumps(radios[:1]))
                previous={name:r.read_file(name) for name in ('sdwan-config.json','sdwan-active.json','sdwan-backup.json','sdwan-controller.rsc','sdwan-install.rsc','sdwan-rollback.rsc','sdwan-dataplane.rsc','sdwan-links.rsc')}
                candidate=copy.deepcopy(base);candidate['revision']='lte-failed-adoption'
                w=candidate['wans'][2];w.update(kind='lte',interface=IFACE,apn_profile=PROFILE);w.pop('address');w.pop('gateway')
                with tempfile.TemporaryDirectory(prefix='sdwan-lte-recovery-') as folder:
                    with package_adapter(cli):package=cli.bundle(candidate,folder)
                    installer=package/'sdwan-install.rsc'
                    installer.write_text(installer.read_text()+'\n:if ([/interface/lte/apn/get [/interface/lte/apn/find where name="'+PROFILE+'"] add-default-route]) do={ :error "APN adoption did not run" }\n:error "injected failure after LTE APN adoption"\n')
                    token=start(r,package,'sdwan-edge',revision=candidate['revision'],default_policy='default',timeout=40)
                    try:deployment_wait(r,token,'sdwan-edge',timeout=40)
                    except RuntimeError as error:assert 'rolled-back' in str(error) and 'injected failure after LTE APN adoption' in str(error),str(error)
                    else:raise AssertionError('Failed APN deployment committed')
                    assert read_state(r,token)['phase']=='rolled-back'
                for name,text in previous.items():assert r.read_file(name)==text,name
                actual=r.call('interface/lte/apn/'+apn['id']);assert actual['add-default-route']=='true' and actual['default-route-distance']=='77'
                healthy();record('worker error after real APN mutation restores encrypted binary backup, APN routing, eight core/config files and controller after reboot')
            finally:
                r=real;r.close();apply(base);healthy();r.upload('sdwan-backup.json',original_backup)
    except Exception as error:
        report['checks'].append({'check':'LTE protection interrupted','pass':False,'detail':str(error)});raise
    finally:
        (ROOT/'runtime/lte-protection-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');real.close()


if __name__=='__main__':main()
