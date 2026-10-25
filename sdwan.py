#!/usr/bin/env python3
"""Developer/configuration utility. All runtime SD-WAN logic runs on RouterOS."""
import argparse
from datetime import datetime,timezone
import difflib
import json
from pathlib import Path
import sys
import time
import tempfile

from sdwan.config import load, objects
from sdwan.router import Router
from sdwan.wan import adopted_dynamic_route
from sdwan.lte import apn_binding

ROOT=Path(__file__).resolve().parent
FILES=('sdwan-controller.rsc','sdwan-install.rsc','sdwan-rollback.rsc','sdwan-dataplane.rsc','sdwan-links.rsc','sdwan-overlay.rsc','sdwan-vpn.rsc','sdwan-dns.rsc','sdwan-deployment.rsc','sdwan-deploy-worker.rsc','sdwan-deploy-watchdog.rsc')
PREFIX='sdwan:v1:'


def bundle(c,output):
    from sdwan.vpn_egress import canonical
    c=canonical(c)
    output=Path(output)
    payload={'sdwan-config.json':json.dumps(c,separators=(',',':'),ensure_ascii=False)+'\n'}
    for name in FILES:
        source=(ROOT/'native'/name).read_text()
        if name=='sdwan-controller.rsc' and c.get('controller_backend')=='container':
            from sdwan.container_backend import controller_source
            source=controller_source(ROOT,c)
        if name=='sdwan-install.rsc' and c.get('controller_backend')=='container':
            from sdwan.container_backend import installer_source
            source=installer_source(ROOT,c)
        if name=='sdwan-deploy-watchdog.rsc' and c.get('controller_backend')=='container':
            from sdwan.container_backend import watchdog_source
            source=watchdog_source(ROOT)
        payload[name]=source
    # Keep headroom below the RouterOS file-contents boundary observed on CHR.
    # Reject a growing module before protected deployment archives or uploads.
    for name,text in payload.items():
        if len(text.encode('utf-8'))>60000:raise ValueError('Payload '+name+' exceeds the conservative 60000-byte text limit; split the module')
    output.mkdir(parents=True,exist_ok=True)
    for name,text in payload.items():
        (output/name).write_text(text,encoding='utf-8',newline='\n')
    return output


def inspect(router,c):
    live={}
    for menu in ('ip/route','routing/rule','tool/netwatch','ip/firewall/mangle','ip/firewall/address-list','ip/firewall/nat','ip/firewall/filter'):
        rows=router.call(menu); by_tag={}
        for row in rows:
            if menu=='ip/firewall/address-list' and row.get('dynamic')=='true':continue
            tag=row.get('comment','')
            if tag==PREFIX+'dns-bootstrap' or tag.startswith((PREFIX+'overlay:',PREFIX+'vpn:')):continue  # reconciled by the optional overlay module
            if tag.startswith(PREFIX):
                if tag in by_tag:raise ValueError(f'duplicate managed comment: {tag}')
                by_tag[tag]=row
        live[menu]=by_tag
    desired=objects(c); actions=[]
    for address in router.call('ip/address'):
        if address.get('disabled')=='true' or address.get('invalid')=='true':continue
        for wan in c['wans']:
            ip=address.get('address','').split('/')[0]
            if address.get('interface')==wan['interface'] and ip and ip!=wan.get('address') and not (wan.get('kind','static')!='static' and address.get('dynamic')=='true'):
                desired[('routing/rule',f'sdwan:v1:alias-pin:{wan["name"]}:{ip}') ]={'src-address':ip+'/32','action':'lookup-only-in-table','table':wan['probe_table']}
    for wan in c['wans']:
        if wan.get('kind','static')!='static':actions.append({'action':'resolve address/gateway and reconcile source bindings locally on RouterOS','wan':wan['name'],'interface':wan['interface'],'kind':wan['kind'],'lease_saved_in_config':False})
    for (menu,tag),values in desired.items():
        old=live[menu].get(tag)
        delta={} if old is None else {k:{'from':old.get(k),'to':v} for k,v in values.items() if old.get(k)!=v}
        actions.append({'action':'add' if old is None else ('update' if delta else 'keep'),'menu':menu,'comment':tag,'fields':values if old is None else delta})
    for menu,rows in live.items():
        for tag in rows:
            if (menu,tag) not in desired:actions.append({'action':'remove','menu':menu,'comment':tag})
    return actions


