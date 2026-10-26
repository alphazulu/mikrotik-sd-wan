"""Read-only router inventory and deterministic configuration generation."""
import copy
from datetime import datetime,timezone
import ipaddress
import json
from .wan import inferred_kind,adopted_dynamic_route,interface_route
from .lte import apn_binding,profile_names

FIELDS={
 'interface':'name,type,running,disabled,comment,default-name,mac-address',
 'ip/address':'.id,address,network,interface,actual-interface,disabled,dynamic,invalid',
 'ip/route':'.id,dst-address,gateway,immediate-gw,routing-table,distance,comment,disabled,dynamic,active,static,dhcp,modem,vpn,vrf-interface',
 'routing/rule':'.id,src-address,dst-address,table,action,disabled,comment',
 'ip/dhcp-client':'.id,interface,status,address,gateway,disabled,add-default-route,default-route-tables',
 'interface/pppoe-client':'.id,name,interface,disabled,running,add-default-route',
 'interface/lte':'.id,name,disabled,running,apn-profiles,apn-profile',
 'interface/lte/apn':'.id,name,add-default-route,default-route-distance,ip-type,passthrough-interface,use-peer-dns,use-network-apn',
 'interface/bridge/port':'.id,interface,bridge,disabled',
 'interface/list/member':'interface,list,disabled',
 'ip/firewall/nat':'.id,chain,action,out-interface,out-interface-list,disabled',
 'ip/firewall/filter':'.id,chain,action,disabled,dynamic',
 'ip/firewall/mangle':'.id,chain,action,new-routing-mark,disabled,comment',
 'ip/firewall/raw':'.id,chain,action,disabled',
}


def truth(v):return v is True or str(v).lower() in ('true','yes','1')


def rows(value):return value if isinstance(value,list) else [value]


def discover(router,progress=None):
    """Never invokes a mutation and never requests PPPoE passwords or user lists."""
    inventory={'captured_utc':datetime.now(timezone.utc).isoformat(),'warnings':[],'unreadable_paths':[]}
    for key,path in [('identity','system/identity'),('resource','system/resource')]:
        value=rows(router.call(path+'/print',{'.proplist':'name' if key=='identity' else 'version,board-name,architecture-name,platform,cpu,cpu-count,cpu-frequency,cpu-load,total-memory,free-memory,total-hdd-space,free-hdd-space,uptime'},'POST'))
        if not value:raise ValueError('Router returned no '+key)
        inventory[key]=value[0]
    from .platform_support import collect as collect_platform
    inventory['platform_support']=collect_platform(router)
    for path,fields in FIELDS.items():
        if progress:progress(path)
        try:inventory[path]=rows(router.call(path+'/print',{'.proplist':fields},'POST'))
        except RuntimeError as e:
            if path in ('interface','ip/address','ip/route','routing/rule','ip/dhcp-client','interface/bridge/port'):raise
            inventory[path]=[];inventory['unreadable_paths'].append(path);inventory['warnings'].append(f'{path}: {e}')
    inventory['active_config']=None
    try:
        files=router.call('file/print',{'.proplist':'.id,name'},'POST')
        active=next((f for f in files if f.get('name','').rsplit('/',1)[-1]=='sdwan-active.json'),None)
        if active:
            contents=router.read_file('sdwan-active.json')
            from .config import validate
            inventory['active_config']=validate(json.loads(contents))
    except (RuntimeError,ValueError,KeyError) as e:
        inventory['active_config_error']=str(e);inventory['warnings'].append('Cannot import active SD-WAN configuration: '+str(e))
    from .vpn_egress import inventory as vpn_inventory
    try:
        inventory['vpn_interfaces']=vpn_inventory(router)
        inventory['warnings'].extend(v['interface']+': '+v['unsupported_reason'] for v in inventory['vpn_interfaces'] if v.get('unsupported_reason'))
    except (RuntimeError,ValueError,KeyError,TypeError) as error:
        inventory['vpn_interfaces']=[];inventory['warnings'].append('VPN inventory unavailable: '+str(error))
    from .address_lists import snapshot
    try:
        lists=snapshot(router);inventory['address_list_names']=sorted(lists) if lists is not None else []
        if lists is None:inventory['warnings'].append('Address List inventory exceeds bounded API budget or is unavailable; enter its name manually.')
    except (RuntimeError,ValueError,KeyError,TypeError):inventory['address_list_names']=[]
    inventory['candidates']=candidates(inventory)
    return inventory


