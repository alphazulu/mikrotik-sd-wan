#!/usr/bin/env python3
"""CHR ONLY: classless no-default guard and mixed-WAN binary recovery."""
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
import lab
from dynamic_wan_fixture import dynamic_wans
from sdwan.config import load
from sdwan.deployment import start,wait as deployment_wait,read_state
from sdwan.router import Router

spec=importlib.util.spec_from_file_location('cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    r=Router(ROOT,'api://127.0.0.1:18728');base=load(ROOT/'config/sdwan.json');baseline=r.read_file('sdwan-backup.json');report={'checks':[]}
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def await_status(predicate,timeout=70):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            state=r.status()
            if predicate(state):return state
            time.sleep(.3)
        raise AssertionError(state)
    def healthy():return await_status(lambda s:s.get('states') and 'error' not in s and all(x['state']=='healthy' for x in s['states'].values()))
    def apply(cfg):
        with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,cfg,'sdwan-edge')
    try:
        with dynamic_wans(component_tables=False) as ids:
            try:
                for iface in ('sdwan-test-dhcp-vlan','sdwan-test-pppoe'):ids['add']('edge','interface/list/member',{'list':'WAN','interface':iface,'comment':'dynamic-wan-acceptance-only'})
                cfg=copy.deepcopy(base);cfg['revision']='mixed-protection'
                for w,kind,iface in zip(cfg['wans'][1:],('dhcp','pppoe'),('sdwan-test-dhcp-vlan','sdwan-test-pppoe')):
                    w.update(kind=kind,interface=iface);w.pop('address');w.pop('gateway')
                apply(cfg);healthy()
                option=ids['add']('isp2','ip/dhcp-server/option',{'name':'sdwan-test-no-default','code':'121','value':'0x20c6120201ac1f0201'})
                lab.api('isp2','ip/dhcp-server/network/'+ids['dhcp_network'],{'dhcp-option':'sdwan-test-no-default'},'PATCH')
                r.call('ip/dhcp-client/renew',{'numbers':ids['dhcp']},'POST')
                state=await_status(lambda s:not s.get('samples',{}).get('wan2',{}).get('link_ready',True) and s.get('selected',{}).get('client102')=='wan1')
                assert 'no unique default route' in state['samples']['wan2']['link_reason']
                assert r.call('ip/dhcp-client/'+ids['dhcp'])['status']=='bound'
                assert not any(x.get('dynamic')=='true' and x.get('routing-table','main')=='main' and x.get('dst-address')=='0.0.0.0/0' for x in r.call('ip/route'))
                record('bound DHCP with option121 intranet-only route stays unavailable; option3 does not bypass SLA')
                lab.api('isp2','ip/dhcp-server/network/'+ids['dhcp_network'],{'dhcp-option':'sdwan-test-classless'},'PATCH')
                r.call('ip/dhcp-client/renew',{'numbers':ids['dhcp']},'POST');healthy()
                record('restoring a classless default recovers DHCP through fresh SLA')
                previous={name:r.read_file(name) for name in ('sdwan-active.json','sdwan-config.json','sdwan-backup.json','sdwan-links.rsc','sdwan-controller.rsc','sdwan-install.rsc','sdwan-rollback.rsc','sdwan-dataplane.rsc')}
                candidate=copy.deepcopy(cfg);candidate['revision']='mixed-injected-failure';candidate['wans'][1]=copy.deepcopy(base['wans'][1])
                with tempfile.TemporaryDirectory(prefix='sdwan-mixed-protection-') as folder:
                    package=cli.bundle(candidate,folder);installer=package/'sdwan-install.rsc'
                    installer.write_text(installer.read_text()+'\n:if ([/ip/dhcp-client/get [/ip/dhcp-client/find where interface="sdwan-test-dhcp-vlan"] add-default-route] != "no") do={ :error "fixture DHCP was not retired" }\n:error "injected failure after retiring DHCP WAN"\n')
                    token=start(r,package,'sdwan-edge',revision=candidate['revision'],default_policy='default',timeout=40)
                    try:deployment_wait(r,token,'sdwan-edge',timeout=40)
                    except RuntimeError as error:assert 'rolled-back' in str(error) and 'injected failure after retiring DHCP WAN' in str(error),str(error)
                    else:raise AssertionError('Injected failed deployment committed')
                    assert read_state(r,token)['phase']=='rolled-back'
                for name,text in previous.items():assert r.read_file(name)==text,name
                state=healthy();assert state['revision']=='mixed-protection' and state['selected']['client102']=='wan2'
                dhcp=r.call('ip/dhcp-client/'+ids['dhcp']);ppp=r.call('interface/pppoe-client/'+ids['pppoe'])
                assert dhcp['add-default-route']=='yes' and dhcp['default-route-tables'].split(':')[0]=='sdwan-probe-wan2'
                assert ppp['add-default-route'] in ('false','no')
                record('worker error restores full mixed configuration, provider routing options, all core files and controller after reboot')
            finally:
                r.call('ip/dhcp-client/'+ids['dhcp'],{'add-default-route':'no'},'PATCH');r.call('interface/pppoe-client/'+ids['pppoe'],{'add-default-route':'false'},'PATCH')
                apply(base);healthy();r.upload('sdwan-backup.json',baseline)
    except Exception as error:
        report['checks'].append({'check':'dynamic protection interrupted','pass':False,'detail':str(error)});raise
    finally:
        (ROOT/'runtime/dynamic-wan-protection-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
