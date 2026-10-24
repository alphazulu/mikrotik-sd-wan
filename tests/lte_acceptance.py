#!/usr/bin/env python3
"""CHR LTE lifecycle over a real point-to-point link and real APN settings.

Only modem inventory is substituted. This test does not validate a radio/SIM.
"""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lab
from lte_fixture import lte_wan,package_adapter,IFACE,PROFILE,STATE
from sdwan.config import load,validate
from sdwan.router import Router
from stream_traffic import StreamTraffic
spec=importlib.util.spec_from_file_location('cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    base_router=Router(ROOT,'api://127.0.0.1:18728');r=base_router;base=load(ROOT/'config/sdwan.json');backup=r.read_file('sdwan-backup.json')
    report={'physical_modem_tested':False,'lte_inventory_adapter':True,'checks':[]};traffic=None;remote=None;forward=False
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def wait(predicate,timeout=65):
        end=time.monotonic()+timeout;state={}
        while time.monotonic()<end:
            state=r.status()
            if predicate(state):return state
            if 'error' in state:print('controller error',state['error'],flush=True)
            time.sleep(.3)
        raise AssertionError(state)
    def settled(policy):return wait(lambda s:s.get('uptime_seconds',0)>s.get('last_cleanup',{}).get(policy,{}).get('uptime_seconds',-100)+3)
    def healthy():return wait(lambda s:'error' not in s and s.get('states') and all(x['state']=='healthy' for x in s['states'].values()))
    def apply(cfg):
        with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,cfg,'sdwan-edge')
    try:
        with lte_wan(add_default=False) as (ids,metadata):
            r=metadata
            try:
                cfg=copy.deepcopy(base);cfg['revision']='lte-lifecycle'
                wan=cfg['wans'][2];wan.update(kind='lte',interface=IFACE,apn_profile=PROFILE);wan.pop('address');wan.pop('gateway')
                for p in cfg['policies']:
                    if p['name'] in ('default','client101'):p['wans']=['wan1','wan3']
                validate(cfg)
                for n in (1,2,3):
                    ids['add']('isp'+str(n),'ip/address',{'address':'203.0.113.9/32','interface':'lo','comment':'dynamic-wan-acceptance-only'})
                    ids['add']('isp'+str(n),'ip/firewall/nat',{'chain':'dstnat','dst-address':'203.0.113.200','protocol':'tcp','dst-port':'29010-29019','action':'dst-nat','to-addresses':f'10.77.{n}.2','comment':'dynamic-wan-acceptance-only'})
                if not any(x.get('address')=='192.168.50.103/24' for x in lab.api('client','ip/address')):ids['add']('client','ip/address',{'address':'192.168.50.103/24','interface':'ether2','comment':'dynamic-wan-acceptance-only'})
                # Installation must accept an enabled modem before data is up.
                lab.api('isp3','interface/pppoe-server/server/'+ids['pppoe_server'],{'disabled':'true'},'PATCH')
                for session in lab.api('isp3','ppp/active'):
                    if session.get('name')=='sdwan-test-ppp-user':lab.api('isp3','ppp/active/'+session['.id'],method='DELETE')
                with package_adapter(cli):
                    apply(cfg)
                    state=wait(lambda s:not s.get('samples',{}).get('wan3',{}).get('link_ready',True))
                    assert state['selected']['strict103']=='none' and state['selected']['default']=='wan1'
                    record('enabled LTE without a data session installs safely; primary works and LTE stays closed')
                    lab.api('isp3','interface/pppoe-server/server/'+ids['pppoe_server'],{'disabled':'false'},'PATCH');state=healthy()
                    assert state['samples']['wan3']['kind']=='lte' and state['samples']['wan3']['address']=='172.31.3.2'
                    active=json.loads(r.read_file('sdwan-active.json'));assert active['wans'][2]['apn_profile']==PROFILE and 'address' not in active['wans'][2] and 'gateway' not in active['wans'][2]
                    apn=next(x for x in r.call('interface/lte/apn/print',{'.proplist':'.id,name,add-default-route'},'POST') if x['name']==PROFILE)
                    assert apn['add-default-route']=='false'
                    baseline=json.loads(r.read_file('sdwan-backup.json'));assert baseline['lte_apns'][PROFILE]['original_add'] is False
                    record('APN original add-default-route=no is preserved; fresh LTE SLA opens an interface-pinned WAN without lease snapshots')
                    # Reapplying must retain the first APN baseline and not duplicate it.
                    apply(cfg);healthy();snap=json.loads(r.read_file('sdwan-backup.json'))['lte_apns'];assert len(snap)==1 and snap[PROFILE]['original_add'] is False
                    record('reapply is idempotent and keeps one original APN baseline')
                    from sdwan.discovery import discover
                    (ROOT/'runtime/discovery-lte-adapter.json').write_text(json.dumps(discover(r),indent=2)+'\n')
                    ping=lab.api('isp3','ping',{'address':'172.31.3.2','src-address':'203.0.113.9','count':'3'},'POST');assert int(ping[-1].get('received',0))==3
                    ids['add']('client','ip/firewall/filter',{'chain':'input','src-address':'203.0.113.9','protocol':'tcp','dst-port':'80','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                    ids['add']('edge','ip/firewall/filter',{'chain':'forward','connection-nat-state':'dstnat','protocol':'tcp','dst-port':'80','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                    ids['add']('edge','ip/firewall/nat',{'chain':'dstnat','in-interface':IFACE,'dst-address':'172.31.3.2','protocol':'tcp','dst-port':'29009','action':'dst-nat','to-addresses':'192.168.50.102','to-ports':'80','comment':'dynamic-wan-acceptance-only'})
                    fetched=lab.api('isp3','tool/fetch',{'url':'http://172.31.3.2:29009/','src-address':'203.0.113.9','output':'user'},'POST');fetched=fetched[-1] if isinstance(fetched,list) else fetched;assert fetched.get('status')=='finished'
                    record('router and DNAT replies use LTE ingress despite a different outbound client preference')
                    ids['add']('edge','ip/firewall/filter',{'chain':'input','in-interface':'ether3','src-address':'10.77.2.0/24','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                    ids['add']('isp2','ip/firewall/filter',{'chain':'forward','in-interface':'ether1','dst-address':'172.20.2.2','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                    ids['add']('isp2','ip/firewall/nat',{'chain':'dstnat','in-interface':'ether1','protocol':'tcp','dst-port':'29997','action':'dst-nat','to-addresses':'172.20.2.2','to-ports':'8728','comment':'dynamic-wan-acceptance-only'})
                    out=lab.qmp('isp2','human-monitor-command',{'command-line':'hostfwd_add mgmt tcp:127.0.0.1:18997-10.77.2.15:29997'});assert not out,out;forward=True
                    remote=Router(ROOT,'api://127.0.0.1:18997');assert remote.call('system/identity')['name']=='sdwan-edge'
                    end=time.monotonic()+5;incoming=None
                    while time.monotonic()<end:
                        incoming=next((x['.id'] for x in r.call('ip/firewall/connection') if x.get('connection-mark')=='sdwan-in-wan2' and x.get('dst-port')=='8728'),None)
                        if incoming:break
                        time.sleep(.2)
                    assert incoming
                    traffic=StreamTraffic(r,ids['add']);first=traffic.stream('192.168.50.101','wan1',29010)['.id'];second=traffic.stream('192.168.50.102','wan2',29011)['.id'];third=traffic.stream('192.168.50.103','wan3',29012)['.id']
                    record('real concurrent TCP/NAT streams carry policy/WAN marks, including strict LTE')
                    lab.proxy_request({'wan':'wan1','set':{'blackhole':True}})
                    wait(lambda s:s['selected']['client101']=='wan3' and s['selected']['default']=='wan3')
                    traffic.assert_sessions(absent=[first],retained=[second,third,incoming]);traffic.stop_stream(first)
                    fallback=traffic.stream('192.168.50.101','wan3',29013)['.id'];assert remote.call('system/identity')['name']=='sdwan-edge'
                    lab.proxy_request({'reset':True});healthy();wait(lambda s:s['selected']['client101']=='wan1')
                    traffic.assert_sessions(absent=[fallback],retained=[second,third,incoming]);traffic.stop_stream(fallback)
                    settled('client101')
                    first=traffic.stream('192.168.50.101','wan1',29014)['.id']
                    record('primary silent outage fails over to LTE; failback clears only the changed policy and preserves strict LTE and incoming API')
                    r.call('interface/pppoe-client/'+ids['pppoe'],{'disabled':'true'},'PATCH')
                    wait(lambda s:s['selected']['strict103']=='none' and not s['samples']['wan3']['link_ready'])
                    traffic.assert_sessions(absent=[third],retained=[first,second,incoming]);traffic.stop_stream(third)
                    lab.api('isp3','ppp/profile/'+ids['ppp_profile'],{'remote-address':'172.31.3.22'},'PATCH');r.call('interface/pppoe-client/'+ids['pppoe'],{'disabled':'false'},'PATCH')
                    state=wait(lambda s:s['samples']['wan3']['address']=='172.31.3.22' and s['samples']['wan3']['warming'])
                    assert state['selected']['strict103']=='none' and state['states']['default/wan3']['good_windows']==0
                    healthy();third=traffic.stream('192.168.50.103','wan3',29015)['.id']
                    flow=next(x for x in r.call('ip/firewall/connection') if x['.id']==third);assert flow['reply-dst-address']=='172.31.3.22'
                    traffic.assert_sessions(retained=[first,second,incoming])
                    record('data loss and new LTE IP remove old sessions and require fresh SLA before new source NAT and strict routing')
                    rows=json.loads(r.read_file(STATE));rows[0]['profiles']=['changed-apn'];r.upload(STATE,json.dumps(rows))
                    state=wait(lambda s:not s['samples']['wan3']['link_ready'] and 'profile changed' in s['samples']['wan3']['link_reason'])
                    assert state['selected']['strict103']=='none';traffic.assert_sessions(absent=[third],retained=[first,second,incoming]);traffic.stop_stream(third)
                    rows[0]['profiles']=[PROFILE];r.upload(STATE,json.dumps(rows));healthy()
                    assert remote.call('system/identity')['name']=='sdwan-edge'
                    record('APN drift fails closed without changing another profile or clearing other WAN sessions')
                    traffic.close();traffic=None;remote.close();remote=None
                    try:r.call('system/reboot',{},'POST')
                    except (OSError,ConnectionError):pass
                    r.close();time.sleep(3)
                    end=time.monotonic()+100
                    while time.monotonic()<end:
                        try:
                            state=r.status()
                            if state.get('revision')=='lte-lifecycle' and state.get('selected',{}).get('strict103')=='wan3':break
                        except (OSError,ConnectionError):r.close()
                        time.sleep(.5)
                    else:raise AssertionError('LTE controller did not recover after reboot')
                    healthy();record('native controller reloads LTE/APN logic after reboot without an external runtime')
                    cli.rollback(r,'sdwan-edge');apn=r.call('interface/lte/apn/'+apn['.id']);assert apn['add-default-route']=='false'
                    # Distance is hidden while add=no. This unused fixture APN
                    # can be enabled briefly to verify its latent value.
                    r.call('interface/lte/apn/'+apn['.id'],{'add-default-route':'true'},'PATCH');apn=r.call('interface/lte/apn/'+apn['.id']);assert apn['default-route-distance']=='77'
                    r.call('interface/lte/apn/'+apn['.id'],{'add-default-route':'false'},'PATCH')
                    record('baseline rollback preserves original APN add=no and stored distance without touching provider credentials')
            finally:
                lab.proxy_request({'reset':True})
                if traffic:traffic.close();traffic=None
                if remote:remote.close();remote=None
                if forward:lab.qmp('isp2','human-monitor-command',{'command-line':'hostfwd_remove mgmt tcp:127.0.0.1:18997'});forward=False
                # Adapter is out of scope: restore the production package source.
                r=base_router;r.close();apply(base);healthy();r.upload('sdwan-backup.json',backup)
    except Exception as error:
        report['checks'].append({'check':'LTE lifecycle interrupted','pass':False,'detail':str(error)});raise
    finally:
        (ROOT/'runtime/lte-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');base_router.close()


if __name__=='__main__':main()
