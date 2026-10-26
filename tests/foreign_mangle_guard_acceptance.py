#!/usr/bin/env python3
"""Actual CHR/x86 firewall guards in the explicitly owned LTE lab, no deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from lte_rndis_acceptance import Fixture


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lab-root',required=True,type=Path);args=parser.parse_args()
    fixture=Fixture(args.lab_root.resolve());names=['foreign-guard-payload.rsc','foreign-guard-wrapper.rsc','foreign-guard-result.json']
    report={'pass':False,'production_modified':False,'inventory_adapter':False,'checks':[],'sources':{}}
    try:
        fixture.connect()
        for node in ('x86','chr'):
            router=fixture.routers[node]
            for label,base in [('root',args.lab_root),('candidate',ROOT)]:
                source=(base/'native/sdwan-install.rsc').read_text();report['sources'][label]=hashlib.sha256(source.encode()).hexdigest()
                start=source.index(':local cfgJSON ') if ':local cfgJSON ' in source else source.index(':local cfg ')
                guard=source[:start]+':error "test-guard-passed"\n'
                a=source.index(':foreach id in=[/ip/firewall/filter/find] do={');b=source.index('# Validate policy invariants',a)
                fast=source[a:b]
                cases=[('routing','ip/firewall/mangle',{'chain':'prerouting','action':'mark-routing','new-routing-mark':'main'},'foreign mangle',source),
                       ('connection','ip/firewall/mangle',{'chain':'prerouting','action':'mark-connection','new-connection-mark':'guard-legacy'},'foreign mangle',source),
                       ('route','ip/firewall/mangle',{'chain':'prerouting','action':'route','route-dst':'192.0.3.1'},'foreign mangle',source),
                       ('disabled','ip/firewall/mangle',{'chain':'prerouting','action':'mark-routing','new-routing-mark':'main','disabled':'true'},'test-guard-passed',guard),
                       ('owned','ip/firewall/mangle',{'chain':'prerouting','action':'mark-connection','new-connection-mark':'guard-owned','comment':'sdwan:v1:guard-only'},'test-guard-passed',guard),
                       ('qos','ip/firewall/mangle',{'chain':'prerouting','action':'mark-packet','new-packet-mark':'guard-qos'},'test-guard-passed',guard),
                       ('notrack','ip/firewall/raw',{'chain':'prerouting','action':'notrack'},'RAW notrack',source),
                       ('disabled-notrack','ip/firewall/raw',{'chain':'prerouting','action':'notrack','disabled':'true'},'test-guard-passed',guard),
                       ('fasttrack','ip/firewall/filter',{'chain':'forward','action':'fasttrack-connection'},'FastTrack must be declared',fast),
                       ('declared-fasttrack','ip/firewall/filter',{'chain':'forward','action':'fasttrack-connection'},'test-guard-passed',fast),
                       ('disabled-fasttrack','ip/firewall/filter',{'chain':'forward','action':'fasttrack-connection','disabled':'true'},'test-guard-passed',fast)]
                for name,menu,fields,expected,payload in cases:
                    row=router.call(menu,dict({'src-address':'198.19.99.254/32','comment':'foreign-guard-acceptance'},**fields),'PUT');id=row['.id']
                    fixture.created.append((router,menu,id))
                    if 'fasttrack' in name:
                        cfg={'disable_fasttrack':[{'.id':id}]} if name=='declared-fasttrack' else {}
                        payload=':local cfg [:deserialize from=json value='+json.dumps(json.dumps(cfg))+']\n'+fast+':error "test-guard-passed"\n'
                    router.upload(names[0],payload);router.upload(names[2],'{}')
                    router.upload(names[1],':local caught ""\n:onerror failure in={ /import file-name="'+names[0]+'" } do={ :set caught $failure }\n/file/set [/file/find where name="'+names[2]+'"] contents=[:serialize to=json value={"error"=$caught} options=json.no-string-conversion]\n')
                    before=router.call(menu+'/print',{'.proplist':'.id,action,comment,disabled'},'POST')
                    files=router.call('file/print',{'.proplist':'name,size'},'POST')
                    router.call('import',{'file-name':names[1]},'POST');result=json.loads(router.read_file(names[2]))
                    assert expected in result.get('error',''),(node,label,name,result)
                    assert router.call(menu+'/print',{'.proplist':'.id,action,comment,disabled'},'POST')==before
                    after=router.call('file/print',{'.proplist':'name,size'},'POST')
                    assert [x for x in after if x['name']!=names[2]]==[x for x in files if x['name']!=names[2]]
                    assert not router.call('system/scheduler?name=sdwan-controller')
                    assert not router.file_entry('sdwan-backup.json')
                    report['checks'].append({'node':node,'source':label,'case':name,'pass':True})
                    print('PASS '+node+' '+label+' '+name,flush=True)
                    router.call(menu+'/'+id,method='DELETE');fixture.created.remove((router,menu,id))
        report['pass']=True
    finally:
        for router in fixture.routers.values():
            for name in names:
                row=router.file_entry(name)
                if row:router.call('file/'+row['.id'],method='DELETE')
        fixture.close();report['cleanup']=fixture.report['cleanup'];report['pass']=report['pass'] and report['cleanup']['pass']
        (fixture.run/'foreign-mangle-guard-validation.json').write_text(json.dumps(report,indent=2)+'\n')
    assert report['pass']
    print(json.dumps({'pass':True,'checks':len(report['checks']),'cleanup':report['cleanup']}))


if __name__=='__main__':main()