def preflight(router,c,expected):
    from sdwan.vpn_egress import canonical
    c=canonical(c)
    identity=router.call('system/identity')['name']
    if identity!=expected:raise ValueError(f'Router identity {identity!r} differs from expected {expected!r}')
    res=router.call('system/resource')
    if isinstance(res,list):res=res[0]
    if res['version'].split()[0]!='7.24.5':raise ValueError('This build is validated for RouterOS 7.24.5 only')
    routes=router.call('ip/route')
    from sdwan.vpn_egress import validate_pushed_defaults
    validate_pushed_defaults(routes,c)
    selectors={s['.id']:s for s in c.get('takeover_routes',[])}
    actual={r['.id']:r for r in routes}
    for identifier,selector in selectors.items():
        row=actual.get(identifier)
        if not row or row.get('dynamic')=='true' or any(row.get(k,'main' if k=='routing-table' else '')!=selector[k] for k in ('dst-address','gateway','routing-table')):
            raise ValueError('Discovered default route changed; reconnect and regenerate: '+identifier)
    for item in c.get('disable_fasttrack',[]):
        row=router.call('ip/firewall/filter/'+item['.id'])
        if row.get('action')!=item['action'] or row.get('chain')!=item['chain']:raise ValueError('FastTrack selector changed; reconnect and regenerate')
    for r in routes:
        if r.get('routing-table','main')=='main' and r.get('dst-address')=='0.0.0.0/0' and r.get('disabled')!='true' and not r.get('comment','').startswith(PREFIX) and r.get('comment') not in c['takeover_route_comments'] and r['.id'] not in selectors and not adopted_dynamic_route(r,c['wans']):
            raise ValueError(f'Undeclared default route would bypass SD-WAN: {r.get(".id")}')
    interfaces={i['name'] for i in router.call('interface')}
    for policy in c['policies']:
        if policy.get('in_interface') and policy['in_interface'] not in interfaces:raise ValueError('Unknown policy input interface: '+policy['in_interface'])
    addresses=router.call('ip/address')
    for w in c['wans']:
        if w['interface'] not in interfaces:raise ValueError(f'Unknown interface {w["interface"]}')
        kind=w.get('kind','static')
        if kind=='static' and not any(row.get('interface')==w['interface'] and row.get('address','').split('/')[0]==w['address'] and row.get('dynamic') not in ('true',True) and row.get('disabled') not in ('true',True) and row.get('invalid') not in ('true',True) for row in addresses):raise ValueError('Static WAN source must already be assigned statically: '+w['interface'])
        if kind=='lte':
            binding=apn_binding(w['interface'],router.call('interface/lte/print',{'.proplist':'.id,name,disabled,running,apn-profiles,apn-profile'},'POST'),router.call('interface/lte/apn/print',{'.proplist':'.id,name,add-default-route,default-route-distance,ip-type,passthrough-interface'},'POST'),expected_profile=w['apn_profile'],managed_interfaces=[x['interface'] for x in c['wans'] if x.get('kind')=='lte'])
        elif kind=='vpn':
            from sdwan.vpn_egress import binding as vpn_binding
            vpn_binding(router,w)
        elif kind!='static':
            menu='ip/dhcp-client' if kind=='dhcp' else 'interface/pppoe-client'
            field='interface' if kind=='dhcp' else 'name'
            clients=router.call(menu+'/print',{'.proplist':'.id,name,interface,disabled,add-default-route,default-route-tables'},'POST')
            if len([row for row in clients if row.get(field)==w['interface']])!=1:raise ValueError('Missing or ambiguous '+kind+' client on '+w['interface'])
    for row in router.call('ip/firewall/mangle'):
        if row.get('disabled')!='true' and row.get('action') in ('mark-routing','mark-connection','route') and not row.get('comment','').startswith(PREFIX):raise ValueError('Foreign routing/connection marks conflict with SD-WAN; reconcile them first')
    if any(row.get('action')=='notrack' and row.get('disabled')!='true' for row in router.call('ip/firewall/raw')):raise ValueError('Active RAW notrack conflicts with SD-WAN connection tracking')
    tracking=router.call('ip/firewall/connection/tracking')
    if isinstance(tracking,list):tracking=tracking[0]
    if tracking.get('enabled') in ('no','false'):raise ValueError('Connection tracking must be enabled for SD-WAN')
    declared={row['.id'] for row in c.get('disable_fasttrack',[])}
    if any(row.get('action')=='fasttrack-connection' and row.get('disabled')!='true' and row['.id'] not in declared for row in router.call('ip/firewall/filter')):raise ValueError('Active FastTrack must be declared for disabling before SD-WAN installation')
    actions=inspect(router,c)
    if c.get('controller_backend')=='container':
        from sdwan.container_runtime import check_ready
        actions.append(check_ready(router,c,expected))
    from sdwan.policies import conflicts,signature
    for conflict in conflicts(c):actions.append({'action':'ordered policy overlap',**conflict})
    try:active=json.loads(router.read_file('sdwan-active.json'))
    except ValueError as error:
        if not str(error).startswith('Router file not found:'):raise
        active=None
    from sdwan.overlay import enabled as overlay_enabled
    if overlay_enabled(c):
        actions.append({'action':'reconcile local WireGuard/OSPF overlay using prepared public identities; pin every tunnel to its WAN and probe its inner peer; blackhole remote prefixes when unavailable',
                        'tunnels':[{'name':t['name'],'wan':t['wan'],'cost':t['cost']} for t in c['overlay']['tunnels']],
                        'local_prefixes':c['overlay']['local_prefixes'],'remote_prefixes':c['overlay']['remote_prefixes']})
    elif active and overlay_enabled(active):actions.append({'action':'withdraw owned overlay peers, OSPF templates and VPN routes; retain disabled key identities'})
    if active and signature(active)!=signature(c):actions.append({'action':'reclassify managed outbound client connections after selector/group/order changes; incoming WAN API and probes preserved'})
    from sdwan.vpn_egress import vpn_wans
    from sdwan.vpn_egress import wan_flag
    for w in vpn_wans(c):actions.append({'action':'adopt existing VPN WAN transport and suppress automatic/pushed defaults; select with ordinary WAN policies and common SLA/conntrack','wan':w['name'],'vpn_type':w['vpn_type'],'underlays':w['underlays'],'masquerade':wan_flag(c,w,'masquerade'),'allow_selected_forward':wan_flag(c,w,'allow_selected_forward'),'credentials_changed':False})
    for identifier in selectors:actions.append({'action':'disable baseline route','menu':'ip/route','id':identifier})
    for item in c.get('disable_fasttrack',[]):actions.append({'action':'disable FastTrack','menu':'ip/firewall/filter','id':item['.id']})
    for w in c['wans']:
        if w.get('kind')=='lte':actions.append({'action':'save APN routing baseline; disable APN automatic default; use interface gateway in pinned tables; preserve APN credentials/DNS/distance','wan':w['name'],'interface':w['interface'],'apn_profile':w['apn_profile']})
        if w.get('kind') in ('dhcp','pppoe'):actions.append({'action':'save provider client settings for baseline rollback; isolate DHCP routes in probe table' if w['kind']=='dhcp' else 'save and disable PPPoE automatic default route','wan':w['name'],'interface':w['interface']})
    settings=router.call('ip/settings')
    if isinstance(settings,list):settings=settings[0]
    if settings.get('rp-filter')=='strict':actions.append({'action':'set rp-filter to loose for multiple WANs; save original for rollback','menu':'ip/settings'})
    actions.append({'action':'order SD-WAN mangle jumps first and local routing rules before WAN source pins; clear only affected managed conntrack marks on policy/WAN transitions'})
    actions.append({'action':'save encrypted full backup and previous files; apply in local scheduler; require fresh API confirmation within 120 seconds; native watchdog restores backup and reboots on failure or timeout'})
    if 'maintenance' in c:
        from sdwan.maintenance import backup_plan
        plan=backup_plan(router,expected,c['maintenance']['backup_keep'])
        actions.append({'action':'opt-in archive cleanup once after committed installation','keep':plan['keep'],
                        'currently_eligible_files':len(plan['delete']),'currently_reclaimable_bytes':plan['reclaim_bytes'],
                        'blocked':plan['blocked'],'reasons':plan['reasons'],'protect_current_and_dependencies':True})
    return actions


