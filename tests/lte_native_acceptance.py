#!/usr/bin/env python3
"""CHR LTE resolver and APN reference guards using declared device adapter."""
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from lte_fixture import lte_wan,adapted_links,IFACE,PROFILE,STATE
from sdwan.router import Router
import lab


def main():
    r=Router(ROOT);before=r.read_file('sdwan-active.json');report={'physical_modem_tested':False,'checks':[]};files=[]
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def execute(code):
        source=adapted_links((ROOT/'native/sdwan-links.rsc').read_text())+'\n'+code+'\n/file/set [/file/find where name="sdwan-test-lte-native-out.json"] contents=[:serialize to=json value=$result options=json.no-string-conversion]\n'
        for name,text in [('sdwan-test-lte-native-out.json','{}'),('sdwan-test-lte-native.rsc',source)]:
            r.upload(name,text)
            if name not in files:files.append(name)
        r.call('import',{'file-name':'sdwan-test-lte-native.rsc'},'POST')
        return json.loads(r.read_file('sdwan-test-lte-native-out.json'))
    def resolve(profile=PROFILE):
        spec=json.dumps([{'name':'lte','kind':'lte','interface':IFACE,'apn_profile':profile}])
        r.upload('sdwan-test-lte-spec.json',spec)
        if 'sdwan-test-lte-spec.json' not in files:files.append('sdwan-test-lte-spec.json')
        return execute(':local specs [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="sdwan-test-lte-spec.json"] contents]]\n:local result [$sdwanResolveWANs wans=$specs]')[0]
    try:
        with lte_wan(add_default=False) as (ids,adapter):
            normalized=execute(':local refs [/interface/lte/apn/find where name="'+PROFILE+'"]\n:local result [:toarray ""]\n:set ($result->"ids") [$sdwanLTENormalizeProfiles values=$refs]\n:set ($result->"names") [$sdwanLTENormalizeProfiles values="'+PROFILE+'"]')
            assert normalized['ids']==normalized['names']==[PROFILE],normalized
            record('APN reference names and native ID arrays normalize without losing profile boundaries')
            out=resolve();assert out['ready'] and out['address']=='172.31.3.2' and out['route_gateway']==IFACE,out
            record('LTE resolver uses real dynamic IPv4 and interface gateway without a DHCP client or lease snapshot')
            out=resolve('previous-apn');assert not out['ready'] and 'profile changed' in out['link_reason'],out
            record('APN profile drift closes the WAN')
            apn=next(x for x in r.call('interface/lte/apn/print',{'.proplist':'.id,name'},'POST') if x['name']==PROFILE)['.id']
            r.call('interface/lte/apn/'+apn,{'add-default-route':'true'},'PATCH');out=resolve();assert not out['ready'] and 'not adopted' in out['link_reason']
            r.call('interface/lte/apn/'+apn,{'add-default-route':'false'},'PATCH')
            record('unadopted APN automatic default cannot make LTE ready')
            r.call('interface/pppoe-client/'+ids['pppoe'],{'disabled':'true'},'PATCH');out=resolve();assert not out['ready']
            lab.api('isp3','ppp/profile/'+ids['ppp_profile'],{'remote-address':'172.31.3.22'},'PATCH');r.call('interface/pppoe-client/'+ids['pppoe'],{'disabled':'false'},'PATCH')
            end=time.monotonic()+25
            while time.monotonic()<end:
                out=resolve()
                if out['ready'] and out['address']=='172.31.3.22':break
                time.sleep(.3)
            else:raise AssertionError(out)
            record('lost data link and new IPv4 are resolved from runtime state')
            rows=json.loads(r.read_file(STATE));rows.append({'id':'*shadow','name':'unselected-modem','profiles':[PROFILE]});r.upload(STATE,json.dumps(rows))
            result=execute(':local result "not rejected"\n:onerror denied in={ :local snap [$sdwanLTEAPNCapture profile="'+PROFILE+'" selected=[:toarray "'+IFACE+'"]] } do={ :set result $denied }')
            assert 'shared with unselected modem' in result,result
            record('native shared-profile guard handles arrays and disabled unselected modems')
            r.upload(STATE,json.dumps(rows[:1]))
            snap=execute(':local result [$sdwanLTEAPNCapture profile="'+PROFILE+'" selected=[:toarray "'+IFACE+'"]]')
            assert snap['apn_profile']==PROFILE and snap['original_add'] is False
            record('native APN capture accepts the selected modem and original add-default-route=no')
        assert r.read_file('sdwan-active.json')==before
    finally:
        # Restore production library globals before the static controller ticks.
        r.call('import',{'file-name':'sdwan-links.rsc'},'POST')
        for f in r.call('file/print',{'.proplist':'.id,name'},'POST'):
            if f.get('name') in files:r.call('file/'+f['.id'],method='DELETE')
        (ROOT/'runtime/lte-native-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
