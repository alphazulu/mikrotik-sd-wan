#!/usr/bin/env python3
"""Run the actual native selector and derived priority guard on owned CHR/x86.

No route/firewall mutation. The old guard must reproduce the counterexamples;
the current generated guard must satisfy the same cases on RouterOS itself.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from sdwan.container_backend import controller_source
from sdwan.router import Router
from lte_rndis_acceptance import qmp

FILES=('container-priority-test.rsc','container-priority-result.json')


def blocks(source):
    start=source.index('        :local selected "none"\n')
    native=source[start:source.index('        # Retain only previously selected/retained marks,',start)]
    start=source.index('        # Revalidate cached intent against CURRENT native SLA,')
    guard=source[start:source.index('        :local decision [:toarray ""]\n',start)]
    return native,guard


def cases():
    rows=[]
    def add(name,states,wanted,expected,accepted,*,allow=False,admit=(True,True),order=('wan1','wan2'),active=True):
        rows.append({'name':name,'policy':{'name':'p','profile':'default','wans':list(order),'mode':'strict' if len(order)==1 else 'prefer','allow_degraded':allow},
            'states':{'default/'+wan:value for wan,value in zip(('wan1','wan2'),states)},
            'maintenance':{wan:{'admit':value} for wan,value in zip(('wan1','wan2'),admit)},
            'active':active,'wanted':wanted,'expected':{'selected':expected,'accepted':accepted}})
    add('healthy-backup-cannot-delay-failback',('healthy','healthy'),'wan2','wan1',False)
    add('cached-none-cannot-blackhole-healthy',('healthy','healthy'),'none','wan1',False)
    add('current-primary-intent-accepted',('healthy','healthy'),'wan1','wan1',True)
    add('failed-primary-intent-rejected',('down','healthy'),'wan1','wan2',False)
    add('current-backup-intent-accepted',('down','healthy'),'wan2','wan2',True)
    add('healthy-backup-beats-degraded-primary',('degraded','healthy'),'wan1','wan2',False,allow=True)
    add('healthy-backup-intent-accepted-over-degraded',('degraded','healthy'),'wan2','wan2',True,allow=True)
    add('permitted-degraded-primary-accepted',('degraded','down'),'wan1','wan1',True,allow=True)
    add('cached-none-cannot-hide-permitted-degraded',('degraded','down'),'none','wan1',False,allow=True)
    add('degraded-forbidden',('degraded','down'),'wan1','none',False)
    add('all-down-none-accepted',('down','down'),'none','none',True)
    add('drain-primary-not-admitted',('healthy','healthy'),'wan1','wan2',False,admit=(False,True))
    add('drain-backup-admitted',('healthy','healthy'),'wan2','wan2',True,admit=(False,True))
    add('emergency-down-closes-admission',('healthy','healthy'),'wan1','none',False,admit=(False,False))
    add('emergency-none-accepted',('healthy','healthy'),'none','none',True,admit=(False,False))
    add('strict-unavailable-closes',('down','healthy'),'none','none',True,order=('wan1',))
    add('strict-available-rejects-none',('healthy','healthy'),'none','wan1',False,order=('wan1',))
    add('explicit-reversed-priority',('healthy','healthy'),'wan1','wan2',False,order=('wan2','wan1'))
    add('inactive-container-keeps-native',('healthy','healthy'),'wan2','wan1',False,active=False)
    add('degraded-order-respected',('degraded','degraded'),'wan2','wan1',False,allow=True)
    return rows


def payload(source,values):
    native,guard=blocks(source)
    return ''':local choose do={
    :local pn ($policy->"name")
    :local sdwanState $states
    :local plan [:toarray ""]; :set ($plan->$pn) $wanted
    :local containerBridge {"active"=$active;"selected"=$plan}
'''+native+guard+'''
    :return {"selected"=$selected;"accepted"=$containerDecision}
}
:local cases [:deserialize from=json options=json.no-string-conversion value='''+json.dumps(json.dumps(values))+''']
:local results [:toarray ""]
:foreach item in=$cases do={
    :local result [$choose policy=($item->"policy") states=($item->"states") maintenance=($item->"maintenance") active=($item->"active") wanted=($item->"wanted")]
    :set ($results->[:len $results]) {"name"=($item->"name");"result"=$result}
}
/file/set [/file/find where name="container-priority-result.json"] contents=[:serialize to=json options=json.no-string-conversion value=$results]
'''


def fingerprint(router):
    return {menu:router.call(menu+'/print',{'.proplist':fields},'POST') for menu,fields in
        [('ip/route','.id,dst-address,gateway,routing-table,disabled,comment'),('routing/rule','.id,src-address,dst-address,table,action,disabled,comment'),
         ('ip/firewall/mangle','.id,chain,action,disabled,comment'),('system/scheduler','.id,name,disabled,on-event')]}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--lab-root',required=True,type=Path);args=parser.parse_args()
    lab=args.lab_root.resolve()/'runtime/x86-lte-lab';run=lab/'runtime';lock=(run/'lab.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    old_bytes=subprocess.check_output(['git','show','1b2a9d6:sdwan/container_backend.py'],cwd=ROOT)
    spec=importlib.util.spec_from_loader('priority_baseline_adapter',loader=None);old=importlib.util.module_from_spec(spec);exec(compile(old_bytes,'baseline_adapter.py','exec'),old.__dict__)
    sources={'before':old.controller_source(ROOT),'after':controller_source(ROOT)}
    report={'pass':False,'production_modified':False,'route_writes':False,'sources':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()},'nodes':{}}
    try:
        for node,port,qport,name,identity in [('chr',24424,24420,'sdwan-lte-chr','sdwan-lte-chr'),('x86',24404,24400,'sdwan-x86-lte','MikroTik')]:
            qmp(qport,name);file='credentials.json' if node=='x86' else 'chr-credentials.json'
            r=Router(lab,'api://127.0.0.1:'+str(port),credentials_data=json.loads((run/file).read_text()));created=[]
            try:
                assert r.call('system/identity')['name']==identity
                assert r.call('system/resource')['version'].split()[0]=='7.24.5'
                assert not r.call('system/scheduler?name=sdwan-controller'),'Use idle isolated nodes only'
                assert not any(r.file_entry(name) for name in FILES),'Existing component fixture must be reviewed first'
                before=fingerprint(r);node_result={};report['nodes'][node]=node_result
                for name in FILES:r.upload(name,'{}');created.append(name)
                for label,source in sources.items():
                    r.upload(FILES[0],payload(source,cases()));r.upload(FILES[1],'{}');r.call('import',{'file-name':FILES[0]},'POST')
                    results=json.loads(r.read_file(FILES[1]));assert len(results)==len(cases())
                    mismatches=[row['name'] for row,case in zip(results,cases()) if row['name']!=case['name'] or row['result']!=case['expected']]
                    node_result[label]={'cases':len(results),'mismatches':mismatches,'results':results}
                    if label=='before':assert {'healthy-backup-cannot-delay-failback','cached-none-cannot-blackhole-healthy'}<=set(mismatches),'Old guard did not reproduce regression'
                    else:assert not mismatches,mismatches
                    assert fingerprint(r)==before,'Component changed routing/firewall/scheduler state'
                    print(node+' '+label+': '+str(len(mismatches))+' mismatches / '+str(len(results))+' cases',flush=True)
                node_result['pass']=True
            finally:
                for name in created:
                    row=r.file_entry(name)
                    if row:r.call('file/'+row['.id'],method='DELETE')
                assert not any(r.file_entry(name) for name in created)
                r.close()
        report['pass']=True
    finally:
        (run/'container-priority-validation.json').write_text(json.dumps(report,indent=2)+'\n');lock.close()
    print('RouterOS priority regression component PASS; old counterexamples reproduced; temporary files removed',flush=True)


if __name__=='__main__':main()
