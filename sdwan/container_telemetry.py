"""Optional local web provisioning. No statistics are written through this module."""
import ipaddress
import re
from .container_config import BRIDGE,VETH,telemetry,addresses

PREFIX='sdwan-container:web-'
CLIENTS='sdwan-container-web-clients'

def validate_interfaces(router,config):
    cfg=telemetry(config)
    if not cfg['enabled']:return
    if any(r.get('swap') in ('true',True) or r.get('swap-enabled') in ('true',True) for r in router.call('disk/print',{'.proplist':'slot,swap,swap-enabled'},'POST')):raise ValueError('RAM-only telemetry requires no enabled RouterOS swap devices; global disk settings are not changed')
    if any(r.get('list')==CLIENTS and (r.get('comment')!=PREFIX+'source' or r.get('dynamic')=='true') for r in router.call('ip/firewall/address-list')):raise ValueError('Reserved web source list contains unrelated entries')
    interfaces=router.call('interface/print',{'.proplist':'name,dynamic'},'POST')
    names={r['name'] for r in interfaces}
    forbidden={BRIDGE,VETH}|{w['interface'] for w in config['wans']}
    ports=router.call('interface/bridge/port/print',{'.proplist':'interface,bridge'},'POST')
    members=router.call('interface/list/member/print',{'.proplist':'interface,list'},'POST')
    lists=router.call('interface/list/print',{'.proplist':'name,include,exclude'},'POST')
    memo={}
    def resolve(name,seen):
        if name=='all':return names
        if name in ('static','dynamic'):return {r['name'] for r in interfaces if (r.get('dynamic')=='true')==(name=='dynamic')}
        if name in memo:return memo[name]
        if name in seen or len(seen)>=64:raise ValueError('Circular or excessively nested interface list prevents safe web LAN validation')
        row=next((r for r in lists if r['name']==name),{})
        result=set()
        for child in filter(None,row.get('include','').split(',')):result.update(resolve(child,seen|{name}))
        for child in filter(None,row.get('exclude','').split(',')):result.difference_update(resolve(child,seen|{name}))
        result.update(r['interface'] for r in members if r.get('list')==name)
        memo[name]=result
        return result
    for name in {r['name'] for r in lists if r['name'].upper()=='WAN'}|{r['list'] for r in members if r.get('list','').upper()=='WAN'}:forbidden.update(resolve(name,set()))
    parents=router.call('interface/pppoe-client/print',{'.proplist':'name,interface'},'POST')+router.call('interface/vlan/print',{'.proplist':'name,interface'},'POST')
    # Refuse PPPoE/VLAN WAN carriers, bridges carrying WAN and their ports.
    for _ in range(len(ports)+len(parents)+1):
        previous=len(forbidden)
        for row in parents:
            if row.get('name') in forbidden:forbidden.add(row.get('interface'))
        for row in ports:
            if row.get('interface') in forbidden or row.get('bridge') in forbidden:forbidden.update((row.get('interface'),row.get('bridge')))
        if len(forbidden)==previous:break
    if any(i not in names or i in forbidden for i in cfg['allowed_interfaces']):raise ValueError('Web interface is absent or belongs to a WAN/container bridge')

def process_settings(config):
    cfg=telemetry(config)
    if not cfg['enabled']:return None
    _,_,guest=addresses(config)
    profile=next(p['profile'] for p in config['policies'] if p['table']=='main')
    return {'enabled':True,'listen':guest+':'+str(cfg['port']),'token_file':'/secrets/web-token',
            'allowed_sources':cfg['allowed_sources'],'sample_seconds':cfg['sample_seconds'],
            'history_points':cfg['history_points'],'profile':profile}

