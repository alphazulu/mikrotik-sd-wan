#!/usr/bin/env python3
"""Live preparation guards and repeatability on the separate container CHR."""
import copy
import json
from container_support import Lab,ROOT
from sdwan.container_runtime import prepare,check_ready,paths,ALL_POLICIES,POLICIES

def main():
    env=Lab();r=env.router;cfg=json.loads((ROOT/'runtime/container-lab/sdk-config.json').read_text());report={'checks':[]}
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def rejected(config,pattern):
        try:prepare(r,config,'sdwan-container-edge')
        except ValueError as error:assert pattern in str(error),(pattern,str(error))
        else:raise AssertionError('Unsafe preparation accepted')
    try:
        env.stop();before=r.read_file('sdwan-active.json')
        a=prepare(r,cfg,'sdwan-container-edge');password=r.read_file(paths(cfg)['password'])
        b=prepare(r,cfg,'sdwan-container-edge');assert a==b and r.read_file(paths(cfg)['password'])==password
        assert r.read_file('sdwan-active.json')==before
        record('repeated preparation reuses image/credential and never changes active SD-WAN configuration')
        check_ready(r,cfg,'sdwan-container-edge');record('prepared veth, mounts, unprivileged image, API source restriction and exact group permissions match public JSON')
        row=env.container();r.call('container/'+row['.id'],{'comment':'foreign-fixture'},'PATCH')
        try:rejected(cfg,'not managed')
        finally:r.call('container/'+row['.id'],{'comment':'sdwan-container:controller'},'PATCH')
        record('unmanaged reserved container name is rejected before preparation')
        changed=copy.deepcopy(cfg);changed['container']['subnet']='192.168.50.0/30'
        rejected(changed,'overlaps');record('container network overlapping a real LAN is rejected')
        route=env.add('edge','ip/route',{'dst-address':'172.31.254.0/23','blackhole':'yes','routing-table':'main'})
        try:rejected(cfg,'routed network')
        finally:env.lab.api('edge','ip/route/'+route,method='DELETE')
        record('container network inside an existing routed aggregate is rejected, protecting remote branch routes')
        group=next(x for x in r.call('user/group') if x['name']=='sdwan-container')
        extra=POLICIES|{'reboot'}
        r.call('user/group/'+group['.id'],{'policy':','.join(p if p in extra else '!'+p for p in sorted(ALL_POLICIES))},'PATCH')
        try:rejected(cfg,'unexpected permissions')
        finally:r.call('user/group/'+group['.id'],{'policy':','.join(p if p in POLICIES else '!'+p for p in sorted(ALL_POLICIES))},'PATCH')
        record('unexpected elevated API group rights are rejected rather than silently adopted')
        mount=r.call('container/mounts',{'list':'sdwan-controller','src':'sdwan-unowned-fixture','dst':'/foreign'},'PUT')['.id']
        try:rejected(cfg,'unrelated directories')
        finally:r.call('container/mounts/'+mount,method='DELETE')
        record('unrelated directories in the reserved mount list are rejected')
        changed=copy.deepcopy(cfg);changed['container'].update(poll_ms=2000,memory_max_bytes=8388608)
        try:check_ready(r,changed,'sdwan-container-edge')
        except ValueError:pass
        else:raise AssertionError('Changed process settings accepted without preparation')
        prepare(r,changed,'sdwan-container-edge');check_ready(r,changed,'sdwan-container-edge')
        prepare(r,cfg,'sdwan-container-edge');record('poll/memory changes require preparation and preserve separate mounted credentials')
        (ROOT/'runtime/container-sdk-prepare-validation.json').write_text(json.dumps(prepare(r,cfg,'sdwan-container-edge'),indent=2)+'\n')
        report['pass']=True
    finally:
        env.close();(ROOT/'runtime/container-provision-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
