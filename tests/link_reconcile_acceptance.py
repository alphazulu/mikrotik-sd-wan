#!/usr/bin/env python3
"""CHR only: dynamic source pins, probes and route updates in isolated tables."""
import json
import ipaddress
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.router import Router
from dynamic_wan_fixture import dynamic_wans
import lab


def main():
    r=Router(ROOT,'api://127.0.0.1:18728');resources=[];files=[];report={'checks':[]}
    before=r.read_file('sdwan-active.json');job_name='sdwan-test-links-reconcile'
    specs=[{'name':'dyn-dhcp','interface':'sdwan-test-dhcp-vlan','kind':'dhcp','probe_table':'sdwan-test-dhcp','icmp_target':'198.18.2.1','probes':[]},
           {'name':'dyn-ppp','interface':'sdwan-test-pppoe','kind':'pppoe','probe_table':'sdwan-test-ppp','icmp_target':'198.18.3.1','probes':[]}]
    policies=[{'name':'dyn-policy','wans':['dyn-dhcp','dyn-ppp']}]
    def add(menu,data):
        row=r.call(menu,data,'PUT');resources.append((menu,row['.id']));return row['.id']
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def state():return json.loads(r.read_file('sdwan-test-reconcile-output.json'))
    def wait(predicate,timeout=25):
        end=time.monotonic()+timeout;last={}
        while time.monotonic()<end:
            last=state()
            if predicate(last):return last
            time.sleep(.3)
        raise AssertionError(last)
    def rows(menu):return r.call(menu)
    try:
        with dynamic_wans() as ids:
            try:
                add('routing/table',{'name':'sdwan-test-policy','fib':'true'})
                add('ip/firewall/mangle',{'chain':'prerouting','action':'jump','jump-target':'sdwan-test','src-address':'198.18.255.255/32','comment':'dynamic-wan-acceptance-only'})
                for index,spec in enumerate(specs,2):
                    wn=spec['name'];table=spec['probe_table']
                    add('routing/table',{'name':table,'fib':'true'})
                    add('ip/route',{'dst-address':'0.0.0.0/0','gateway':'127.0.0.1','routing-table':table,'disabled':'true','comment':'sdwan:v1:pinroute:'+wn})
                    add('ip/route',{'dst-address':'0.0.0.0/0','blackhole':'true','routing-table':table,'distance':'254','comment':'sdwan:v1:pin-blackhole:'+wn})
                    add('ip/route',{'dst-address':'0.0.0.0/0','gateway':'127.0.0.1','routing-table':'sdwan-test-policy','disabled':'true','comment':'sdwan:v1:route:dyn-policy:'+wn})
                    add('tool/netwatch',{'host':f'198.18.{index}.1','type':'icmp','packet-count':'1','interval':'1s','timeout':'100ms','startup-delay':'0s','start-delay':'0s','disabled':'true','comment':'sdwan:v1:icmp:'+wn})
                    add('ip/firewall/mangle',{'chain':'sdwan-test','action':'mark-routing','new-routing-mark':table,'src-address':'0.0.0.0/32','disabled':'true','comment':'sdwan:v1:source:'+wn})
                    add('ip/firewall/mangle',{'chain':'sdwan-test','action':'mark-connection','new-connection-mark':'sdwan-probe-'+wn,'src-address':'0.0.0.0/32','disabled':'true','comment':'sdwan:v1:probe-classify:'+wn+':no-mark'})
                    add('ip/firewall/mangle',{'chain':'sdwan-test','action':'mark-connection','new-connection-mark':'sdwan-out-dyn-policy:'+wn,'comment':'sdwan:v1:classify:dyn-policy:'+wn})
                for name,text in [('sdwan-test-reconcile-input.json',json.dumps({'wans':specs,'policies':policies,'health':{'interval_seconds':1,'timeout_ms':100,'packet_count':1,'packet_interval_ms':50}})),('sdwan-test-reconcile-output.json','{}')]:
                    r.upload(name,text);files.append(name)
                source=(ROOT/'native/sdwan-links.rsc').read_text()+'''\n
:if ([/system/script/job/print count-only where script="sdwan-test-links-reconcile"] > 1) do={ :return }
:local input [:deserialize from=json value=[/file/get [/file/find where name="sdwan-test-reconcile-input.json"] contents]]
:local links [$sdwanResolveWANs wans=($input->"wans")]
:local changes [$sdwanReconcileWANs wans=$links policies=($input->"policies") health=($input->"health")]
:local output [:toarray ""]
:set ($output->"links") $links
:set ($output->"changes") $changes
/file/set [/file/find where name="sdwan-test-reconcile-output.json"] contents=[:serialize to=json value=$output options=json.no-string-conversion]
'''
                add('system/script',{'name':job_name,'source':source,'policy':'read,write,policy,test,sensitive'})
                scheduler=add('system/scheduler',{'name':job_name,'on-event':'/system/script/run '+job_name,'interval':'1s','policy':'read,write,policy,test,sensitive'})
                wait(lambda s:len(s.get('links',[]))==2 and all(x['ready'] for x in s['links']))
                def native_checks():
                    current={x['name']:x for x in state()['links']}
                    for spec in specs:
                        wn=spec['name'];value=current[wn]
                        route=next(x for x in rows('ip/route') if x.get('comment')=='sdwan:v1:pinroute:'+wn)
                        assert route['disabled']=='false' and route['gateway'].removesuffix('@main')==value['route_gateway'].removesuffix('@main'),route
                        pin=next(x for x in rows('routing/rule') if x.get('comment')=='sdwan:v1:pinrule:'+wn)
                        assert pin['src-address']==value['address']+'/32',pin
                        probe=next(x for x in rows('tool/netwatch') if x.get('comment')=='sdwan:v1:icmp:'+wn)
                        assert probe['disabled']=='false' and probe['src-address']==value['address'],probe
                        binding=next(x for x in rows('ip/firewall/mangle') if x.get('comment')=='sdwan:v1:source:'+wn)
                        assert binding['disabled']=='false' and str(ipaddress.IPv4Network(binding['src-address']))==value['address']+'/32',binding
                    assert all(x['disabled']=='true' for x in rows('ip/route') if x.get('comment','').startswith('sdwan:v1:route:dyn-policy:'))
                native_checks()
                wait(lambda s:not s.get('changes'))
                record('local scheduler reconciles DHCP and PPPoE pins/routes/probe sources; stable ticks are idempotent')
                end=time.monotonic()+15
                while time.monotonic()<end:
                    probes=[x for x in rows('tool/netwatch') if x.get('comment') in ('sdwan:v1:icmp:dyn-dhcp','sdwan:v1:icmp:dyn-ppp')]
                    if all(x.get('status')=='up' for x in probes):break
                    time.sleep(.5)
                else:raise AssertionError(probes)
                record('actual ICMP probes reach both providers through DHCP VLAN and PPPoE pinned tables')
                lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'disabled':'true'},'PATCH')
                wait(lambda s:any(x['name']=='dyn-dhcp' and not x['ready'] for x in s.get('links',[])))
                assert not any(x.get('comment')=='sdwan:v1:pinrule:dyn-dhcp' for x in rows('routing/rule'))
                assert next(x for x in rows('tool/netwatch') if x.get('comment')=='sdwan:v1:icmp:dyn-dhcp')['disabled']=='true'
                assert next(x for x in rows('ip/route') if x.get('comment')=='sdwan:v1:pinroute:dyn-dhcp')['disabled']=='true'
                assert next(x for x in rows('tool/netwatch') if x.get('comment')=='sdwan:v1:icmp:dyn-ppp')['disabled']=='false'
                record('lost DHCP lease disables only its probes/routes and removes the obsolete source pin')
                lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'disabled':'false'},'PATCH')
                wait(lambda s:all(x['ready'] for x in s.get('links',[])))
                lab.api('edge','interface/pppoe-client/'+ids['pppoe'],{'disabled':'true'},'PATCH')
                wait(lambda s:any(x['name']=='dyn-ppp' and not x['ready'] for x in s.get('links',[])))
                assert next(x for x in rows('tool/netwatch') if x.get('comment')=='sdwan:v1:icmp:dyn-ppp')['disabled']=='true'
                lab.api('isp3','ppp/profile/'+ids['ppp_profile'],{'remote-address':'172.31.3.22'},'PATCH')
                lab.api('edge','interface/pppoe-client/'+ids['pppoe'],{'disabled':'false'},'PATCH')
                wait(lambda s:any(x['name']=='dyn-ppp' and x['ready'] and x['address']=='172.31.3.22' for x in s.get('links',[])))
                native_checks()
                assert not any(x.get('src-address')=='172.31.3.2/32' and x.get('comment')=='sdwan:v1:pinrule:dyn-ppp' for x in rows('routing/rule'))
                record('PPPoE address change updates sources and pins; policy routes remain closed until caller validates SLA')
                assert r.read_file('sdwan-active.json')==before
            finally:
                for menu,identifier in reversed(resources):
                    if menu=='system/scheduler':r.call(menu+'/'+identifier,{'disabled':'true'},'PATCH')
                end=time.monotonic()+5
                while time.monotonic()<end:
                    jobs=r.call('system/script/job/print',{'.proplist':'script'},'POST')
                    if not any(x.get('script')==job_name for x in jobs):break
                    time.sleep(.2)
                for row in rows('routing/rule'):
                    if row.get('comment','') in ('sdwan:v1:pinrule:dyn-dhcp','sdwan:v1:pinrule:dyn-ppp'):r.call('routing/rule/'+row['.id'],method='DELETE')
                for row in rows('tool/netwatch'):
                    if row.get('comment') in ('sdwan:v1:icmp:dyn-dhcp','sdwan:v1:icmp:dyn-ppp'):r.call('tool/netwatch/'+row['.id'],method='DELETE')
                for menu,identifier in reversed(resources):
                    if menu!='tool/netwatch':r.call(menu+'/'+identifier,method='DELETE')
                resources.clear()
    except Exception as error:
        report['checks'].append({'check':'link reconciliation interrupted','pass':False,'detail':str(error)});raise
    finally:
        for f in r.call('file/print',{'.proplist':'.id,name'},'POST'):
            if f['name'] in files:r.call('file/'+f['.id'],method='DELETE')
        for env in r.call('system/script/environment/print',{'.proplist':'.id,name'},'POST'):
            if env['name']=='sdwanLinkFingerprints':r.call('system/script/environment/'+env['.id'],method='DELETE')
        (ROOT/'runtime/link-reconcile-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
