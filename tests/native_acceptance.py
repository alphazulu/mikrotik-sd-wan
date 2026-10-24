#!/usr/bin/env python3
"""Fault injector and observer; routing decisions are exclusively native RouterOS."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import lab
from sdwan.router import Router
spec=importlib.util.spec_from_file_location('baseline_acceptance',ROOT/'tests/acceptance.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
router=Router(ROOT)
report={'timestamp_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'controller':'native RouterOS script/scheduler','checks':[]}


def status():
    s=router.status()
    if 'error' in s:raise AssertionError(s['error'])
    return s


def wait(predicate,timeout=35):
    until=time.monotonic()+timeout;last={}
    while time.monotonic()<until:
        last=status()
        if predicate(last):return last
        time.sleep(.5)
    raise AssertionError('Condition timed out: '+json.dumps(last))


def healthy():
    return wait(lambda s:len(s.get('states',{}))==6 and all(x['state']=='healthy' for x in s['states'].values()))


def record(name,detail=None):
    report['checks'].append({'check':name,'pass':True,'detail':detail});print('PASS '+name,flush=True)


def source_path(source,wan):
    return base.path(source,wan)


def endpoint(command,name=None):
    subprocess.run([sys.executable,str(ROOT/'tools/probe_services.py'),command]+([name] if name else []),check=True,capture_output=True)


def main():
    outage=None;temp_address=None;disabled=[]
    try:
        lab.proxy_request({'reset':True});endpoint('heal')
        for i in (1,2,3):lab.qmp('edge','set_link',{'name':f'nic{i+1}','up':True})
        existing=lab.api('client','ip/address')
        if not any(x.get('address')=='192.168.50.103/24' for x in existing):temp_address=lab.api('client','ip/address',{'address':'192.168.50.103/24','interface':'ether2','comment':'native-acceptance'},'PUT')['.id']
        healthy()
        staged=next(f for f in router.call('file') if f['name']=='sdwan-config.json')
        original=router.call('file/'+staged['.id'])['contents']
        invalid=json.loads(original);invalid['policies'][-1]['wans']=['wan3','wan1']
        try:
            router.upload('sdwan-config.json',json.dumps(invalid))
            time.sleep(2)
            assert status()['selected']['strict103']=='wan3'
            try:
                router.call('import',{'file-name':'sdwan-install.rsc'},'POST')
                raise AssertionError('Native installer accepted invalid strict policy')
            except RuntimeError as e:
                assert 'strict' in str(e),str(e)
            assert router.call('system/scheduler?name=sdwan-controller')[0].get('disabled')=='false'
        finally:router.upload('sdwan-config.json',original)
        record('staged configuration is inert; native validator rejects invalid strict policy')
        record('native policy .101 -> WAN1',source_path('192.168.50.101','wan1'))
        record('native policy .102 -> WAN2',source_path('192.168.50.102','wan2'))
        record('strict .103 -> WAN3',source_path('192.168.50.103','wan3'))
        before=status();time.sleep(2.2);after=status()
        delta=after['states']['default/wan1']['good_windows']-before['states']['default/wan1']['good_windows']
        bad_delta=after['states']['default/wan1']['bad_windows']-before['states']['default/wan1']['bad_windows']
        epochs=after['samples']['wan1']['epoch']-before['samples']['wan1']['epoch']
        # Either streak can reset on an opposite verdict while hysteresis keeps
        # the state healthy; only increases are bounded by new Netwatch epochs.
        assert epochs>=0 and delta<=epochs and bad_delta<=epochs,(delta,bad_delta,epochs)
        if epochs==0:assert delta==bad_delta==0,(delta,bad_delta,epochs)
        record('polls do not count duplicate Netwatch windows',{'good_window_delta':delta,'bad_window_delta':bad_delta,'epoch_delta':epochs})

        endpoint('fail','a');time.sleep(6)
        s=status();assert all(x['state']=='healthy' for x in s['states'].values()),s
        assert all(x['up']==2 for x in s['samples'].values()),s
        record('one failed target preserves quorum and healthy WANs')
        endpoint('heal');healthy()

        started=time.monotonic()
        outage=lab.api('isp1','ip/firewall/filter',{'chain':'forward','action':'drop','place-before':'0','comment':'native-test-upstream-outage'},'PUT')['.id']
        s=wait(lambda s:s['selected']['client101']=='wan2' and s['states']['default/wan1']['state']=='down')
        elapsed=time.monotonic()-started
        time.sleep(8)
        assert status()['samples']['wan1']['up']==0, 'Probe escaped through a healthy fallback WAN'
        _,ok=lab.ping('edge','172.20.1.1');assert ok,'ISP1 gateway should remain alive'
        detail=source_path('192.168.50.101','wan2');detail['observed_seconds']=round(elapsed,3)
        record('upstream outage detected while gateway stays reachable',detail)
        lab.api('isp1','ip/firewall/filter/'+outage,method='DELETE');outage=None
        s=wait(lambda s:s['states']['default/wan1']['state']=='recovering')
        assert s['selected']['client101']=='wan2',s
        started=time.monotonic();s=wait(lambda s:s['selected']['client101']=='wan1')
        record('recovery waits for good windows and hold-down',{'observed_recovering_seconds':round(time.monotonic()-started,3)})

        lab.proxy_request({'wan':'wan2','set':{'delay':55.0}})
        s=wait(lambda s:s['states']['voice/wan2']['state']=='degraded' and s['states']['default/wan2']['state']=='healthy' and s['selected']['client102']=='wan1',timeout=45)
        assert s['states']['default/wan2']['state']=='healthy',s
        record('voice SLA switches client while default SLA remains healthy',{'sample':s['samples']['wan2'],'path':source_path('192.168.50.102','wan1')})
        lab.proxy_request({'reset':True});healthy();wait(lambda s:s['selected']['client102']=='wan2')

        lab.qmp('edge','set_link',{'name':'nic4','up':False})
        wait(lambda s:s['selected']['strict103']=='none')
        _,ok=lab.ping('client','198.19.0.1','192.168.50.103',count=2);assert not ok,'Strict client leaked to fallback WAN'
        source_path('192.168.50.101','wan1');record('strict pinning fails closed; prefer client continues')
        lab.qmp('edge','set_link',{'name':'nic4','up':True});healthy()

        for i in (1,2,3):lab.qmp('edge','set_link',{'name':f'nic{i+1}','up':False})
        wait(lambda s:all(x=='none' for x in s['selected'].values()))
        for source in ('192.168.50.101','192.168.50.102','192.168.50.103'):
            _,ok=lab.ping('client','198.19.0.1',source,count=2);assert not ok,source
        lab.api('edge','system/resource');record('all WANs down: all policies fail closed, management survives')
        for i in (1,2,3):lab.qmp('edge','set_link',{'name':f'nic{i+1}','up':True})
        healthy()

        probe=next(x for x in lab.api('edge','tool/netwatch') if x.get('comment')=='sdwan:v1:icmp:wan1')
        lab.api('edge','tool/netwatch/'+probe['.id'],{'disabled':'true'},'PATCH');disabled.append(probe['.id'])
        s=wait(lambda s:s['states']['default/wan1']['state']=='down' and s['samples']['wan1']['stale'])
        assert s['selected']['client101']=='wan2',s
        record('stalled telemetry cannot stay healthy',s['states']['default/wan1'])
        lab.api('edge','tool/netwatch/'+probe['.id'],{'disabled':'false'},'PATCH');disabled=[];healthy()

        # No external SD-WAN process exists; reboot persists files/scripts/scheduler.
        lab.api('edge','system/reboot',{},'POST')
        until=time.monotonic()+15
        while lab.alive('edge') and time.monotonic()<until:time.sleep(.3)
        subprocess.run([sys.executable,str(ROOT/'lab.py'),'up'],check=True,capture_output=True,text=True)
        healthy();record('router reboot restores autonomous local controller',source_path('192.168.50.101','wan1'))

        subprocess.run([sys.executable,str(ROOT/'sdwan.py'),'rollback'],check=True,capture_output=True,text=True)
        lab.verify();record('native rollback restores baseline routes and rules')
        subprocess.run([sys.executable,str(ROOT/'sdwan.py'),'apply'],check=True,capture_output=True,text=True)
        healthy();record('standalone native installer restores SD-WAN after rollback')
    except Exception as e:
        report['checks'].append({'check':'native acceptance interrupted','pass':False,'detail':str(e)});raise
    finally:
        if outage:lab.api('isp1','ip/firewall/filter/'+outage,method='DELETE')
        for ident in disabled:lab.api('edge','tool/netwatch/'+ident,{'disabled':'false'},'PATCH')
        lab.proxy_request({'reset':True});endpoint('heal')
        for i in (1,2,3):lab.qmp('edge','set_link',{'name':f'nic{i+1}','up':True})
        if temp_address:lab.api('client','ip/address/'+temp_address,method='DELETE')
        lab.save(lab.RUN/'native-acceptance.json',report)

if __name__=='__main__':main()
