"""Ordered IPv4 flow selectors shared by validation, planning and diagnostics."""
import ipaddress
import json
import re

MATCH_FIELDS=('source_group','source_list','destination','destination_group','destination_list','in_interface','protocol','src_ports','dst_ports')
EXTRA_FIELDS=MATCH_FIELDS+('priority',)


def composite(policy):
    return any(policy.get(k) not in (None,'','any') for k in MATCH_FIELDS)


def ordered(config):
    return [p for _,p in sorted(enumerate(config['policies']),key=lambda x:(not bool(x[1]['source']),x[1].get('priority',1000000+x[0])))]


def port_ranges(value):
    if not value:return [(1,65535)]
    if not isinstance(value,str) or not re.fullmatch(r'[0-9,-]+',value):raise ValueError('ports must be numbers/ranges, e.g. 80,443,10000-20000')
    parts=value.split(',')
    if len(parts)>15:raise ValueError('at most 15 port entries supported')
    ranges=[]
    for part in parts:
        ends=part.split('-')
        if len(ends)>2 or not all(ends):raise ValueError('invalid port range')
        lo=int(ends[0]);hi=int(ends[-1])
        if not 1<=lo<=hi<=65535:raise ValueError('ports must be in 1..65535 with ascending ranges')
        if any(lo<=b and a<=hi for a,b in ranges):raise ValueError('duplicate/overlapping port ranges')
        ranges.append((lo,hi))
    return ranges


def networks(config,p,source=True):
    field='source' if source else 'destination';group='source_group' if source else 'destination_group'
    base=ipaddress.IPv4Network(p.get(field) or '0.0.0.0/0')
    members=config.get('groups',{}).get(p.get(group),['0.0.0.0/0'])
    return [base if base.subnet_of(n) else n for raw in members if (n:=ipaddress.IPv4Network(raw)).overlaps(base)]


def overlaps(c,a,b):
    if any(not any(x.overlaps(y) for x in networks(c,a,side) for y in networks(c,b,side)) for side in (True,False)):return False
    if a.get('in_interface') and b.get('in_interface') and a['in_interface']!=b['in_interface']:return False
    if a.get('protocol','any')!='any' and b.get('protocol','any')!='any' and a['protocol']!=b['protocol']:return False
    return all(any(lo<=end and start<=hi for lo,hi in port_ranges(a.get(k)) for start,end in port_ranges(b.get(k))) for k in ('src_ports','dst_ports'))


def covers(c,a,b):
    # An opaque live list cannot prove coverage of another selector/list.
    for field in ('source_list','destination_list'):
        if a.get(field) and a.get(field)!=b.get(field):return False
    for side in (True,False):
        outer=list(ipaddress.collapse_addresses(networks(c,a,side)))
        if not all(any(n.subnet_of(other) for other in outer) for n in networks(c,b,side)):return False
    if a.get('in_interface') and a['in_interface']!=b.get('in_interface'):return False
    if a.get('protocol','any')!='any' and a['protocol']!=b.get('protocol','any'):return False
    for field in ('src_ports','dst_ports'):
        merged=[]
        for start,end in sorted(port_ranges(a.get(field))):
            if merged and start<=merged[-1][1]+1:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
            else:merged.append((start,end))
        if not all(any(start<=lo and hi<=end for start,end in merged) for lo,hi in port_ranges(b.get(field))):return False
    return True


def conflicts(c):
    result=[];policies=[p for p in ordered(c) if p['source']]
    for i,a in enumerate(policies):
        for b in policies[i+1:]:
            if overlaps(c,a,b):
                result.append({'first':a['name'],'later':b['name'],'resolution':'first matching policy wins','explicit':('priority' in a and 'priority' in b),'shadowed':covers(c,a,b)})
    return result