def valid_token(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None

def rule_specs(config):
    cfg=telemetry(config)
    if not cfg['enabled']:return []
    _,_,guest=addresses(config);specs=[]
    # Explicit WAN drops precede LAN accepts, including established traffic.
    for index,wan in enumerate(config['wans']):
        specs.append(('web-wan-'+str(index),dict(chain='forward',action='drop',**{'in-interface':wan['interface'],'out-interface':BRIDGE,'dst-address':guest})))
    for index,interface in enumerate(cfg['allowed_interfaces']):
        specs.append(('web-request-'+str(index),dict(chain='forward',action='accept',**{'in-interface':interface,'out-interface':BRIDGE,'src-address-list':CLIENTS,'dst-address':guest,'protocol':'tcp','dst-port':str(cfg['port']),'connection-state':'established,new'})))
        specs.append(('web-reply-'+str(index),dict(chain='forward',action='accept',**{'in-interface':BRIDGE,'out-interface':interface,'src-address':guest,'dst-address-list':CLIENTS,'protocol':'tcp','src-port':str(cfg['port']),'connection-state':'established'})))
    return specs

def provision_sources(router,config):
    for row in router.call('ip/firewall/address-list'):
        if row.get('comment','').startswith(PREFIX) and row.get('list')==CLIENTS:router.call('ip/firewall/address-list/'+row['.id'],method='DELETE')
    cfg=telemetry(config)
    if cfg['enabled']:
        for source in cfg['allowed_sources']:router.call('ip/firewall/address-list',{'list':CLIENTS,'address':source,'comment':PREFIX+'source'},'PUT')

def check_ready(router,config,actual,entrypoint,token_path):
    expected=process_settings(config)
    if (expected is None and 'telemetry' in actual) or actual.get('telemetry')!=expected:raise ValueError('Prepared telemetry settings differ; prepare the stopped container first')
    if expected:
        if entrypoint!='/sdwan-controller-web':raise ValueError('Telemetry requires the optional web scratch image')
        if not valid_token(router.read_file(token_path)):raise ValueError('Dedicated mounted web token is missing or invalid')
    rules=[r for r in router.call('ip/firewall/filter') if r.get('comment','').startswith(PREFIX)]
    specs=rule_specs(config)
    if len(rules)!=len(specs):raise ValueError('Prepared web firewall rules differ')
    for tag,fields in specs:
        matches=[r for r in rules if r.get('comment')=='sdwan-container:'+tag]
        if len(matches)!=1 or matches[0].get('disabled')=='true' or any(str(matches[0].get(k,''))!=str(v) for k,v in fields.items()):raise ValueError('Prepared web firewall scope differs')
    sources=[r for r in router.call('ip/firewall/address-list') if r.get('list')==CLIENTS]
    wanted=set(telemetry(config)['allowed_sources']) if expected else set()
    if len(sources)!=len(wanted) or {str(ipaddress.IPv4Network(r['address'],strict=False)) for r in sources}!=wanted or any(r.get('dynamic')=='true' or r.get('disabled')=='true' or r.get('comment')!=PREFIX+'source' for r in sources):raise ValueError('Prepared web source ACL differs')
    if specs:
        all_rules=router.call('ip/firewall/filter');positions={r['.id']:i for i,r in enumerate(all_rules)}
        drops=[positions[r['.id']] for r in all_rules if r.get('comment') in ('sdwan-container:no-forward','sdwan-container:no-forward-to-container')]
        if len(drops)!=2 or max(positions[r['.id']] for r in rules)>=min(drops):raise ValueError('Web rules must precede container isolation drops')
        wan=[positions[r['.id']] for r in rules if r.get('comment','').startswith(PREFIX+'wan-')]
        accepts=[positions[r['.id']] for r in rules if r.get('action')=='accept']
        if wan and accepts and max(wan)>=min(accepts):raise ValueError('Web WAN drops must precede LAN accepts')
        unmanaged=[positions[r['.id']] for r in all_rules if r.get('chain')=='forward' and r.get('disabled')!='true' and r.get('dynamic')!='true' and not r.get('comment','').startswith('sdwan-container:')]
        if unmanaged and max(drops)>=min(unmanaged):raise ValueError('Container isolation must precede existing forward rules')