def apply(router,c,expected,*,timeout=120):
    from sdwan.deployment import start,wait
    actions=preflight(router,c,expected)
    try:previous_backend=json.loads(router.read_file('sdwan-active.json')).get('controller_backend','routeros')
    except ValueError as error:
        if not str(error).startswith('Router file not found:'):raise
        previous_backend='routeros'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    run=ROOT/'runtime';run.mkdir(exist_ok=True)
    snapshot={m:router.call(m) for m in ('system/identity','ip/route','routing/rule','routing/table','tool/netwatch','system/scheduler','system/script','ip/firewall/mangle','ip/firewall/filter','ip/firewall/address-list','ip/settings')}
    (run/f'pre-native-{stamp}.json').write_text(json.dumps(snapshot,indent=2)+'\n')
    # Multiple routers can be configured concurrently. Each transaction needs
    # its own sealed local payload until every file has been uploaded.
    (ROOT/'build').mkdir(exist_ok=True)
    default=next(p for p in c['policies'] if not p['source']);policy=default['name']
    modes={w['name']:w.get('admin_state','enabled') for w in c['wans']}
    allow_no_default=all(modes[wan] in ('drain','down') for wan in default['wans'])
    with tempfile.TemporaryDirectory(prefix='deploy-',dir=ROOT/'build') as directory:
        output=bundle(c,Path(directory))
        token=start(router,output,expected,revision=c['revision'],default_policy=policy,timeout=timeout,allow_no_default=allow_no_default)
        result=wait(router,token,expected,timeout=timeout)
    if previous_backend=='container' and c.get('controller_backend')!='container':
        from sdwan.container_runtime import deactivate
        deactivate(router)
    if 'maintenance' in c:
        from sdwan.maintenance import prune_backups
        try:print(json.dumps({'archive_cleanup':prune_backups(router,expected,c['maintenance']['backup_keep'],execute=True)},ensure_ascii=False))
        except Exception as error:
            # Installation is already committed. A maintenance failure must not
            # claim that routing failed or trigger a second deployment/rollback.
            print(json.dumps({'archive_cleanup_skipped':str(error),'deployment_committed':True},ensure_ascii=False))
    print(json.dumps({'installed':True,'controller':'local Rust container + RouterOS fallback' if c.get('controller_backend')=='container' else 'native RouterOS','deployment':result,'snapshot':f'runtime/pre-native-{stamp}.json','objects':len(actions),'status':router.status()},ensure_ascii=False,indent=2))


