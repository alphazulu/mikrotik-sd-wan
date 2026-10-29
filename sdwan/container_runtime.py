"""Prepare a local RouterOS container; no routing policy decisions run here."""
import ipaddress
import json
import secrets
import time
from .container_config import BRIDGE,VETH,NAME,USER,HEARTBEAT_PORT,addresses,settings,validate_backend
from . import container_telemetry as web

PREFIX='sdwan-container:'
POLICIES={'read','write','policy','test','sensitive','api'}
ALL_POLICIES={'local','telnet','ssh','ftp','reboot','read','write','policy','test','winbox','password','web','sniff','sensitive','api','romon','rest-api'}

def one(value):return value[0] if isinstance(value,list) else value

def api_service_access(api,guest):
    # RouterOS builds expose the service prefix list under either name. An
    # omitted legacy field must not hide a present, restrictive canonical one.
    field='available-from' if 'available-from' in api else 'address'
    value=api.get(field,'')
    if not isinstance(value,str):raise ValueError('Native API service access list is unreadable')
    prefixes=[s.strip() for s in value.split(',') if s.strip()]
    permitted=not prefixes or any(ipaddress.IPv4Address(guest) in ipaddress.ip_network(n) for n in prefixes)
    disabled=api.get('disabled')=='true';update={}
    if disabled:update['disabled']='no'
    if prefixes and not permitted:update[field]=','.join(prefixes+[guest+'/32'])
    elif disabled and not prefixes:update[field]=guest+'/32'
    return permitted and not disabled,update

def paths(config):
    storage=settings(config)['storage']
    return {'storage':storage,'root':storage+'/root','config':storage+'/config',
            'secrets':storage+'/secrets','settings':storage+'/config/controller.json',
            'password':storage+'/secrets/api-password','web_token':storage+'/secrets/web-token'}

def read_container(router):
    rows=router.call('container/print',{'.proplist':'.id,name,interface,stopped,running,default-user,default-entrypoint,user,entrypoint,privileged,cmd,root-dir,mountlists,comment,arch,image-id,file,memory-max,swap-max,logging,dns,start-on-boot'},'POST')
    return next((row for row in rows if row.get('name')==NAME),None)

def prerequisites(router,config,expected):
    validate_backend(config)
    web.validate_interfaces(router,config)
    if one(router.call('system/identity'))['name']!=expected:raise ValueError('Router identity differs from expected identity')
    resource=one(router.call('system/resource'))
    if resource['version'].split()[0]!='7.24.5':raise ValueError('Container backend is validated on RouterOS 7.24.5')
    if resource.get('architecture-name') not in ('x86','x86_64','arm','arm64'):raise ValueError('Router architecture does not support this container backend')
    packages=router.call('system/package')
    if not any(row.get('name')=='container' and row.get('version')=='7.24.5' and row.get('disabled')!='true' for row in packages):raise ValueError('Install the matching RouterOS 7.24.5 container package first')
    if one(router.call('system/device-mode')).get('container') not in ('true',True):raise ValueError('Enable device-mode container=yes and confirm physically before preparation')
    network,host,guest=addresses(config)
    for row in router.call('ip/address'):
        if row.get('interface')==BRIDGE and row.get('address')==host+'/30':continue
        if row.get('disabled')=='true':continue
        if ipaddress.IPv4Interface(row['address']).network.overlaps(network):raise ValueError('Container subnet overlaps an existing interface network: '+row['interface'])
    for row in router.call('ip/route'):
        if row.get('disabled')=='true' or row.get('routing-table','main')!='main' or row.get('dst-address') in (None,'0.0.0.0/0'):continue
        existing=ipaddress.IPv4Network(row['dst-address'])
        if existing==network and row.get('gateway')==BRIDGE:continue
        if existing.overlaps(network):raise ValueError('Container subnet overlaps an existing routed network: '+str(existing))
    return resource,network,host,guest

