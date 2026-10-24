#!/usr/bin/env python3
"""Actual RouterOS container shadow with separate configuration/secret mounts."""
from pathlib import Path
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tools'))
import container_lab
from sdwan.router import Router

def main():
    lab=container_lab.load()
    credentials=json.loads((lab.RUN/'credentials.json').read_text())['edge']
    router=Router(ROOT,'api://127.0.0.1:38728',credentials_data=credentials)
    try:
        identity=router.call('system/identity')
        if isinstance(identity,list):identity=identity[0]
        assert identity['name']=='sdwan-container-edge'
        cfg=json.loads(router.read_file('sdwan-active.json'))
        assert '172.31.255.0/30' in cfg['local_networks'], 'Container management subnet must bypass WAN policy routing'
        assert json.loads((ROOT/'runtime/container-image-validation.json').read_text())['pass']
        rows=lab.api('edge','container');assert len(rows)==1
        container=rows[0];assert container['name']=='sdwan-container-controller'
        assert container.get('stopped')=='true'
        # Lab-only admin credentials are in a separate mount, never image/env.
        for directory in ('sdwan-container-config','sdwan-container-secrets'):
            if not any(row['name']==directory for row in router.call('file')):
                router.call('file',{'name':directory,'type':'directory'},'PUT')
        settings={'endpoint':'172.31.255.1:8728','identity':'sdwan-container-edge',
                  'username':credentials['username'],'password_file':'/secrets/api-password',
                  'mode':'shadow','poll_ms':1000,'metrics_every_seconds':2}
        router.upload('sdwan-container-config/controller.json',json.dumps(settings))
        router.upload('sdwan-container-secrets/api-password',credentials['password'])
        for src,dst in (('sdwan-container-config','/config'),('sdwan-container-secrets','/secrets')):
            mounts=lab.api('edge','container/mounts')
            if not any(row.get('list')=='sdwan-controller' and row.get('dst')==dst for row in mounts):
                lab.api('edge','container/mounts',{'list':'sdwan-controller','src':src,'dst':dst},'PUT')
        filters=lab.api('edge','ip/firewall/filter')
        first=filters[0]['.id']
        for comment,data in [
            ('sdwan-container:api',{'chain':'input','in-interface':'sdwan-container-mgmt',
                'src-address':'172.31.255.2','dst-address':'172.31.255.1','protocol':'tcp','dst-port':'8728','action':'accept'}),
            ('sdwan-container:no-forward',{'chain':'forward','in-interface':'sdwan-container-mgmt','action':'drop'})]:
            if not any(row.get('comment')==comment for row in filters):
                lab.api('edge','ip/firewall/filter',dict(data,comment=comment,**{'place-before':first}),'PUT')
        lab.api('edge','container/'+container['.id'],{'cmd':'run /config/controller.json','mountlists':'sdwan-controller','memory-max':'16777216','shm-size':'0'},'PATCH')
        before=router.status()
        lab.api('edge','container/start',{'numbers':container['.id']},'POST')
        readings=[]
        for _ in range(10):
            time.sleep(2)
            row=lab.api('edge','container')[0]
            assert row.get('running')=='true', 'Container failed; inspect isolated CHR logs without printing secrets'
            readings.append({k:row[k] for k in ('memory-current','cpu-usage') if k in row})
        logs=lab.api('edge','log')
        messages=[r.get('message','') for r in logs if 'sdwan-container-controller:' in r.get('message','')]
        plans=[];resources=[]
        for message in messages:
            start=message.find('{')
            if start<0:continue
            try:row=json.loads(message[start:])
            except json.JSONDecodeError:continue
            if row.get('mode')=='shadow' and 'selected' in row:plans.append(row)
            if 'resources' in row:resources.append(row['resources'])
        assert plans and plans[-1]['selected']==before['selected']
        assert resources and all(row['rss_bytes']>0 for row in resources)
        assert all(row['writes']==0 for row in plans)
        assert not any('unavailable:' in message for message in messages)
        result={'pass':True,'execution':'inside RouterOS7.24.5 CHR container','base':'scratch',
                'image_user':container['default-user'],'separate_config_and_secret_mounts':True,
                'plans_match_native':True,'writes':0,'process_rss_min_bytes':min(r['rss_bytes'] for r in resources),
                'process_rss_max_bytes':max(r['rss_bytes'] for r in resources),
                'routeros_container_samples':readings,'native_controller_remains_active':True,
                'active_container_backend_complete':False,'production_modified':False}
        (ROOT/'runtime/container-runtime-shadow-validation.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    finally:
        # Stop the read-only experiment, retain separate mounted lab fixtures.
        for row in lab.api('edge','container'):
            if row.get('name')=='sdwan-container-controller' and row.get('running')=='true':
                lab.api('edge','container/stop',{'numbers':row['.id']},'POST')
        router.close()

if __name__=='__main__':main()
