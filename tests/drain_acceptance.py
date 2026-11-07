#!/usr/bin/env python3
"""CHR ONLY: real TCP flows across protected WAN maintenance changes."""
import argparse
import copy
import json
from pathlib import Path
import time
from network_lab import NetworkLab
import stream_traffic


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',type=Path,required=True);args=p.parse_args()
    report={'checks':[],'pass':False};traffic=None
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    try:
        with NetworkLab(args.lab_root) as env:
            router=env.router;cfg=copy.deepcopy(env.before)
            for wan in cfg['wans']:wan.pop('admin_state',None);wan.pop('drain_timeout_seconds',None)
            # Scheduling jitter during encrypted backups is unrelated to drain.
            for profile in cfg['sla_profiles'].values():profile['jitter_ms']=100
            cfg['revision']='drain-fixture';env.apply(cfg);env.healthy()
            for n in (1,2,3):env.add('isp'+str(n),'ip/firewall/nat',{'chain':'dstnat','dst-address':'203.0.113.200','protocol':'tcp','dst-port':'59010-59029','action':'dst-nat','to-addresses':f'10.77.{n}.2'})
            if not any(x.get('address')=='192.168.50.103/24' for x in env.lab.api('client','ip/address')):env.add('client','ip/address',{'address':'192.168.50.103/24','interface':'ether2'})
            stream_traffic.lab=env.lab;traffic=stream_traffic.StreamTraffic(router,env.add)
            try:
                a=traffic.stream('192.168.50.101','wan1',59010)['.id'];b=traffic.stream('192.168.50.102','wan2',59011)['.id'];c=traffic.stream('192.168.50.103','wan3',59012)['.id']
                cfg['revision']='drain-start';cfg['wans'][0].update(admin_state='drain',drain_timeout_seconds=0);env.apply(cfg)
                s=env.wait(lambda s:s['selected']['client101']=='wan2' and s['maintenance']['wan1']['effective']=='drain');assert s['states']['default/wan1']['state']=='healthy'
                time.sleep(4);traffic.assert_sessions(retained=[a,b,c]);d=traffic.stream('192.168.50.101','wan2',59013)['.id']
                record('drain via protected apply preserves real established WAN1 flows beyond late sweep; new flows use WAN2')
                cfg['revision']='drain-strict';cfg['wans'][2].update(admin_state='drain',drain_timeout_seconds=0);env.apply(cfg)
                env.wait(lambda s:s['selected']['strict103']=='none');time.sleep(4);traffic.assert_sessions(retained=[a,b,c,d])
                record('strict policy admits no new WAN3 flow during drain while its existing TCP stream survives')
                cfg['revision']='drain-cancel';cfg['wans'][2]['admin_state']='enabled';env.apply(cfg);env.wait(lambda s:s['selected']['strict103']=='wan3');traffic.assert_sessions(retained=[a,b,c,d])
                record('cancelling drain restores admission without resetting the retained strict session')
                cfg['revision']='drain-emergency';cfg['wans'][0]['admin_state']='down';env.apply(cfg);env.wait(lambda s:s['maintenance']['wan1']['effective']=='down');traffic.assert_sessions(absent=[a],retained=[b,c,d]);traffic.stop_stream(a)
                record('emergency down retires previously drained WAN1 conntrack after selection already moved; other WANs survive')
                cfg['revision']='drain-timeout';cfg['wans'][2].update(admin_state='drain',drain_timeout_seconds=8);env.apply(cfg)
                env.wait(lambda s:s['maintenance']['wan3']['effective']=='down',timeout=20);traffic.assert_sessions(absent=[c],retained=[b,d]);traffic.stop_stream(c)
                record('drain deadline expires in RouterOS RAM and retires only the affected strict flow')
                cfg['revision']='drain-link-test';cfg['wans'][0]['admin_state']='enabled';cfg['wans'][2]['admin_state']='enabled';env.apply(cfg);env.healthy();time.sleep(4)
                traffic.assert_sessions(absent=[d],retained=[b]);traffic.stop_stream(d)
                a=traffic.stream('192.168.50.101','wan1',59014)['.id']
                cfg['revision']='drain-before-failure';cfg['wans'][0].update(admin_state='drain',drain_timeout_seconds=0);env.apply(cfg);env.wait(lambda s:s['selected']['client101']=='wan2');traffic.assert_sessions(retained=[a,b])
                env.lab.proxy_request({'wan':'wan1','set':{'blackhole':True}});env.wait(lambda s:s['states']['default/wan1']['state']=='down');traffic.assert_sessions(absent=[a],retained=[b]);traffic.stop_stream(a)
                record('physical/SLA failure of an already drained WAN retires its retained connection without another selection transition')
                report['pass']=True
            finally:
                traffic.close();traffic=None
    finally:
        if traffic:traffic.close()
        (args.lab_root/'runtime/drain-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