def check_ready(router,config,expected):
    _,network,host,guest=prerequisites(router,config,expected)
    row=read_container(router)
    if not row or row.get('comment')!=PREFIX+'controller':raise ValueError('Prepare the local SD-WAN container before applying this backend')
    if row.get('interface')!=VETH or row.get('default-user')!='65532:65532' or row.get('default-entrypoint') not in ('/sdwan-controller','/sdwan-controller-web'):raise ValueError('Prepared container image/interface differs from expected SD-WAN runtime')
    if row.get('privileged')=='true' or row.get('user','') not in ('','65532:65532') or row.get('entrypoint','') not in ('',row.get('default-entrypoint')):raise ValueError('SD-WAN container must retain its unprivileged image user and entrypoint')
    runtime=paths(config)
    if row.get('root-dir','').strip('/')!=runtime['root']:raise ValueError('Container storage changed; prepare it before applying')
    actual=json.loads(router.read_file(runtime['settings']))
    web.check_ready(router,config,actual,row.get('default-entrypoint'),runtime['web_token'])
    # RouterOS 7.24.5 interprets zero as unlimited. Keep the smallest positive
    # per-container limit as a defence; web prerequisites also require no swap
    # devices, since kernel page rounding is platform dependent.
    if web.process_settings(config) and (row.get('swap-max')!='1' or row.get('logging')!='false'):raise ValueError('Web statistics require swap-max=1 and logging=no to avoid persistent writes')
    if actual.get('identity')!=expected or actual.get('username')!=USER or actual.get('endpoint','').split(':')[0]!=host or actual.get('mode')!='active' or actual.get('poll_ms')!=settings(config)['poll_ms']:raise ValueError('Prepared controller settings differ from selected backend')
    if row.get('file')!=settings(config)['image_file'] or int(row.get('memory-max',0))!=settings(config)['memory_max_bytes']:raise ValueError('Prepared container archive/memory limit differs; prepare it before applying')
    if row.get('dns')!=host:raise ValueError('Prepared container requires an explicit local DNS setting even though its API uses numeric IP')
    api=next(x for x in router.call('ip/service') if x.get('name')=='api' and x.get('dynamic')!='true')
    permitted,_=api_service_access(api,guest)
    if not permitted or actual.get('endpoint')!=host+':'+str(api['port']):raise ValueError('Prepared local native API endpoint/ACL changed')
    if not any(x['name']==router.storage_prefix+'sdwan-container-intent.json' for x in router.call('file/print',{'.proplist':'name'},'POST')):raise ValueError('Prepared intent file is missing')
    mounts=[x for x in router.call('container/mounts') if x.get('list')=='sdwan-controller']
    expected_mounts={(runtime['config'],'/config'),(runtime['secrets'],'/secrets')}
    if set(row.get('mountlists','').split(','))!={'sdwan-controller'} or len(mounts)!=2 or {(x['src'].strip('/'),x['dst']) for x in mounts}!=expected_mounts or any(x.get('mode')!='ro' for x in mounts):raise ValueError('Prepared container mounts differ from the dedicated read-only config/secret paths')
    users=router.call('user/print',{'.proplist':'name,group,address,disabled,comment','.query':['name='+USER]},'POST')
    if len(users)!=1 or users[0].get('comment')!=PREFIX+'api-user' or users[0].get('address')!=guest+'/32' or users[0].get('disabled')=='true':raise ValueError('Dedicated container API user changed')
    groups=router.call('user/group/print',{'.proplist':'name,policy','.query':['name='+users[0]['group']]},'POST')
    if len(groups)!=1 or {p for p in groups[0]['policy'].split(',') if not p.startswith('!')}!=POLICIES:raise ValueError('Dedicated container API group permissions changed')
    veth=router.call('interface/veth/print',{'.proplist':'name,address,gateway'},'POST')
    if not any(x['name']==VETH and x['address']==guest+'/30' and x['gateway']==host for x in veth):raise ValueError('Container veth addressing changed')
    if not any(x.get('comment')==PREFIX+'heartbeat' and x.get('src-address')==guest and x.get('address-list')=='sdwan-container-live' and x.get('disabled')!='true' for x in router.call('ip/firewall/mangle')):raise ValueError('Container RAM heartbeat rule is missing or changed')
    return {'action':'use local Rust container with RouterOS SLA validation and warm native fallback',
            'container':NAME,'network':str(network),'storage':runtime['storage']}