def gateway_ip(value):
    value=str(value).split('@')[0].split('%')[0]
    try:return str(ipaddress.IPv4Address(value))
    except ValueError:return None


class WANSelectionError(ValueError):
    def __init__(self,message,interface='',field=''):
        super().__init__(message);self.interface=interface;self.field=field


def validate_wan_choices(inventory,choices):
    """Validate step 1 before targets; retain the interface/field for GUI focus."""
    if not choices:raise WANSelectionError('Отметьте хотя бы один внешний интерфейс WAN.')
    selected=[dict(x) for x in choices]
    if len({x['interface'] for x in selected})!=len(selected):raise WANSelectionError('Один интерфейс выбран несколько раз.')
    by_interface={x['interface']:x for x in inventory['candidates']}
    used=set()
    for choice in selected:
        name=choice['interface'];candidate=by_interface.get(name)
        if not candidate:raise WANSelectionError('Интерфейс отсутствует на роутере: '+name,name)
        if candidate['disabled']:raise WANSelectionError('Интерфейс выключен: '+name,name)
        if candidate['bridge']:raise WANSelectionError(f'{name} входит в bridge {candidate["bridge"]}. Выберите L3-интерфейс bridge/VLAN.',name)
        kind=candidate.get('kind','static')
        if candidate.get('kind_error'):raise WANSelectionError(candidate['kind_error'],name)
        if candidate['dynamic'] and kind=='static':raise WANSelectionError(f'{name}: тип динамической адресации не поддерживается. Выберите static, DHCP-client, логический PPPoE или native LTE.',name)
        try:priority=int(choice.get('priority',0))
        except (TypeError,ValueError):priority=0
        if not 1<=priority<=16:raise WANSelectionError(f'WAN «{name}»: приоритет должен быть от 1 до 16.',name,'priority')
        if priority in used:raise WANSelectionError(f'WAN «{name}»: приоритет {priority} уже занят. Задайте разные приоритеты каналов.',name,'priority')
        used.add(priority);choice['priority']=priority
        choice['kind']=kind
        if kind=='lte':
            try:
                binding=apn_binding(name,inventory.get('interface/lte',[]),inventory.get('interface/lte/apn',[]),expected_profile=choice.get('apn_profile') or candidate.get('apn_profile'),managed_interfaces=[c['interface'] for c in selected])
            except ValueError as error:raise WANSelectionError(str(error),name,'apn_profile') from error
            choice['apn_profile']=binding['apn_profile']
        if kind!='static':
            # These form values are an observed session, not fixed settings.
            choice['address']='';choice['gateway']=''
            continue
        for field,label in [('address','IPv4-адрес'),('gateway','шлюз')]:
            value=str(choice.get(field) or '').strip()
            if not value:
                options=candidate['addresses' if field=='address' else 'gateways']
                if len(options)>1:detail='Найдено несколько вариантов: '+', '.join(options)+'. Выберите нужный в нижней форме шага 1.'
                elif field=='address':detail='На этом интерфейсе не найден IPv4-адрес. Выберите интерфейс с назначенным адресом либо настройте адрес на MikroTik и получите настройки заново.'
                else:detail='Шлюз не найден автоматически. Укажите адрес шлюза провайдера в нижней форме шага 1.'
                raise WANSelectionError(f'WAN «{name}»: не указан {label}.\n{detail}',name,field)
            try:choice[field]=str(ipaddress.IPv4Address(value))
            except ValueError:raise WANSelectionError(f'WAN «{name}»: некорректный {label} «{value}». Укажите IPv4 без маски.',name,field) from None
        if choice['address'] not in candidate['addresses']:raise WANSelectionError(f'WAN «{name}»: адрес {choice["address"]} не назначен этому интерфейсу.',name,'address')
        if choice['address']==choice['gateway']:raise WANSelectionError(f'WAN «{name}»: адрес и шлюз совпадают.',name,'gateway')
    return sorted(selected,key=lambda x:x['priority'])


