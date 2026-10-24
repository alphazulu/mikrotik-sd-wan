#!/usr/bin/env python3
"""CHR ONLY: real APN routing ownership; no LTE modem or production access."""
import json
from pathlib import Path
import secrets
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.router import Router


def main():
    r=Router(ROOT,'api://127.0.0.1:18728');assert r.call('system/identity')['name']=='sdwan-edge'
    report={'checks':[]};files=[];pid=None;entry=None
    library=(ROOT/'native/sdwan-links.rsc').read_text()
    name='sdwan-test-lte-apn';password=secrets.token_urlsafe(24)
    active=r.read_file('sdwan-active.json')
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def run(body):
        r.upload('sdwan-test-lte-entry.json',json.dumps(entry or {}));r.upload('sdwan-test-lte-result.json','{}')
        source=library+'\n:local entry [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="sdwan-test-lte-entry.json"] contents]]\n'+body+'\n/file/set [/file/find where name="sdwan-test-lte-result.json"] contents=[:serialize to=json value=$result options=json.no-string-conversion]\n'
        r.upload('sdwan-test-lte-apn.rsc',source)
        for f in ('sdwan-test-lte-entry.json','sdwan-test-lte-result.json','sdwan-test-lte-apn.rsc'):
            if f not in files:files.append(f)
        r.call('import',{'file-name':'sdwan-test-lte-apn.rsc'},'POST')
        return json.loads(r.read_file('sdwan-test-lte-result.json'))
    def settings():
        rows=r.call('interface/lte/apn/print',{'.proplist':'.id,name,add-default-route,default-route-distance,use-peer-dns,use-network-apn,authentication,user,password','.query':['name='+name]},'POST')
        assert len(rows)==1
        # Read only the credentials of this generated fixture, never a user APN.
        rows[0]['password']=r.call('interface/lte/apn/get',{'number':rows[0]['.id'],'value-name':'password'},'POST')['ret']
        assert rows[0]['password']==password,'Fixture APN credentials changed'
        return rows[0]
    try:
        pid=r.call('interface/lte/apn',{'name':name,'apn':'internet','authentication':'pap','user':'fixture-only','password':password,'use-peer-dns':'false','use-network-apn':'false','add-default-route':'true','default-route-distance':'77','ip-type':'ipv4'},'PUT')['.id']
        original=settings();entry=run(':local result [$sdwanLTEAPNCapture profile="'+name+'" selected=[:toarray ""]]')
        assert settings()==original and password not in json.dumps(entry)
        assert entry['original_add'] is True and entry['original_distance']==77
        record('read-only native APN baseline captures routing flags without credentials')
        run('$sdwanLTEAPNApply entry=$entry\n:local result true')
        changed=settings();assert changed['add-default-route']=='false'
        assert all(changed[k]==original[k] for k in original if k not in ('add-default-route','default-route-distance'))
        record('APN adoption disables automatic default only; distance, DNS and authentication survive')
        assert run(':local result [$sdwanLTEAPNRestore entry=$entry]') is True
        assert settings()==original
        assert settings()['default-route-distance']=='77'
        record('owned baseline rollback restores APN automatic route without changing other settings')
        previous=entry;r.call('interface/lte/apn/'+pid,{'add-default-route':'false'},'PATCH')
        entry=run(':local result [$sdwanLTEAPNCapture profile="'+name+'" selected=[:toarray ""]]')
        assert entry['original_add'] is False
        run('$sdwanLTEAPNApply entry=$entry\n:local result true')
        assert run(':local result [$sdwanLTEAPNRestore entry=$entry]') is True
        assert settings()['add-default-route']=='false'
        r.call('interface/lte/apn/'+pid,{'add-default-route':'true'},'PATCH');assert settings()['default-route-distance']=='77'
        entry=previous
        record('APN already configured add-default-route=no is adopted idempotently; latent distance survives')
        run('$sdwanLTEAPNApply entry=$entry\n:local result true')
        r.call('interface/lte/apn/'+pid,{'add-default-route':'true','default-route-distance':'88'},'PATCH')
        assert run(':local result [$sdwanLTEAPNRestore entry=$entry]') is False
        assert settings()['default-route-distance']=='88' and settings()['add-default-route']=='true'
        record('rollback respects operator changes instead of overriding APN ownership drift')
        r.call('interface/lte/apn/'+pid,method='DELETE');pid=None
        assert run(':local result [$sdwanLTEAPNRestore entry=$entry]') is False
        record('missing APN is skipped safely on rollback')
        assert r.read_file('sdwan-active.json')==active
    finally:
        if pid:r.call('interface/lte/apn/'+pid,method='DELETE')
        for row in r.call('file/print',{'.proplist':'.id,name'},'POST'):
            if row.get('name') in files:r.call('file/'+row['.id'],method='DELETE')
        (ROOT/'runtime/lte-apn-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
