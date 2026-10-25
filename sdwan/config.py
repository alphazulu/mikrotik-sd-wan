import ipaddress
import json
import math
import re
from pathlib import Path
from .wan import addressing_kind
from .policies import EXTRA_FIELDS, composite, validate_selectors
from .probes import STRICT_FIELDS,MAX_STRICT_PROBES,validate_probe,native_type,http_codes,requires_fetch

IDENT = re.compile(r'^[a-z][a-z0-9_-]{0,30}$')
PROBE_IDENT = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')


def validate(c):
    def need(condition, message):
        if not condition:
            raise ValueError(message)
    def keys(value, allowed, label, required=None):
        need(isinstance(value,dict), f'{label} must be an object')
        missing=set(allowed if required is None else required)-set(value)
        unknown=set(value)-set(allowed)
        need(not missing,f'{label}: missing fields {sorted(missing)}')
        need(not unknown,f'{label}: unknown fields {sorted(unknown)}')
    required=('schema_version','revision','health','sla_profiles','wans','local_networks','policies','takeover_route_comments','takeover_rule')
    keys(c,required+('takeover_routes','disable_fasttrack','groups','controller_backend','container','maintenance','overlay','vpn_egress'),'config',required)
    if 'maintenance' in c:
        keys(c['maintenance'],('backup_keep',),'maintenance')
        need(type(c['maintenance']['backup_keep']) is int and 1 <= c['maintenance']['backup_keep'] <= 20,'maintenance.backup_keep must be 1..20')
    from .container_config import validate_backend
    validate_backend(c)
    need(type(c.get('schema_version')) is int and c['schema_version'] == 1, 'schema_version must be 1')
    need(isinstance(c.get('revision'), str) and 0 < len(c['revision']) <= 80, 'revision must be a short string')
    h = c['health']
    timing=('interval_seconds','timeout_ms','packet_count','packet_interval_ms','quorum','fail_windows','recover_windows','hold_down_seconds','stale_seconds')
    keys(h,timing+('strict_probe_interval_seconds','strict_probe_timeout_ms'),'health',timing)
    strict_interval=h.get('strict_probe_interval_seconds',10)
    strict_timeout=h.get('strict_probe_timeout_ms',2000)
    need(type(strict_interval) is int and 5<=strict_interval<=300,'strict_probe_interval_seconds must be 5..300')
    need(type(strict_timeout) is int and 100<=strict_timeout<=2000,'strict_probe_timeout_ms must be 100..2000')
    for k in ('interval_seconds', 'timeout_ms', 'packet_count', 'packet_interval_ms', 'quorum', 'fail_windows', 'recover_windows', 'hold_down_seconds', 'stale_seconds'):
        need(type(h[k]) is int and 0 <= h[k] <= 100000, f'health.{k} must be a nonnegative integer')
    need(all(h[k] > 0 for k in ('interval_seconds','timeout_ms','packet_count','packet_interval_ms','quorum','fail_windows','recover_windows')), 'probe timing and windows must be positive')
    need((h['packet_count']-1)*h['packet_interval_ms']+h['timeout_ms'] < h['interval_seconds']*1000, 'ICMP train does not fit the interval')
    need(h['stale_seconds'] >= 2*h['interval_seconds'], 'stale_seconds must cover at least two intervals')
    need(h['packet_count'] <= 1000, 'packet_count exceeds supported lab budget')
    profiles = c['sla_profiles']
    need(isinstance(profiles,dict) and profiles, 'at least one SLA profile required')
    for name, profile in profiles.items():
        keys(profile,('rtt_ms','jitter_ms','loss_percent'),'SLA '+name)
        need(bool(IDENT.fullmatch(name)), f'invalid profile name {name}')
        for key in ('rtt_ms','jitter_ms','loss_percent'):
            value = profile[key]
            need(type(value) in (int,float) and math.isfinite(value) and value >= 0, f'invalid {name}.{key}')
        need(profile['loss_percent'] <= 100, 'loss_percent exceeds 100')
        for key,scale in (('rtt_ms',1000),('jitter_ms',1000),('loss_percent',100)):
            val=profile[key]*scale
            need(val <= 2147483647 and abs(val-round(val))<1e-7,f'{name}.{key} has unsupported precision/range')
    wans = c['wans']
    need(isinstance(wans,list) and 1 <= len(wans) <= 16, '1..16 WANs required')
    names=set(); interfaces=set(); tables=set(); addresses=set(); strict_probes=0
    for w in wans:
        keys(w,('name','interface','address','gateway','probe_table','icmp_target','probes','kind','apn_profile','admin_state','drain_timeout_seconds','vpn_type','vpn_endpoint','vpn_listen_port','vpn_peer_public_key','underlays'),'WAN',('name','interface','probe_table','icmp_target','probes'))
        kind=addressing_kind(w)
        need(w.get('admin_state','enabled') in ('enabled','drain','down'), 'WAN admin_state must be enabled, drain or down')
        timeout=w.get('drain_timeout_seconds',300)
        need(type(timeout) is int and 0<=timeout<=86400, 'WAN drain_timeout_seconds must be 0..86400 (0 keeps established flows without a deadline)')
        need(bool(IDENT.fullmatch(w['name'])) and w['name'] not in names, 'invalid or duplicate WAN name')
        names.add(w['name'])
        need(isinstance(w['interface'],str) and bool(re.fullmatch(r'[^\x00-\x1f\x7f]{1,64}',w['interface'])) and w['interface'] not in interfaces, 'invalid/duplicate interface')
        interfaces.add(w['interface'])
        need(not any(ch in w['interface'] for ch in ('%','@')), 'WAN interface cannot contain route delimiters % or @')
        need(w['probe_table'].startswith('sdwan-') and bool(IDENT.fullmatch(w['probe_table'])) and w['probe_table'] not in tables, 'probe table must be unique and start sdwan-')
        tables.add(w['probe_table'])
        ipaddress.IPv4Address(w['icmp_target'])
        if kind=='static':
            address=ipaddress.IPv4Address(w['address'])
            need(str(address) not in addresses, 'duplicate WAN source address'); addresses.add(str(address))
        need(isinstance(w['probes'],list) and h['quorum']<=len(w['probes'])<=16, 'quorum exceeds targets or more than 16 probes per WAN')
        probes=set(); targets=set()
        for p in w['probes']:
            keys(p,('name','type','host','port','dns_server')+STRICT_FIELDS,'probe',('name','type','host'))
            validate_probe(p)
            strict_probes+=int(requires_fetch(p))
            need(isinstance(p['name'],str) and bool(PROBE_IDENT.fullmatch(p['name'])), f'Цель {p["name"]!r}: имя должно содержать латинские буквы, цифры, точки, дефисы или подчёркивания (до 128 символов)')
            need(p['name'] not in probes, f'Повторяется имя контрольной цели: {p["name"]}'); probes.add(p['name'])
            need(p['type'] in ('http-get','https-get','tcp-conn','dns'), 'unsupported probe type')
            need(isinstance(p['host'],str) and bool(re.fullmatch(r'[A-Za-z0-9_.:-]{1,253}',p['host'])), 'invalid probe host')
            if p['type']=='dns':
                ipaddress.IPv4Address(p['dns_server']); target=(p['type'],p['host'],p['dns_server'])
            else:
                need(type(p['port']) is int and 1 <= p['port'] <= 65535, 'invalid TCP port'); target=(p['type'],p['host'],p['port'])
            need(target not in targets, 'duplicate probe targets cannot count toward quorum'); targets.add(target)
    need(strict_probes<=MAX_STRICT_PROBES,'At most 16 asynchronous HTTP body/path probes are supported')
    need(((strict_probes+1)//2)*((strict_timeout+999)//1000+1)<=2*strict_interval,
         'Strict probe schedule exceeds the bounded two-worker freshness budget')
    need(isinstance(c['policies'],list) and 1<=len(c['policies'])<=64,'1..64 policies required')
    policies=c['policies']; sources=[]; pnames=set(); defaults=0
    for p in policies:
        keys(p,('name','source','table','profile','mode','wans','allow_degraded')+EXTRA_FIELDS,'policy',('name','source','table','profile','mode','wans','allow_degraded'))
        need(bool(IDENT.fullmatch(p['name'])) and p['name'] not in pnames, 'invalid/duplicate policy name'); pnames.add(p['name'])
        need(p['profile'] in profiles, 'unknown policy SLA profile')
        need(p['mode'] in ('prefer','strict'), 'supported policy modes: prefer, strict')
        need(type(p['allow_degraded']) is bool, 'allow_degraded must be boolean')
        need(p['wans'] and len(set(p['wans']))==len(p['wans']) and set(p['wans'])<=names, 'unknown/duplicate policy WAN')
        need(p['mode']!='strict' or len(p['wans'])==1, 'strict must select exactly one WAN')
        need(isinstance(p['source'],str),'policy source must be an IPv4 prefix or empty default')
        if p['source']=='':
            defaults+=1;need(p['table']=='main','default policy must use main')
        else:
            n=ipaddress.IPv4Network(p['source'],strict=True)
            sources.append(n)
            need(p['table'].startswith('sdwan-') and bool(IDENT.fullmatch(p['table'])) and p['table'] not in tables,'policy table must be unique and start sdwan-')
            tables.add(p['table'])
    need(defaults==1,'exactly one default policy required')
    validate_selectors(c)
    for n in c['local_networks']:
        net=ipaddress.IPv4Network(n,strict=True);need(net.prefixlen>0,'local_networks cannot bypass the default route')
    keys(c['takeover_rule'],('src-address','table'),'takeover_rule')
    rule=c['takeover_rule']
    if rule['src-address'] or rule['table']:
        ipaddress.IPv4Network(rule['src-address'],strict=True)
        need(isinstance(rule['table'],str) and bool(rule['table']) and not rule['table'].startswith('sdwan-'),'invalid takeover rule table')
    for item in c.get('takeover_routes',[]):
        keys(item,('.id','gateway','dst-address','routing-table'),'takeover route')
        need(bool(re.fullmatch(r'\*[0-9A-Fa-f]+',item['.id'])),'invalid takeover route identifier')
        need(item['dst-address']=='0.0.0.0/0' and item['routing-table']=='main','only main default routes can be adopted')
        need(isinstance(item['gateway'],str) and bool(item['gateway']),'missing takeover gateway')
    for item in c.get('disable_fasttrack',[]):
        keys(item,('.id','chain','action'),'FastTrack selector')
        need(bool(re.fullmatch(r'\*[0-9A-Fa-f]+',item['.id'])) and item['chain']=='forward' and item['action']=='fasttrack-connection','invalid FastTrack selector')
    need(all(isinstance(t,str) and 0<len(t)<128 and not t.startswith('sdwan:') for t in c['takeover_route_comments']), 'invalid takeover route comments')
    from .overlay import validate as validate_overlay
    validate_overlay(c)
    from .vpn_egress import validate as validate_vpn
    validate_vpn(c)
    return c


def load(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8-sig')))


def objects(c):
    result={}
    def add(menu,tag,**fields): result[(menu,tag)]=fields
    for w in c['wans']:
        n=w['name']
        static=w.get('kind','static')=='static'
        gateway={'gateway':w['gateway']+'%'+w['interface']} if static else ({'gateway':w['interface']} if w['kind'] in ('pppoe','lte','vpn') else {})
        source={'src-address':w['address']} if static else {}
        add('ip/route',f'sdwan:v1:pinroute:{n}',**gateway,**{'routing-table':w['probe_table']})
        add('routing/rule',f'sdwan:v1:pinrule:{n}',table=w['probe_table'],**({'src-address':w['address']+'/32'} if static else {}))
        add('tool/netwatch',f'sdwan:v1:icmp:{n}',host=w['icmp_target'],type='icmp',**source)
        for p in w['probes']:
            fields={'port':str(p['port'])} if p['type']!='dns' else {'dns-server':p['dns_server']}
            if p['type'] in ('http-get','https-get') and 'http_codes' in p and not requires_fetch(p):fields['http-codes']=http_codes(p)
            add('tool/netwatch',f'sdwan:v1:probe:{n}:{p["name"]}',host=p['host'],type=native_type(p),**source,**fields)
    for p in c['policies']:
        for i,w in enumerate(p['wans']):
            spec=next(x for x in c['wans'] if x['name']==w)
            gateway={'gateway':spec['gateway']+'%'+spec['interface']} if spec.get('kind','static')=='static' else ({'gateway':spec['interface']} if spec['kind'] in ('pppoe','lte','vpn') else {})
            add('ip/route',f'sdwan:v1:route:{p["name"]}:{w}',**gateway,distance=str(i+1),**{'routing-table':p['table']})
        if p['source'] and not composite(p): add('routing/rule',f'sdwan:v1:client:{p["name"]}',table=p['table'],**{'src-address':p['source']})
    from .overlay import effective_networks
    for n in effective_networks(c): add('routing/rule',f'sdwan:v1:local:{n}',table='main',**{'dst-address':n})
    from .dataplane import objects as dataplane_objects
    result.update(dataplane_objects(c))
    return result