def rollback(router,expected,*,timeout=120):
    from sdwan.deployment import start,wait
    if router.call('system/identity')['name']!=expected:raise ValueError('Router identity changed')
    cfg=load(ROOT/'config/sdwan.json')
    (ROOT/'build').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rollback-',dir=ROOT/'build') as directory:
        output=bundle(cfg,Path(directory))
        token=start(router,output,expected,operation='rollback',timeout=timeout)
        result=wait(router,token,expected,timeout=timeout)
    from sdwan.container_runtime import deactivate
    deactivate(router)
    print(json.dumps({'baseline_restored':True,'deployment':result},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default=str(ROOT/'config/sdwan.json'))
    p.add_argument('--url',default='http://127.0.0.1:18080');p.add_argument('--credentials');p.add_argument('--ca')
    p.add_argument('--expect-identity',default='sdwan-edge')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('validate','plan','apply','container-prepare','status','events','enable','disable','rollback'):sub.add_parser(name)
    maintenance=sub.add_parser('prune-backups',help='Preview old verified transaction archives; no deletion unless --execute')
    maintenance.add_argument('--keep',type=int,default=3)
    maintenance.add_argument('--execute',action='store_true')
    b=sub.add_parser('bundle');b.add_argument('--output',default=str(ROOT/'build'))
    a=p.parse_args();c=load(a.config) if a.command in ('validate','bundle','plan','apply','container-prepare') else None
    if a.command=='validate':print(f'Valid: {len(c["wans"])} WANs, {len(c["sla_profiles"])} SLA profiles, {len(c["policies"])} policies. Controller: '+('local Rust container + RouterOS fallback' if c.get('controller_backend')=='container' else 'native RouterOS')+'.');return
    if a.command=='bundle':print(bundle(c,a.output));return
    router=Router(ROOT,a.url,a.credentials,a.ca)
    if a.command=='prune-backups':
        from sdwan.maintenance import prune_backups
        print(json.dumps(prune_backups(router,a.expect_identity,a.keep,execute=a.execute),indent=2,ensure_ascii=False))
    elif a.command=='plan':
        actions=preflight(router,c,a.expect_identity)
        print(json.dumps(actions,indent=2))
        old=''
        for f in router.call('file'):
            if f.get('name')=='sdwan-config.json':old=json.dumps(json.loads(router.read_file(f['name'])),indent=2)+'\n'
        print(''.join(difflib.unified_diff(old.splitlines(True),(json.dumps(c,indent=2)+'\n').splitlines(True),fromfile='router/sdwan-config.json',tofile=a.config)))
        print('Takeover routes:',', '.join(c['takeover_route_comments']))
    elif a.command=='apply':apply(router,c,a.expect_identity)
    elif a.command=='container-prepare':
        from sdwan.container_runtime import prepare
        print(json.dumps(prepare(router,c,a.expect_identity),indent=2))
    elif a.command=='status':
        status=router.status();status['scheduler']=router.call('system/scheduler?name=sdwan-controller');print(json.dumps(status,indent=2,ensure_ascii=False))
    elif a.command=='events':
        print(json.dumps([r for r in router.call('log') if r.get('message','').startswith('SDWAN ')],indent=2,ensure_ascii=False))
    elif a.command in ('enable','disable'):
        sched=router.call('system/scheduler?name=sdwan-controller')
        if len(sched)!=1:raise RuntimeError('Native controller scheduler not installed')
        router.call('system/scheduler/'+sched[0]['.id'],{'disabled':'false' if a.command=='enable' else 'true'},'PATCH')
        print('Native scheduler '+a.command+'d. disable freezes last policy; rollback restores the baseline.')
    elif a.command=='rollback':rollback(router,a.expect_identity)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as e:
        print('ERROR: '+str(e),file=sys.stderr);sys.exit(1)
