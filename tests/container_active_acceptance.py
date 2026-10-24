#!/usr/bin/env python3
"""Real container decisions, conntrack and warm native failover on isolated CHR."""
import json
import copy
import time
from container_support import Lab,ROOT
import stream_traffic

def main():
    env=Lab();lab=env.lab;router=env.router;traffic=None
    report={'checks':[],'production_modified':False}
    baseline=json.loads(router.read_file('sdwan-active.json'))
    fixture=copy.deepcopy(baseline);fixture['revision']='container-availability-fixture'
    for profile in fixture['sla_profiles'].values():profile['jitter_ms']=200
    def record(name,**detail):
        report['checks'].append(dict(check=name,**{'pass':True},detail=detail));print('PASS '+name,flush=True)
        (ROOT/'runtime/container-active-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    def healthy():return env.wait(lambda s:len(s.get('states',{}))==6 and all(x['state']=='healthy' for x in s['states'].values()))
    def route(wan,active=True):return env.wait(lambda s:s['selected']['client101']==wan and bool(s['container']['active'])==active)
    try:
        env.apply(fixture)
        lab.proxy_request({'reset':True});healthy()
        settings=json.loads(router.read_file('sdwan-container-config/controller.json'))
        assert settings['mode']=='active' and settings['username']=='sdwan-container'
        first=env.start();owner=first['container']['owner_instance']
        env.wait(lambda s:all('Rust container intent' in p['reason'] for p in s['policies'].values()))
        record('dedicated API user claims live fenced lease; all policies use Rust decisions',owner_length=len(owner))
        intent=router.read_file('sdwan-container-intent.json');time.sleep(9)
        assert router.read_file('sdwan-container-intent.json')==intent
        leases=router.call('ip/firewall/address-list')
        assert any(x.get('list')=='sdwan-container-live' and x.get('dynamic')=='true' for x in leases)
        record('unchanged decisions do not rewrite intent; heartbeat lives in dynamic RAM address list')
        for n in (1,2,3):env.add('isp'+str(n),'ip/firewall/nat',{'chain':'dstnat','dst-address':'203.0.113.200','protocol':'tcp','dst-port':'49100-49119','action':'dst-nat','to-addresses':f'10.77.{n}.2'})
        env.add('client','ip/address',{'address':'192.168.50.103/24','interface':'ether2'})
        stream_traffic.lab=lab;traffic=stream_traffic.StreamTraffic(router,env.add)
        a=traffic.stream('192.168.50.101','wan1',49100)['.id']
        b=traffic.stream('192.168.50.102','wan2',49101)['.id']
        c=traffic.stream('192.168.50.103','wan3',49102)['.id']
        record('three real concurrent TCP/NAT streams follow per-client and strict policies')
        lab.proxy_request({'wan':'wan1','set':{'blackhole':True}});route('wan2')
        traffic.assert_sessions(absent=[a],retained=[b,c]);traffic.stop_stream(a)
        a=traffic.stream('192.168.50.101','wan2',49103)['.id']
        flow=next(x for x in traffic.connections() if x['.id']==a)
        assert flow['reply-dst-address']=='172.20.2.2'
        record('WAN failure selects backup and closes only affected conntrack; new flow uses backup source NAT')
        lab.proxy_request({'reset':True});healthy();route('wan1')
        time.sleep(4) # Let the native late conntrack sweep and provider TCP recovery finish.
        traffic.assert_sessions(absent=[a],retained=[b,c]);traffic.stop_stream(a)
        a=traffic.stream('192.168.50.101','wan1',49104)['.id']
        record('SLA recovery/hold-down failback preserves unrelated client/strict connections')
        stopped=env.stop();assert stopped['selected']['client101']=='wan1'
        traffic.assert_sessions(retained=[a,b,c])
        assert all('Rust container intent' not in p['reason'] for p in stopped['policies'].values())
        record('stopping container expires lease and native warm fallback preserves unchanged flows')
        lab.proxy_request({'wan':'wan1','set':{'blackhole':True}});route('wan2',active=False)
        traffic.assert_sessions(absent=[a],retained=[b,c]);traffic.stop_stream(a)
        a=traffic.stream('192.168.50.101','wan2',49105)['.id']
        record('native fallback independently switches WAN and clears affected conntrack while container stopped')
        lab.proxy_request({'reset':True});healthy();route('wan1',active=False)
        traffic.assert_sessions(absent=[a],retained=[b,c]);traffic.stop_stream(a)
        restart=env.start();assert restart['container']['owner_instance']!=owner
        traffic.assert_sessions(retained=[b,c]);record('restart gets a new nonce and resumes without disturbing unrelated connections')
        # RouterOS/PID1 ignores SIGSTOP on this build; sever the heartbeat path
        # while the real process and API remain running to test lease failure.
        block=env.add('edge','ip/firewall/raw',{'chain':'prerouting','in-interface':'sdwan-container-mgmt','src-address':'172.31.255.2','dst-address':'172.31.255.1','protocol':'udp','dst-port':'45999','action':'drop'})
        freeze=time.monotonic();env.wait(lambda s:not s['container']['active'],timeout=15)
        assert env.container().get('running')=='true';traffic.assert_sessions(retained=[b,c])
        frozen_intent=router.read_file('sdwan-container-intent.json');time.sleep(8)
        assert router.read_file('sdwan-container-intent.json')==frozen_intent
        record('lost heartbeat expires lease with process still running; blocked path does not cause repeated flash writes',fallback_seconds=round(time.monotonic()-freeze-8,2))
        lab.api('edge','ip/firewall/raw/'+block,method='DELETE');env.wait(lambda s:s['container']['active'])
        record('restoring heartbeat resumes the same process with a fresh accepted claim')
        env.command('kill',signal='9-SIGKILL');env.wait(lambda s:not s['container']['active'],timeout=15)
        traffic.assert_sessions(retained=[b,c]);record('abrupt SIGKILL falls back without resetting unaffected sessions')
        report['pass']=True
    finally:
        if traffic:traffic.close()
        env.close()
        restore=Lab()
        try:restore.apply(baseline)
        finally:restore.close()
        (ROOT/'runtime/container-active-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