def candidates(inventory):
    active=inventory.get('active_config') or {};known={w['interface']:w for w in active.get('wans',[])}
    members={r['interface']:r['bridge'] for r in inventory.get('interface/bridge/port',[]) if not truth(r.get('disabled'))}
    wanlist={r['interface'] for r in inventory.get('interface/list/member',[]) if r.get('list','').upper()=='WAN' and not truth(r.get('disabled'))}
    dhcp={r['interface']:r for r in inventory.get('ip/dhcp-client',[]) if not truth(r.get('disabled'))}
    ppp={r['name']:r for r in inventory.get('interface/pppoe-client',[]) if not truth(r.get('disabled'))}
    result=[]
    for iface in inventory.get('interface',[]):
        name=iface['name'];addresses=[];networks=[];dynamic=False
        kind_error=''
        try:kind=inferred_kind(name,inventory.get('ip/dhcp-client',[]),inventory.get('interface/pppoe-client',[]),inventory.get('interface/lte',[]))
        except ValueError as error:kind='static';kind_error=str(error)
        if known.get(name,{}).get('kind')=='dhcp' and any(row.get('interface')==name for row in inventory.get('ip/dhcp-client',[])):kind='dhcp'
        apn_profile=''
        if kind=='lte':
            radio=next((r for r in inventory.get('interface/lte',[]) if r.get('name')==name),{})
            profiles=profile_names(radio)
            if len(profiles)==1:apn_profile=profiles[0]
            if len(profiles)!=1:kind_error='LTE требует ровно один APN профиль'
            if 'interface/lte/apn' in inventory.get('unreadable_paths',[]):kind_error='Нет доступа к APN профилям LTE'
        elif iface.get('type','').lower()=='lte':kind_error='Не удалось прочитать параметры native LTE; переподключитесь с правами чтения LTE/APN'
        peers=[]
        for a in inventory.get('ip/address',[]):
            if a.get('interface')!=name or truth(a.get('disabled')) or truth(a.get('invalid')):continue
            try:
                parsed=ipaddress.IPv4Interface(a['address']);addresses.append(str(parsed.ip));networks.append(parsed.network)
                dynamic=dynamic or truth(a.get('dynamic'))
                if kind=='pppoe' and truth(a.get('dynamic')) and parsed.network.prefixlen==32 and gateway_ip(a.get('network')):peers.append(gateway_ip(a['network']))
            except (ValueError,KeyError):continue
        gateways=[];distances=[]
        for route in inventory.get('ip/route',[]):
            if route.get('dst-address')!='0.0.0.0/0':continue
            if kind=='lte' and adopted_dynamic_route(route,[{'kind':'lte','interface':name}]) and not truth(route.get('disabled')):
                try:distances.append(int(route.get('distance',255)))
                except ValueError:pass
            # immediate-gw is the actual next hop; gateway may be a recursive
            # reachability target several hops away, not the provider gateway.
            immediate=route.get('immediate-gw','')
            resolved=[entry.rsplit('%',1)[0] for entry in immediate.split(',') if '%' in entry and entry.rsplit('%',1)[1]==name]
            entries=resolved or route.get('gateway','').split(',')
            for entry in entries:
                ip=gateway_ip(entry)
                if not ip:continue
                attached=bool(resolved) or any(ipaddress.IPv4Address(ip) in net for net in networks)
                if attached:
                    if ip not in gateways:gateways.append(ip)
                    try:distances.append(int(route.get('distance',255)))
                    except ValueError:pass
        if name in dhcp and gateway_ip(dhcp[name].get('gateway')):
            gw=gateway_ip(dhcp[name]['gateway'])
            if gw not in gateways:gateways.append(gw)
        if kind=='pppoe':gateways=list(dict.fromkeys(peers+gateways))
        if kind=='lte':gateways=[name]
        k=known.get(name,{})
        if k.get('kind')=='vpn' or any(v['interface']==name for v in inventory.get('vpn_interfaces',[])):
            kind='vpn'
            kind_error='Добавьте VPN отдельно: «VPN по Address List» на шаге 3; общая Internet-политика остаётся на физических WAN.'
        reason=[]
        if k:reason.append('текущий SD-WAN')
        if name in wanlist:reason.append('список WAN')
        if gateways:reason.append('найден шлюз')
        if name in members:reason.append('порт bridge '+members[name])
        if dynamic or name in dhcp:reason.append('динамический адрес / DHCP')
        if kind=='pppoe':reason.append('PPPoE — параметры текущей сессии')
        if kind=='dhcp':reason.append('DHCP — параметры текущей аренды')
        if kind=='lte':reason.append('LTE — APN '+apn_profile)
        result.append({'interface':name,'type':iface.get('type',''),'running':truth(iface.get('running')),'disabled':truth(iface.get('disabled')),
          'kind':kind,'kind_error':kind_error,'apn_profile':apn_profile,'addresses':addresses,'networks':[str(net) for net in networks],'gateways':gateways,'address':(k.get('address') if kind=='static' else '') or (addresses[0] if len(addresses)==1 else ''),
          'gateway':(k.get('gateway') if kind=='static' else '') or (gateways[0] if len(gateways)==1 else ''),'name':k.get('name',''),
          'priority':next((i+1 for p in active.get('policies',[]) if not p.get('source') for i,w in enumerate(p['wans']) if w==k.get('name')),min(distances,default=255)),
          'suggested':not (k.get('kind')=='vpn' or any(v['interface']==name for v in inventory.get('vpn_interfaces',[]))) and bool(k or name in wanlist or gateways or kind in ('dhcp','pppoe','lte')),'bridge':members.get(name,''),
          'dynamic':dynamic or name in dhcp or name in ppp or kind=='lte','reason':'; '.join(reason),'comment':iface.get('comment','')})
    return result


