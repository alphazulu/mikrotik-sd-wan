"""Bounded host-side preparation of a router-local device-mode request.

The temporary launcher is configuration; worker state lives only in RouterOS RAM.
It deliberately never changes the whole device mode or confirms physical access.
"""
import re
import secrets
import time
from .platform_support import records

FEATURES=frozenset(('scheduler','fetch','container','l2tp','ipsec'))
MARKER=re.compile(r'sdwanDeviceMode[0-9a-f]{16}')
POLICY='read,write,policy,test,sensitive,reboot'


def request(router,features,save):
    if not features or set(features)-FEATURES or any(v!='yes' for v in features.values()):
        raise ValueError('Only required per-feature device-mode permissions may be requested')
    token=secrets.token_hex(8);name='sdwan-device-mode-'+token;marker='sdwanDeviceMode'+token
    intent={'worker':name,'marker':marker,'created':time.time(),'expires':time.time()+600,'request_status':'sending','features':list(features)}
    # Persist before any router mutation: ambiguous transport failure must not
    # cause a second update, which could cancel the original request.
    save(intent)
    command='/system/device-mode/update '+' '.join(key+'=yes' for key in sorted(features))+' activation-timeout=5m as-value'
    source=(':global '+marker+'; :set '+marker+' "running"; '
            ':do { :local result ['+command+']; :set '+marker+' [:serialize to=json value=$result] } '
            'on-error={ :set '+marker+' "failed" }')
    launcher=name+'-launch'
    try:
        router.call('system/script',{'name':name,'comment':name,'policy':POLICY,'source':source},'PUT')
        item=router.call('system/script',{'name':launcher,'comment':launcher,'policy':POLICY,'source':':execute script="/system/script/run '+name+'"'},'PUT')
        router.call('system/script/run',{'number':item['.id']},'POST')
        intent['request_status']='launched';intent['expires']=time.time()+330;save(intent)
    finally:
        # Keep the named worker until its job has ended: RouterOS can leave a
        # stale RAM marker after cancellation. The name identifies the real job.
        try:_remove_script(router,launcher)
        except (OSError,RuntimeError):pass

    return intent


def observe(router,intent):
    marker=intent.get('marker','')
    if not MARKER.fullmatch(marker):return 'unknown'
    rows=records(router.call('system/script/environment/print',{'.query':['name='+marker],'.proplist':'name,value'},'POST'))
    matching=[r for r in rows if r.get('name')==marker]
    if len(matching)!=1:return 'unknown'
    value=matching[0].get('value','')
    if value=='running':
        name=intent.get('worker','')
        if not re.fullmatch(r'sdwan-device-mode-[0-9a-f]{16}',name):return 'unknown'
        active=records(router.call('system/script/job/print',{'.query':['script='+name],'.proplist':'.id,owner,script'},'POST'))
        return 'running' if any(row.get('script')==name and row.get('owner')==router.username for row in active) else 'ended'
    if value=='failed' or 'canceled' in value.lower():return 'ended'
    return 'ended' if value else 'unknown'


def _remove_script(router,name):
    rows=records(router.call('system/script/print',{'.query':['name='+name,'comment='+name],'.proplist':'.id,name,comment'},'POST'))
    if len(rows)==1 and rows[0].get('name')==name and rows[0].get('comment')==name:
        router.call('system/script/remove',{'numbers':rows[0]['.id']},'POST')


def cleanup(router,intent):
    name=intent.get('worker','')
    if not re.fullmatch(r'sdwan-device-mode-[0-9a-f]{16}',name):return
    active=records(router.call('system/script/job/print',{'.query':['script='+name],'.proplist':'.id'},'POST'))
    if not active:
        _remove_script(router,name+'-launch');_remove_script(router,name)
