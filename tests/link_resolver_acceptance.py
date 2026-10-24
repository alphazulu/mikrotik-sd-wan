#!/usr/bin/env python3
"""CHR only: read-only native resolution of actual DHCP and PPPoE sessions."""
import json
import copy
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.router import Router
from dynamic_wan_fixture import dynamic_wans
import lab


def main():
    r=Router(ROOT,'api://127.0.0.1:18728');report={'checks':[]};files=[]
    before=r.read_file('sdwan-active.json')
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    specs=[{'name':'static','interface':'ether2','address':'172.20.1.2','gateway':'172.20.1.1'},{'name':'dhcp','interface':'sdwan-test-dhcp-vlan','kind':'dhcp'},{'name':'ppp','interface':'sdwan-test-pppoe','kind':'pppoe'}]
    def resolve(wans=specs):
        script=(ROOT/'native/sdwan-links.rsc').read_text()+'\n:local wans [:deserialize from=json value=[/file/get [/file/find where name="sdwan-test-links-input.json"] contents]]\n:local out [$sdwanResolveWANs wans=$wans]\n/file/set [/file/find where name="sdwan-test-links-output.json"] contents=[:serialize to=json value=$out options=json.no-string-conversion]\n'
        for name,text in [('sdwan-test-links-input.json',json.dumps(wans)),('sdwan-test-links-output.json','{}'),('sdwan-test-links.rsc',script)]:
            r.upload(name,text)
            if name not in files:files.append(name)
        r.call('import',{'file-name':'sdwan-test-links.rsc'},'POST')
        value=json.loads(r.read_file('sdwan-test-links-output.json'))
        assert isinstance(value,list),value
        return {x['name']:x for x in value}
    try:
        with dynamic_wans() as ids:
            out=resolve()
            assert all(w['ready'] for w in out.values()),out
            assert out['static']['route_gateway']=='172.20.1.1%ether2@main'
            assert out['dhcp']['address'] in ('172.31.2.2','172.31.2.3') and out['dhcp']['route_gateway']=='172.31.2.1%sdwan-test-dhcp-vlan@main'
            assert out['ppp']['address']=='172.31.3.2' and out['ppp']['gateway']=='172.31.3.1' and out['ppp']['route_gateway']=='sdwan-test-pppoe'
            record('native resolver reads static address, DHCP lease and PPPoE local/remote without saved lease snapshots')
            lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'disabled':'true'},'PATCH')
            lab.api('edge','interface/pppoe-client/'+ids['pppoe'],{'disabled':'true'},'PATCH')
            time.sleep(.5);out=resolve();assert not out['dhcp']['ready'] and not out['ppp']['ready'] and out['static']['ready'],out
            record('loss of DHCP lease and PPPoE session is unavailable despite physical carrier remaining up')
            lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'disabled':'false'},'PATCH')
            lab.api('edge','interface/pppoe-client/'+ids['pppoe'],{'disabled':'false'},'PATCH')
            end=time.monotonic()+30
            while time.monotonic()<end:
                out=resolve()
                if out['dhcp']['ready'] and out['ppp']['ready']:break
                time.sleep(.5)
            else:raise AssertionError(out)
            record('DHCP rebind and PPPoE reconnect are discovered without external controller or credentials export')
            lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'disabled':'true'},'PATCH')
            for lease in lab.api('isp2','ip/dhcp-server/lease'):
                if lease.get('server')=='sdwan-test-dhcp':lab.api('isp2','ip/dhcp-server/lease/'+lease['.id'],method='DELETE')
            ids['add']('isp2','ip/address',{'address':'172.31.2.254/24','interface':'sdwan-test-dhcp-vlan','comment':'dynamic-wan-acceptance-only'})
            lab.api('isp2','ip/pool/'+ids['dhcp_pool'],{'ranges':'172.31.2.20-172.31.2.21'},'PATCH')
            lab.api('isp2','ip/dhcp-server/network/'+ids['dhcp_network'],{'gateway':'172.31.2.254'},'PATCH')
            lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'disabled':'false'},'PATCH')
            end=time.monotonic()+30
            while time.monotonic()<end:
                out=resolve()
                if out['dhcp']['ready'] and out['dhcp']['address'] in ('172.31.2.20','172.31.2.21') and out['dhcp']['gateway']=='172.31.2.254':break
                time.sleep(.5)
            else:raise AssertionError(out)
            record('new DHCP lease address and gateway replace old values without changing configuration')
            lab.api('edge','interface/pppoe-client/'+ids['pppoe'],{'disabled':'true'},'PATCH')
            lab.api('isp3','ppp/profile/'+ids['ppp_profile'],{'remote-address':'172.31.3.22'},'PATCH')
            lab.api('edge','interface/pppoe-client/'+ids['pppoe'],{'disabled':'false'},'PATCH')
            end=time.monotonic()+30
            while time.monotonic()<end:
                out=resolve()
                if out['ppp']['ready'] and out['ppp']['address']=='172.31.3.22':break
                time.sleep(.5)
            else:raise AssertionError(out)
            record('PPPoE reconnect with another local IP resolves the new dynamic /32 and interface gateway')
            # Keep provider-created routes outside main; option 121 must win
            # over the conflicting option-3 gateway (172.31.2.254).
            lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'default-route-tables':'sdwan-test-acquire'},'PATCH')
            lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'add-default-route':'yes','disabled':'true'},'PATCH')
            lab.api('isp2','ip/dhcp-server/network/'+ids['dhcp_network'],{'dhcp-option':'sdwan-test-classless'},'PATCH')
            lab.api('edge','ip/dhcp-client/'+ids['dhcp'],{'disabled':'false'},'PATCH')
            isolated=copy.deepcopy(specs);isolated[1]['probe_table']='sdwan-test-acquire'
            end=time.monotonic()+30
            while time.monotonic()<end:
                out=resolve(isolated)
                if out['dhcp']['ready'] and out['dhcp']['gateway']=='172.31.2.1':break
                time.sleep(.5)
            else:raise AssertionError(out)
            routes=r.call('ip/route')
            assert any(x.get('dynamic')=='true' and x.get('dst-address')=='0.0.0.0/0' and x.get('routing-table')=='sdwan-test-acquire' for x in routes)
            assert not any(x.get('routing-table','main')=='main' and x.get('dst-address')=='0.0.0.0/0' and x.get('gateway','').startswith('172.31.2.') for x in routes)
            record('DHCP classless default gateway wins over option 3; acquired routes stay outside main')
            duplicate=specs+[{'name':'duplicate','interface':'ether2','address':'172.20.1.2','gateway':'172.20.1.1'}]
            out=resolve(duplicate);assert not out['static']['ready'] and not out['duplicate']['ready']
            record('duplicate local WAN addresses fail closed instead of cross-WAN probe leakage')
            assert r.read_file('sdwan-active.json')==before
    except Exception as error:
        report['checks'].append({'check':'link resolver interrupted','pass':False,'detail':str(error)});raise
    finally:
        for f in r.call('file/print',{'.proplist':'.id,name'},'POST'):
            if f['name'] in files:r.call('file/'+f['.id'],method='DELETE')
        (ROOT/'runtime/link-resolver-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