def generate(inventory,choices,*,keep_policies=True,probes=None,icmp_target=None):
    """Generate from explicit user-selected interfaces; never guess a missing gateway."""
    from .config import validate
    unknown=set(inventory.get('unreadable_paths',[])) & {'interface/pppoe-client','ip/firewall/filter','ip/firewall/mangle','ip/firewall/raw'}
    if unknown:raise ValueError('Недостаточно данных для проверки конфликтов. Разрешите чтение и подключитесь заново: '+', '.join(sorted(unknown)))
    if inventory.get('active_config_error') and any(r.get('comment','').startswith('sdwan:') for r in inventory.get('ip/route',[])):raise ValueError('Не удалось прочитать действующий SD-WAN. Исправьте права/формат перед созданием новой конфигурации.')
    selected=validate_wan_choices(inventory,choices)
    active=inventory.get('active_config')
    if active:
        from .vpn_egress import canonical
        active=canonical(active)
    base=copy.deepcopy(active) if active else {
      'schema_version':1,'revision':'discovered','health':{'interval_seconds':5,'timeout_ms':1000,'packet_count':20,'packet_interval_ms':50,'quorum':2,'fail_windows':3,'recover_windows':6,'hold_down_seconds':60,'stale_seconds':20},
      'sla_profiles':{'default':{'rtt_ms':150,'jitter_ms':30,'loss_percent':2},'voice':{'rtt_ms':80,'jitter_ms':15,'loss_percent':1}},
      'wans':[],'local_networks':[],'policies':[],'takeover_route_comments':[],'takeover_rule':{'src-address':'','table':''}}
    by_interface={x['interface']:x for x in inventory['candidates']};old={w['interface']:w for w in (active or {}).get('wans',[])}
    wans=[];used=set();wan_networks=[]
    retained_vpns=copy.deepcopy([w for w in (active or {}).get('wans',[]) if w.get('kind')=='vpn']) if keep_policies else []
    reserved={old[x['interface']]['name'] for x in selected if x['interface'] in old}|{w['name'] for w in retained_vpns}
    for index,choice in enumerate(selected,1):
        name=choice['interface'];candidate=by_interface.get(name)
        ip=choice['address'];gw=choice['gateway'];kind=choice['kind']
        observed_ip=ip if kind=='static' else candidate['address']
        for address,network in zip(candidate['addresses'],candidate.get('networks',[])):
            if address!=observed_ip:continue
            net=ipaddress.IPv4Network(network)
            if any(net.overlaps(other) for other in wan_networks):raise ValueError('Подсети выбранных WAN перекрываются. Для них нужна отдельная схема VRF/привязки шлюза к интерфейсу.')
            wan_networks.append(net)
        previous=old.get(name)
        if previous:wn=previous['name']
        else:
            number=1
            while 'wan'+str(number) in used|reserved:number+=1
            wn='wan'+str(number)
        used.add(wn)
        w=copy.deepcopy(previous) if previous else {'name':wn,'probe_table':'sdwan-probe-'+wn}
        w.update(name=wn,interface=name,kind=kind)
        if kind=='lte':w['apn_profile']=choice['apn_profile']
        else:w.pop('apn_profile',None)
        if kind=='static':w.update(address=ip,gateway=gw)
        else:w.pop('address',None);w.pop('gateway',None)
        if probes is not None:w['probes']=copy.deepcopy(probes)
        if icmp_target is not None:w['icmp_target']=icmp_target
        if not w.get('probes') or not w.get('icmp_target'):raise ValueError('Задайте ICMP-цель и контрольные TCP/HTTP/DNS цели на шаге 2.')
        wans.append(w)
    order=[w['name'] for w in wans];selected_ifaces={w['interface'] for w in wans}
    physical_names=set(order)
    for w in retained_vpns:
        if not set(w['underlays'])<=physical_names:raise ValueError('VPN '+w['name']+' использует исключённый физический WAN; включите его либо измените underlays VPN.')
    wans.extend(retained_vpns);selected_ifaces.update(w['interface'] for w in retained_vpns)
    base['wans']=wans
    if not retained_vpns:base.pop('vpn_egress',None)
    defaults=next((copy.deepcopy(p) for p in base['policies'] if not p.get('source')),{'name':'default','source':'','table':'main','profile':'default','mode':'prefer','allow_degraded':False})
    if retained_vpns and any(name in {w['name'] for w in retained_vpns} for name in defaults.get('wans',[])):
        if not set(defaults['wans'])<={w['name'] for w in wans}:raise ValueError('Общая политика использует исключённый WAN; исправьте её порядок перед генерацией.')
    else:defaults.update(wans=order,mode='prefer')
    policies=[defaults]
    if keep_policies and active:
        for p in active['policies']:
            if not p['source']:continue
            if not set(p['wans'])<={w['name'] for w in wans}:raise ValueError(f'Политика {p["name"]} использует исключённый WAN. Снимите «Сохранить политики клиентов» либо включите все её WAN.')
            policies.append(copy.deepcopy(p))
    base['policies']=policies
    networks=[]
    vpn_ifaces={v['interface'] for v in inventory.get('vpn_interfaces',[])}|{w['interface'] for w in (active or {}).get('wans',[]) if w.get('kind')=='vpn'}
    for a in inventory['ip/address']:
        if a.get('interface') in selected_ifaces|vpn_ifaces or truth(a.get('disabled')) or truth(a.get('invalid')):continue
        try:
            net=ipaddress.IPv4Interface(a['address']).network
            if not net.is_loopback and str(net) not in networks:networks.append(str(net))
        except ValueError:continue
    base['local_networks']=networks
    actual_routes={r['.id']:r for r in inventory['ip/route']}
    takeovers=[copy.deepcopy(s) for s in base.get('takeover_routes',[]) if s['.id'] in actual_routes and all(actual_routes[s['.id']].get(k,'main' if k=='routing-table' else '')==s[k] for k in ('gateway','dst-address','routing-table'))]
    inventory['unselected_vpn_defaults']=any(r.get('dst-address') in ('0.0.0.0/0','0.0.0.0/1','128.0.0.0/1') and r.get('routing-table','main')=='main' and not truth(r.get('disabled')) and any(interface_route(r,iface) for iface in vpn_ifaces) and not any(interface_route(r,w['interface']) for w in retained_vpns) for r in inventory['ip/route'])
    gateways={gateway for choice in selected for gateway in by_interface[choice['interface']]['gateways'] if gateway_ip(gateway)}
    gateways.update(w['gateway'] for w in wans if w.get('kind','static')=='static')
    for r in inventory['ip/route']:
        if r.get('dst-address')!='0.0.0.0/0' or r.get('routing-table','main')!='main' or r.get('comment','').startswith('sdwan:'):continue
        if any(interface_route(r,iface) for iface in vpn_ifaces) and not any(interface_route(r,w['interface']) for w in retained_vpns):
            inventory['unselected_vpn_defaults']=True
            continue # safe draft only; preflight still rejects unadopted routes
        if truth(r.get('dynamic')):
            if not truth(r.get('disabled')) and not adopted_dynamic_route(r,wans):raise ValueError('Активный динамический default route не принадлежит выбранному DHCP/PPPoE/LTE WAN.')
            continue
        if any(interface_route(r,w['interface']) for w in retained_vpns):
            selector={'.id':r['.id'],'gateway':r.get('gateway',''),'dst-address':'0.0.0.0/0','routing-table':'main'}
            takeovers=[x for x in takeovers if x['.id']!=r['.id']];takeovers.append(selector)
            continue
        resolved=r.get('immediate-gw','').split(',')
        matching_resolved=bool(resolved[0]) and all(any(entry==w['gateway']+'%'+w['interface'] for w in wans if w.get('kind','static')=='static') for entry in resolved)
        if gateway_ip(r.get('gateway','')) not in gateways and not matching_resolved:
            if not truth(r.get('disabled')):raise ValueError('Есть default route через невыбранный WAN: '+r.get('gateway','')+'. Уточните список внешних каналов.')
            continue
        if r.get('comment') in base['takeover_route_comments']:continue
        selector={'.id':r['.id'],'gateway':r.get('gateway',''),'dst-address':'0.0.0.0/0','routing-table':r.get('routing-table','main')}
        takeovers=[x for x in takeovers if x['.id']!=selector['.id']];takeovers.append(selector)
    if takeovers:base['takeover_routes']=takeovers
    else:base.pop('takeover_routes',None)
    previously_disabled={f['.id'] for f in base.get('disable_fasttrack',[])}
    fasttrack=[{'.id':f['.id'],'chain':f.get('chain','forward'),'action':'fasttrack-connection'} for f in inventory.get('ip/firewall/filter',[]) if f.get('action')=='fasttrack-connection' and (not truth(f.get('disabled')) or f['.id'] in previously_disabled)]
    if fasttrack:base['disable_fasttrack']=fasttrack
    else:base.pop('disable_fasttrack',None)
    marked=[m for m in inventory.get('ip/firewall/mangle',[]) if m.get('action') in ('mark-routing','mark-connection','route') and not truth(m.get('disabled')) and not m.get('comment','').startswith('sdwan:v1:')]
    if marked:raise ValueError('Обнаружены сторонние активные mangle mark-routing/mark-connection/route. Нужна явная согласованная схема политик перед генерацией.')
    if any(r.get('action')=='notrack' and not truth(r.get('disabled')) for r in inventory.get('ip/firewall/raw',[])):raise ValueError('Активные RAW notrack несовместимы с маркировкой соединений SD-WAN.')
    base['revision']='wizard-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    return validate(base)
