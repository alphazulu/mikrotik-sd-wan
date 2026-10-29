#!/usr/bin/env python3
"""CHR ONLY: retire a real standby UDP tuple with an incomplete address cache.

Execute the old and current native function bodies on the existing isolated
fabric. The controller's live functions/cache, addresses and routes are retained.
Empty/oversized inventory cases replace only the function's read expression.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(ROOT/'tests')]
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic

TAG='sdwan-retire-cache-acceptance'
RESULT='sdwanRetireCacheAcceptance'
POLICY='read,write,policy,test,sensitive'


def function(source):
    start=source.index(':global sdwanOverlayRetireTransport do={')
    end=source.index('\n:global sdwanOverlayRebind do={',start)
    return source[start:end].replace(':global sdwanOverlayRetireTransport do={',':local retireFixture do={',1)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--lab-root',required=True,type=Path)
    p.add_argument('--previous-source',required=True,type=Path)
    args=p.parse_args();v=VPNLab(args.lab_root);a=v.routers['sitea'];traffic=None;locks=[];created=[]
    current=(ROOT/'native/sdwan-overlay.rsc').read_text();old=args.previous_source.read_text()
    report={'pass':False,'checks':[],'production_access':False,
            'source_sha256':hashlib.sha256(current.encode()).hexdigest(),
            'previous_source_sha256':hashlib.sha256(old.encode()).hexdigest()}
    before=None;script=None;scheduler=None
    def wait(fn,seconds=20):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            result=fn()
            if result:return result
            time.sleep(.2)
        raise AssertionError('Standby/cache fixture did not converge')
    def rows(router):
        return router.call('ip/firewall/connection/print',{
            '.proplist':'.id,protocol,src-address,src-port,dst-address,dst-port,orig-bytes,repl-bytes'},'POST')
    def standby():
        return [r for r in rows(a) if r.get('protocol')=='udp' and r.get('src-port')=='51822'
                and r.get('dst-port')=='51822' and '198.18.100.1' in (r.get('src-address'),r.get('dst-address'))]
    def retained():
        return {(node,r['.id']):int(r['orig-bytes']) for node,router,port in
                [('sitea',a,'51821'),('hub',v.routers['hub'],'51823')]
                for r in rows(router) if r.get('protocol')=='udp' and r.get('dst-port')==port}
    def run(label,text,mutate='',inventory=None,removed=True):
        wait(standby);protected=retained();assert len(protected)>=2
        body=function(text)
        if inventory is not None:
            needle='[/ip/address/print as-value]'
            assert body.count(needle)==1
            body=body.replace(needle,inventory)
        source='''/system/scheduler/disable [/system/scheduler/find where name="'''+TAG+'''"]
:global sdwanOverlayTransport
:global '''+RESULT+'''
:onerror failure in={
'''+body+'''
:local saved [:serialize to=json value=($sdwanOverlayTransport->"hub-wan2") options=json.no-string-conversion]
:local previous [:deserialize from=json value=$saved options=json.no-string-conversion]
'''+mutate+'''
:local count [$retireFixture previous=$previous]
:if ($saved != [:serialize to=json value=($sdwanOverlayTransport->"hub-wan2") options=json.no-string-conversion]) do={ :error "live transport cache was modified" }
:set '''+RESULT+''' [:serialize to=json value={"removed"=$count} options=json.no-string-conversion]
} do={ :set '''+RESULT+''' [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
'''
        a.call('system/script/'+script,{'source':source},'PATCH')
        for row in a.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+RESULT]},'POST'):
            a.call('system/script/environment/'+row['.id'],method='DELETE')
        a.call('system/scheduler/'+scheduler,{'disabled':'false'},'PATCH')
        def completed():
            rows=a.call('system/script/environment/print',{'.proplist':'value','.query':['name='+RESULT]},'POST')
            if len(rows)!=1:return None
            try:value=json.loads(rows[0].get('value',''))
            except (ValueError,TypeError):return None
            return value if isinstance(value,dict) and ('removed' in value or 'error' in value) else None
        result=wait(completed);assert 'error' not in result,(label,result)
        assert type(result.get('removed')) is int and (result['removed']>=1 if removed else result['removed']==0),(label,result)
        now=retained();assert protected.keys()<=now.keys(),label+': unrelated primary/SiteB UDP retired'
        assert all(now[k]>=value for k,value in protected.items()),label+': unrelated UDP counters regressed'
        traffic.assert_sessions(retained=flows)
        report['checks'].append({'check':label,'pass':True,'removed':result['removed'],
                                 'inventory_stub':inventory is not None})
        print('PASS '+label,flush=True)
    try:
        for name in ['network-soak.lock','lab.lock']:
            h=(v.run/name).open('a');fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(h)
        for name in ('hub','sitea','siteb','nata','natb'):
            assert v.lab.qmp(name,'query-name')['name']=='sdwan-overlay-'+name
        assert not a.status().get('container',{}).get('active'),'Use native restored baseline'
        before=a.read_file('sdwan-active.json')
        for menu in ('system/script','system/scheduler'):
            assert not a.call(menu+'/print',{'.proplist':'.id','.query':['name='+TAG]},'POST'),'Fixture already exists'
        script=a.call('system/script/add',{'name':TAG,'source':'','policy':POLICY,'comment':TAG},'POST')['ret'];created.append('system/script')
        scheduler=a.call('system/scheduler/add',{'name':TAG,'on-event':'/system/script/run '+TAG,
                      'interval':'1s','disabled':'true','policy':POLICY,'comment':TAG},'POST')['ret'];created.append('system/scheduler')
        traffic=VPNTraffic(v);traffic.prepare()
        flows=[traffic.stream(59410,'sdwan-out-default:wan1',target='198.19.100.2'),
               traffic.stream(59419,'no-mark',target='10.201.1.2')]
        partial=':set ($previous->"local_addresses") {"172.31.255.1"=true}'
        run('old helper reproduces zero removal with an incomplete snapshot',old,partial,removed=False)
        run('current helper retires the same real standby tuple with an incomplete snapshot',current,partial)
        run('fresh inventory admits local socket source missing from both cache and WAN hint',current,
            partial+'; :set ($previous->"source") ""')
        run('empty early snapshot still admits a current local socket',current,
            ':set ($previous->"local_addresses") [:toarray ""]; :set ($previous->"source") ""')
        run('saved WAN source remains usable when current inventory is absent',current,partial,inventory='[:toarray ""]')
        run('saved socket snapshot remains usable without WAN hint or current inventory',current,
            ':set ($previous->"local_addresses") {"100.65.10.2"=true}; :set ($previous->"source") ""',inventory='[:toarray ""]')
        for flag in ('disabled','invalid'):
            run(flag+' current address does not authorize retirement',current,
                partial+'; :set ($previous->"source") ""',
                inventory='[:deserialize from=json options=json.no-string-conversion value='+json.dumps(json.dumps([{'address':'100.65.10.2/30',flag:True}],separators=(',',':')))+']',removed=False)
        for label,change in [('unknown endpoint',':set ($previous->"endpoint") "0.0.0.0"'),
                             ('wrong endpoint',':set ($previous->"endpoint") "198.18.100.254"'),
                             ('wrong remote port',':set ($previous->"endpoint_port") 51823'),
                             ('invalid local port',':set ($previous->"listen_port") 65536'),
                             ('invalid cache type',':set ($previous->"local_addresses") "invalid"'),
                             ('oversized prior cache',':local large [:toarray ""]; :for i from=0 to=1024 do={ :set ($large->[:tostr $i]) true }; :set ($previous->"local_addresses") $large')]:
            run(label+' does not delete the real standby tuple',current,change,removed=False)
        run('oversized current inventory refuses retirement',current,
            inventory='[:toarray "'+','.join(['1']*1025)+'"]',removed=False)
        report['pass']=True
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error);raise
    finally:
        errors=[]
        try:
            if traffic:traffic.close()
            for menu in reversed(created):
                for row in a.call(menu+'/print',{'.proplist':'.id,comment','.query':['name='+TAG]},'POST'):
                    assert row.get('comment')==TAG
                    a.call(menu+'/'+row['.id'],method='DELETE')
            for row in a.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+RESULT]},'POST'):
                a.call('system/script/environment/'+row['.id'],method='DELETE')
            if before is not None:assert a.read_file('sdwan-active.json')==before,'Active configuration changed'
        except BaseException as error:
            report['pass']=False;errors.append(type(error).__name__+': '+str(error));raise
        finally:
            report['cleanup_errors']=errors;report['cleanup_pass']=not errors
            (v.run/'overlay-retirement-cache-validation.json').write_text(json.dumps(report,indent=2)+'\n')
            v.close()
            for h in reversed(locks):h.close()


if __name__=='__main__':main()
