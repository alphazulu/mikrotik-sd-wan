#!/usr/bin/env python3
"""Fencing, local competing process, API loss, SLA and reboot on isolated CHR."""
import copy
import json
import time
import sys
from container_support import Lab,ROOT

def main():
    env=Lab();r=env.router;lab=env.lab;baseline=json.loads(r.read_file('sdwan-active.json'))
    fixture=copy.deepcopy(baseline);fixture['revision']='container-fencing-fixture'
    for profile in fixture['sla_profiles'].values():profile['jitter_ms']=200
    resume='--reboot-only' in sys.argv
    previous=json.loads((ROOT/'runtime/container-fencing-validation.json').read_text()) if resume else {'checks':[]}
    if resume:assert len(previous['checks'])==7 and all(item['pass'] for item in previous['checks'])
    report={'checks':previous['checks'] if resume else []};competitor='sdwan-test-container-competitor'
    def record(name,**detail):
        report['checks'].append(dict(check=name,**{'pass':True},detail=detail));print('PASS '+name,flush=True)
        (ROOT/'runtime/container-fencing-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    def healthy():return env.wait(lambda s:len(s.get('states',{}))==6 and all(x['state']=='healthy' for x in s['states'].values()))
    def invalid(text,reason):
        before=env.status()['container'].get('rejections',0)
        r.upload('sdwan-container-intent.json',text)
        current=env.wait(lambda s:s['container'].get('rejections',0)>before)
        assert current['container']['last_rejection']==reason,current['container']
        return current
    def remove_competitor():
        for row in lab.api('edge','container'):
            if row['name']==competitor:
                if row.get('running')=='true':lab.api('edge','container/stop',{'numbers':row['.id']},'POST')
                end=time.monotonic()+20
                while any(x['name']==competitor and x.get('stopped')!='true' for x in lab.api('edge','container')):
                    if time.monotonic()>end:raise AssertionError('Competing test container did not stop')
                    time.sleep(.3)
                lab.api('edge','container/'+row['.id'],method='DELETE')
    try:
        if not resume:
            env.apply(fixture);healthy();s=env.start();owner=s['container']['owner_instance']
            good=r.read_file('sdwan-container-intent.json');bad=json.loads(good);bad['instance']='f'*32;bad['seq']=999999
            rejected=invalid(json.dumps(bad),'intent live foreign owner')
            assert rejected['container']['active'] and rejected['container']['owner_instance']==owner
            assert rejected['selected']['client101']=='wan1'
            r.upload('sdwan-container-intent.json',good)
            record('foreign intent cannot replace the live owner or its accepted routing plan')
            lab.proxy_request({'wan':'wan1','set':{'delay':90.0}})
            s=env.wait(lambda x:x['states']['default/wan1']['state']=='degraded' and x['selected']['client101']=='wan2' and x['container']['active'])
            assert s['samples']['wan1']['up']>=2
            record('RTT SLA violation selects backup even while Internet probe quorum remains available')
            lab.proxy_request({'reset':True});healthy();env.wait(lambda s:s['selected']['client101']=='wan1')
            settings=json.loads(r.read_file('sdwan-container/config/controller.json'));port=settings['endpoint'].split(':')[1]
            block=env.add('edge','ip/firewall/raw',{'chain':'prerouting','in-interface':'sdwan-container-mgmt','src-address':'172.31.255.2','dst-address':'172.31.255.1','protocol':'tcp','dst-port':port,'action':'drop'})
            env.wait(lambda x:not x['container']['active'],timeout=20)
            assert env.container().get('running')=='true'
            before=r.read_file('sdwan-container-intent.json');time.sleep(5);assert r.read_file('sdwan-container-intent.json')==before
            lab.api('edge','ip/firewall/raw/'+block,method='DELETE');env.wait(lambda x:x['container']['active'])
            record('API blackhole stops successful heartbeat; native fallback and recovery need no controller restart')
            primary=env.container();owner=env.status()['container']['owner_instance'];before=r.read_file('sdwan-container-intent.json')
            lab.api('edge','container',{'file':primary['file'],'name':competitor,'root-dir':'sdwan-test-container-competitor-root',
                     'interface':'sdwan-container-veth','mountlists':'sdwan-controller','cmd':'run /config/controller.json',
                     'memory-max':'16777216','shm-size':'0','logging':'yes','start-on-boot':'no','comment':'sdwan-container-test'},'PUT')
            end=time.monotonic()+60
            while time.monotonic()<end:
                row=next(x for x in lab.api('edge','container') if x['name']==competitor)
                if row.get('stopped')=='true':break
                time.sleep(.5)
            else:raise AssertionError('Competing test container extraction timed out')
            lab.api('edge','container/start',{'numbers':row['.id']},'POST');time.sleep(10)
            assert env.status()['container']['owner_instance']==owner
            assert r.read_file('sdwan-container-intent.json')==before
            record('second real local Rust container backs away from a live owner without overwriting intent')
            lab.api('edge','container/stop',{'numbers':primary['.id']},'POST')
            env.wait(lambda s:s['container']['active'] and s['container']['owner_instance']!=owner,timeout=25)
            record('second local container claims only after the old lease expires, with one RouterOS route writer')
            remove_competitor();env.wait(lambda s:not s['container']['active'],timeout=15);env.start();healthy()
            old=env.status()['container'];old_intent=r.read_file('sdwan-container-intent.json')
            changed=copy.deepcopy(fixture);next(p for p in changed['policies'] if p['name']=='client101')['wans']=['wan2','wan1']
            env.apply(changed);s=env.wait(lambda s:s['selected']['client101']=='wan2' and s['container']['active'])
            assert s['revision']==fixture['revision'] and s['container']['generation']>old['generation'] and s['container']['boot_id']==old['boot_id']
            record('policy change with unchanged revision advances generation and refreshes Rust configuration')
            s=invalid(old_intent,'intent configuration fence');assert s['selected']['client101']=='wan2'
            record('old generation intent cannot restore old policy preference')
        else:
            changed=copy.deepcopy(fixture)
            next(p for p in changed['policies'] if p['name']=='client101')['wans']=['wan2','wan1']
            env.apply(changed);healthy();env.start()
        env.stop();env.start();old_boot=env.status()['container']['boot_id'];started=time.monotonic()
        try:r.call('system/reboot',{},'POST')
        except (OSError,RuntimeError):pass
        r.close();time.sleep(3)
        end=time.monotonic()+150
        while time.monotonic()<end:
            try:
                s=r.status()
                if s.get('container',{}).get('boot_id') not in (None,old_boot) and s['container']['active'] and s.get('selected',{}).get('client101')=='wan2' and all(v['state']=='healthy' for v in s.get('states',{}).values()):
                    candidate=json.loads(r.read_file('sdwan-container-intent.json'))
                    if candidate['boot_id']==s['container']['boot_id']:break
            except (OSError,RuntimeError):r.close()
            time.sleep(1)
        else:raise AssertionError('Local controller did not recover after RouterOS reboot')
        intent=json.loads(r.read_file('sdwan-container-intent.json'))
        assert intent['boot_id']==s['container']['boot_id'] and s['selected']['client101']=='wan2'
        record('RouterOS reboot changes boot fence and autonomously restarts the container with fresh probes and intent',seconds=round(time.monotonic()-started,1))
        report['pass']=True
    finally:
        try:remove_competitor()
        finally:env.close()
        restore=Lab()
        try:restore.apply(baseline)
        finally:restore.close()
        (ROOT/'runtime/container-fencing-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