def prepare(router,config,expected,*,timeout=120):
    """Import an uploaded image and create stopped runtime; does not install SD-WAN."""
    if config.get('controller_backend')!='container':raise ValueError('Select controller_backend=container before preparation')
    resource,network,host,guest=prerequisites(router,config,expected)
    cfg=settings(config);runtime=paths(config)
    current=read_container(router)
    if current and (current.get('comment')!=PREFIX+'controller' or current.get('root-dir','').strip('/')!=runtime['root']):raise ValueError('Existing container name/storage is not managed by this configuration')
    if current and current.get('stopped')!='true':raise ValueError('Stop the SD-WAN container before preparing its files')
    if current and current.get('file')!=cfg['image_file']:raise ValueError('To change the image archive, reimport the stopped SD-WAN container first; settings preparation does not replace its filesystem')
    if current and web.process_settings(config) and current.get('default-entrypoint')!='/sdwan-controller-web':raise ValueError('Telemetry requires reimporting the optional web scratch image first')
    files=router.call('file/print',{'.proplist':'.id,name,type,size'},'POST')
    image=next((f for f in files if f['name']==cfg['image_file']),None)
    if not current and (not image or not 0<int(image.get('size',0))<=8388608):raise ValueError('Upload the matching scratch image archive (up to 8 MiB) to container.image_file first')
    for menu,name in (('interface/bridge',BRIDGE),('interface/veth',VETH),('user',USER)):
        for row in router.call(menu):
            if row.get('name')==name and not row.get('comment','').startswith(PREFIX):raise ValueError('Unmanaged object has a reserved SD-WAN container name: '+name)
    for other in router.call('container/print',{'.proplist':'name,mountlists'},'POST'):
        if other.get('name')!=NAME and 'sdwan-controller' in other.get('mountlists','').split(','):raise ValueError('Container mount list is already used by another container')
    for mount in router.call('container/mounts'):
        if mount.get('list')=='sdwan-controller' and mount.get('src','').strip('/') not in (runtime['config'],runtime['secrets']):raise ValueError('Reserved container mount list has unrelated directories')
    groups=router.call('user/group')
    group=next((g for g in groups if g['name']==USER),None)
    if group and {p for p in group['policy'].split(',') if not p.startswith('!')}!=POLICIES:raise ValueError('Existing container user group has unexpected permissions')

    def ensure(menu,key,value,fields,where=None):
        found=[r for r in router.call(menu) if r.get(key)==value and (where is None or where(r))]
        if len(found)>1:raise ValueError('Ambiguous managed container object: '+menu+'/'+value)
        if found:
            target=found[0]
            changed={k:v for k,v in fields.items() if str(target.get(k,''))!=str(v)}
            if changed:router.call(menu+'/'+target['.id'],changed,'PATCH')
            return target['.id']
        return router.call(menu,dict(fields,**{key:value}),'PUT')['.id']

    ensure('interface/bridge','name',BRIDGE,{'comment':PREFIX+'bridge'})
    ensure('interface/veth','name',VETH,{'address':guest+'/30','gateway':host,'comment':PREFIX+'veth'})
    ensure('interface/bridge/port','interface',VETH,{'bridge':BRIDGE,'comment':PREFIX+'port'})
    ensure('ip/address','comment',PREFIX+'address',{'interface':BRIDGE,'address':host+'/30'})
    if not group:router.call('user/group',{'name':USER,'policy':','.join(p if p in POLICIES else '!'+p for p in sorted(ALL_POLICIES))},'PUT')
    for directory in (runtime['storage'],runtime['config'],runtime['secrets']):
        if not any(f['name']==directory for f in router.call('file/print',{'.proplist':'name'},'POST')):
            router.call('file',{'name':directory,'type':'directory'},'PUT')
    user=next((u for u in router.call('user') if u['name']==USER),None)
    try:password=router.read_file(runtime['password']) if user else secrets.token_urlsafe(40)
    except ValueError:password=secrets.token_urlsafe(40)
    if not password:password=secrets.token_urlsafe(40)
    ensure('user','name',USER,{'group':USER,'address':guest+'/32','disabled':'no','password':password,'comment':PREFIX+'api-user'})
    router.upload(runtime['password'],password)
    api=next(row for row in router.call('ip/service') if row.get('name')=='api' and row.get('dynamic')!='true')
    _,update=api_service_access(api,guest)
    if update:router.call('ip/service/'+api['.id'],update,'PATCH')
    process={'endpoint':host+':'+str(api.get('port','8728')),'identity':expected,'username':USER,
             'password_file':'/secrets/api-password','mode':'active','poll_ms':cfg['poll_ms'],
             'heartbeat_port':HEARTBEAT_PORT,'metrics_every_seconds':0}
    telemetry=web.process_settings(config)
    if telemetry:
        try:token=router.read_file(runtime['web_token'])
        except ValueError:token=''
        if not web.valid_token(token) or token==password:token=secrets.token_hex(32)
        router.upload(runtime['web_token'],token)
        process['telemetry']=telemetry
    router.upload(runtime['settings'],json.dumps(process,separators=(',',':')))
    for src,dst in ((runtime['config'],'/config'),(runtime['secrets'],'/secrets')):
        ensure('container/mounts','dst',dst,{'list':'sdwan-controller','src':src,'mode':'ro'},where=lambda row:row.get('list')=='sdwan-controller')
    # Insert managed input/forward rules before existing rules, without moving
    # any existing rule. Exact veth/source constraints do not open WAN services.
    web.provision_sources(router,config)
    rule_specs=[('ip/firewall/filter',tag,fields) for tag,fields in web.rule_specs(config)]+[('ip/firewall/nat',tag,fields) for tag,fields in web.nat_rule_specs(config)]+[
        ('ip/firewall/mangle','heartbeat',dict(chain='prerouting',action='add-src-to-address-list',passthrough='yes',**{'in-interface':BRIDGE,'src-address':guest,'dst-address':host,'protocol':'udp','dst-port':str(HEARTBEAT_PORT),'address-list':'sdwan-container-live','address-list-timeout':'6s'})),
        ('ip/firewall/filter','api',dict(chain='input',action='accept',**{'in-interface':BRIDGE,'src-address':guest,'dst-address':host,'protocol':'tcp','dst-port':str(api.get('port','8728'))})),
        ('ip/firewall/filter','heartbeat-drop',dict(chain='input',action='drop',**{'in-interface':BRIDGE,'src-address':guest,'dst-address':host,'protocol':'udp','dst-port':str(HEARTBEAT_PORT)})),
        ('ip/firewall/filter','other-input-drop',dict(chain='input',action='drop',**{'in-interface':BRIDGE})),
        ('ip/firewall/filter','no-forward',dict(chain='forward',action='drop',**{'in-interface':BRIDGE})),
        ('ip/firewall/filter','no-forward-to-container',dict(chain='forward',action='drop',**{'out-interface':BRIDGE})),
    ]
    for menu in ('ip/firewall/mangle','ip/firewall/filter','ip/firewall/nat'):
        owned={PREFIX+tag for kind,tag,_ in rule_specs if kind==menu}
        for row in router.call(menu):
            if row.get('comment') in owned or (menu in ('ip/firewall/filter','ip/firewall/nat') and row.get('comment','').startswith(web.PREFIX)):router.call(menu+'/'+row['.id'],method='DELETE')
        remaining=router.call(menu);before=remaining[0]['.id'] if remaining else None
        for kind,tag,fields in rule_specs:
            if kind!=menu:continue
            rule=dict(fields,comment=PREFIX+tag)
            if before:rule['place-before']=before
            router.call(menu,rule,'PUT')
    if not any(f['name']==router.storage_prefix+'sdwan-container-intent.json' for f in router.call('file/print',{'.proplist':'name'},'POST')):router.upload('sdwan-container-intent.json','')
    if not current:
        router.call('container',{'file':cfg['image_file'],'interface':VETH,'root-dir':runtime['root'],
                    'name':NAME,'comment':PREFIX+'controller','cmd':'run /config/controller.json',
                    'mountlists':'sdwan-controller','memory-max':str(cfg['memory_max_bytes']),
                    'shm-size':'0','swap-max':'1','logging':'no','start-on-boot':'no','privileged':'no','dns':host},'PUT')
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        current=read_container(router)
        if current and current.get('stopped')=='true':break
        time.sleep(.5)
    else:raise RuntimeError('Container extraction timed out; inspect RouterOS container log')
    expected_arch='amd64' if resource['architecture-name'] in ('x86','x86_64') else resource['architecture-name']
    if current.get('arch')!=expected_arch:raise ValueError('Uploaded image architecture differs from this router')
    router.call('container/'+current['.id'],{'cmd':'run /config/controller.json','memory-max':str(cfg['memory_max_bytes']),'shm-size':'0','swap-max':'1','logging':'no','mountlists':'sdwan-controller','start-on-boot':'no','dns':host},'PATCH')
    check_ready(router,config,expected)
    return {'prepared':True,'container':NAME,'started':False,'sdwan_policies_modified':False,
            'dedicated_api_user':USER,'api_policies':sorted(POLICIES),'storage':runtime['storage']}

def deactivate(router):
    if not any(row.get('name')=='container' for row in router.call('system/package')):return
    row=read_container(router)
    if row and row.get('comment')==PREFIX+'controller':
        router.call('container/'+row['.id'],{'start-on-boot':'no'},'PATCH')
        if row.get('running')=='true':router.call('container/stop',{'numbers':row['.id']},'POST')
