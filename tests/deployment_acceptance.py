#!/usr/bin/env python3
"""LAB ONLY: WAN aliases with no SLA default, rp-filter and failed-update recovery."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lab
from sdwan.config import load
from sdwan.router import Router

spec=importlib.util.spec_from_file_location('deploy_cli',ROOT/'sdwan.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    r=Router(ROOT,'api://127.0.0.1:18728');cfg=load(ROOT/'config/sdwan.json')
    backup=r.read_file('sdwan-backup.json');rp_filter=r.call('ip/settings')['rp-filter']
    resources=[];report={'checks':[]}
    def add(node,menu,data):
        row=lab.api(node,menu,dict(data,comment='deployment-acceptance-only'),'PUT')
        resources.append((node,menu,row['.id']));return row['.id']
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def wait(predicate,timeout=40):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            status=r.status()
            if predicate(status):return status
            time.sleep(.3)
        raise AssertionError('Condition timed out: '+json.dumps(r.status()))
    def healthy():wait(lambda s:s.get('states') and all(x['state']=='healthy' for x in s['states'].values()))
    def apply(config):
        with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,config,'sdwan-edge')
    def endpoint(command,name=None):
        subprocess.run([sys.executable,str(ROOT/'tools/probe_services.py'),command]+([name] if name else []),capture_output=True,check=True)

    try:
        healthy()
        for n in (1,2,3):
            add('edge','ip/address',{'address':f'172.21.{n}.2/30','interface':f'ether{n+1}'})
            add('isp'+str(n),'ip/address',{'address':f'172.21.{n}.1/30','interface':'ether2'})
            add('isp'+str(n),'ip/address',{'address':'203.0.113.9/32','interface':'lo'})
        apply(cfg);healthy()
        alias_rules=[x for x in r.call('routing/rule') if x.get('comment','').startswith('sdwan:v1:alias-pin:')]
        assert len(alias_rules)==3
        for n in (1,2,3):
            rows=lab.api('client','ping',{'address':f'172.21.{n}.2','src-address':'192.168.50.101','count':'1'},'POST')
            assert int(rows[-1].get('received','0'))==1,(n,rows)
        record('LAN clients can reach additional WAN IPs after reinstallation; local bypass precedes source pins')
        endpoint('fail','a');endpoint('fail','b')
        wait(lambda s:s.get('selected') and all(x=='none' for x in s['selected'].values()))
        for n in (1,2,3):
            for address in (f'172.20.{n}.2',f'172.21.{n}.2'):
                rows=lab.api('isp'+str(n),'ping',{'address':address,'src-address':'203.0.113.9','count':'2'},'POST')
                assert int(rows[-1].get('received','0'))==2,(address,rows)
        record('all primary and additional WAN IPs reply while every SLA default is disabled and underlay remains reachable')
        endpoint('heal');healthy()

        r.call('ip/settings/set',{'rp-filter':'strict'},'POST')
        apply(cfg)
        assert r.call('ip/settings')['rp-filter']=='loose'
        assert json.loads(r.read_file('sdwan-backup.json'))['rp_filter']=='strict'
        with contextlib.redirect_stdout(io.StringIO()):cli.rollback(r,'sdwan-edge')
        assert r.call('ip/settings')['rp-filter']=='strict'
        assert not any(x.get('comment','').startswith('sdwan:v1:') for x in r.call('ip/firewall/mangle'))
        assert not any(x.get('comment','').startswith('sdwan:v1:') for x in r.call('ip/firewall/address-list'))
        assert not r.call('system/scheduler?name=sdwan-controller')
        record('native rollback removes managed mangle/address lists and restores strict rp-filter')
        r.call('ip/settings/set',{'rp-filter':rp_filter},'POST');r.upload('sdwan-backup.json',backup)
        apply(cfg);healthy()

        baseline=add('edge','ip/route',{'dst-address':'0.0.0.0/0','gateway':'172.20.3.1','distance':'250'})
        fasttrack=add('edge','ip/firewall/filter',{'chain':'forward','action':'fasttrack-connection','src-address':'198.18.255.255/32'})
        changed=copy.deepcopy(cfg)
        changed['takeover_routes']=[{'.id':baseline,'gateway':'172.20.3.1','dst-address':'0.0.0.0/0','routing-table':'main'}]
        changed['disable_fasttrack']=[{'.id':fasttrack,'chain':'forward','action':'fasttrack-connection'}]
        old_source=r.read_file('sdwan-controller.rsc')
        r.call('ip/settings/set',{'rp-filter':'strict'},'POST')
        original_bundle=cli.bundle
        with tempfile.TemporaryDirectory(prefix='sdwan-failed-package-') as folder:
            def broken_bundle(config,output):
                result=original_bundle(config,folder)
                payload=json.dumps({'error':'injected deployment failure'}).replace('"',r'\"')
                (result/'sdwan-controller.rsc').write_text(f':global sdwanStatusJSON "{payload}"\n')
                return result
            cli.bundle=broken_bundle
            try:
                try:apply(changed)
                except RuntimeError as error:assert 'injected deployment failure' in str(error),str(error)
                else:raise AssertionError('Injected controller error was accepted')
            finally:cli.bundle=original_bundle
        assert r.read_file('sdwan-controller.rsc')==old_source
        assert r.call('ip/route/'+baseline).get('disabled','false')=='false'
        assert r.call('ip/firewall/filter/'+fasttrack).get('disabled','false')=='false'
        assert r.call('ip/settings')['rp-filter']=='strict'
        assert r.call('system/scheduler?name=sdwan-controller')[0].get('disabled')=='false'
        record('failed native update restores previous package, route/FastTrack flags, rp-filter and scheduler')
    except Exception as error:
        report['checks'].append({'check':'deployment acceptance interrupted','pass':False,'detail':str(error)});raise
    finally:
        endpoint('heal')
        r.call('ip/settings/set',{'rp-filter':rp_filter},'POST')
        for node,menu,identifier in reversed(resources):
            lab.api(node,menu+'/'+identifier,method='DELETE')
        r.upload('sdwan-backup.json',backup)
        try:apply(cfg);healthy()
        finally:
            (ROOT/'runtime/deployment-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