def validate_selectors(c):
    groups=c.get('groups',{})
    if not isinstance(groups,dict) or len(groups)>64:raise ValueError('groups must be an object with at most64 groups')
    for name,members in groups.items():
        if not re.fullmatch(r'[a-z][a-z0-9_-]{0,30}',name):raise ValueError('invalid group name')
        if not isinstance(members,list) or not 1<=len(members)<=256:raise ValueError('group must contain1..256 IPv4 prefixes')
        parsed=[]
        for raw in members:
            net=ipaddress.IPv4Network(raw,strict=True)
            if any(net.overlaps(other) for other in parsed):raise ValueError('duplicate/overlapping members in group '+name)
            parsed.append(net)
    priorities=set()
    for p in c['policies']:
        for key in MATCH_FIELDS:
            if key in p and not isinstance(p[key],str):raise ValueError(key+' must be a string')
        if 'priority' in p:
            value=p['priority']
            if type(value) is not int or not 1<=value<=999999 or value in priorities:raise ValueError('policy priority must be unique,1..999999')
            priorities.add(value)
        if not p['source'] and (composite(p) or 'priority' in p):raise ValueError('default policy cannot have selectors/priority; use source0.0.0.0/0 and a separate table')
        for field in ('source_group','destination_group'):
            if p.get(field) and p[field] not in groups:raise ValueError('unknown '+field+': '+p[field])
        if p.get('destination'):ipaddress.IPv4Network(p['destination'],strict=True)
        for side in ('source','destination'):
            if p.get(side+'_list'):
                name=p[side+'_list']
                if not 1<=len(name.encode('utf-8'))<=64 or name!=name.strip() or name.startswith('!') or any(ord(ch)<32 or ord(ch)==127 for ch in name):raise ValueError('invalid '+side+' Address List name')
                if p.get(side+'_group'):raise ValueError(side+'_list and '+side+'_group are mutually exclusive')
        if p.get('in_interface'):
            if not re.fullmatch(r'[^\x00-\x1f\x7f]{1,64}',p['in_interface']):raise ValueError('invalid input interface')
            if p['in_interface'] in {w['interface'] for w in c['wans']}:raise ValueError('policy input interface must not be a selected WAN')
        if p.get('protocol','any') not in ('any','tcp','udp','icmp'):raise ValueError('protocol must be any/tcp/udp/icmp')
        for field in ('src_ports','dst_ports'):
            port_ranges(p.get(field))
            if p.get(field) and p.get('protocol') not in ('tcp','udp'):raise ValueError('ports require TCP or UDP')
        if p['source'] and (not networks(c,p) or not networks(c,p,False)):raise ValueError('policy source/destination does not intersect its group')
    for problem in conflicts(c):
        if not problem['explicit']:raise ValueError('overlapping client sources/selectors require explicit priorities: '+problem['first']+' / '+problem['later'])


def signature(c):
    return json.dumps({'groups':c.get('groups',{}),'policies':[{k:p.get(k,'any' if k=='protocol' else '') for k in ('name','source',*EXTRA_FIELDS)} for p in ordered(c)]},sort_keys=True,separators=(',',':'))


def match_flow(c,source,destination,protocol='tcp',src_port=None,dst_port=None,in_interface='',router_addresses=(),address_lists=None):
    src=ipaddress.IPv4Address(source);dst=ipaddress.IPv4Address(destination)
    if protocol not in ('tcp','udp','icmp'):raise ValueError('protocol must be tcp/udp/icmp')
    for value in (src_port,dst_port):
        if value is not None and (type(value) is not int or not 1<=value<=65535):raise ValueError('flow ports must be1..65535')
    if in_interface in {w['interface'] for w in c['wans']}:return {'bypass':True,'reason':'Входящий WAN: ответ закрепляется за интерфейсом входа'}
    local={w['address'] for w in c['wans'] if w.get('address')}|set(router_addresses)
    if str(dst) in local:return {'bypass':True,'reason':'IP самого MikroTik: локальная доставка'}
    from .overlay import effective_networks
    if any(dst in ipaddress.IPv4Network(n) for n in effective_networks(c)):return {'bypass':True,'reason':'Локальная сеть: lookup main'}
    for p in ordered(c):
        if not any(src in n for n in networks(c,p)) or not any(dst in n for n in networks(c,p,False)):continue
        if p.get('in_interface') and p['in_interface']!=in_interface:continue
        if p.get('protocol','any') not in ('any',protocol):continue
        if any(p.get(key) and (port is None or not any(lo<=port<=hi for lo,hi in port_ranges(p[key]))) for key,port in (('src_ports',src_port),('dst_ports',dst_port))):continue
        list_match=True
        for field,ip in (('source_list',src),('destination_list',dst)):
            if p.get(field):
                name=p[field]
                if address_lists is None or name not in address_lists:raise ValueError('Нужен свежий состав Address List «'+name+'» для объяснения этого соединения')
                if not any(ip in ipaddress.IPv4Network(n,strict=False) for n in address_lists[name]):list_match=False;break
        if not list_match:continue
        return {'bypass':False,'policy':p['name'],'profile':p['profile'],'mode':p['mode'],'priority':p.get('priority'),'reason':'first matching selector in configured order'}
    raise ValueError('No matching default policy')
