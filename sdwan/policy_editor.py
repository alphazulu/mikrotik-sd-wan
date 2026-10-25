"""Local construction of ordinary WAN policies from IP or live-list selectors."""
import ipaddress
from .policies import ordered
from .vpn_egress import canonical

def selector(mode,value):
    if mode=='any':return {}
    if mode=='ip':return {'ip':str(ipaddress.IPv4Network(value,strict=True))}
    if mode=='list':
        if not isinstance(value,str) or not value or value!=value.strip():raise ValueError('Укажите имя Address List MikroTik; для любого адреса выберите «Любой адрес»')
        return {'list':value}
    raise ValueError('Источник/назначение: выберите IP, Address List или любой адрес')

def create(cfg,*,name,source_mode,source_value,destination_mode,destination_value,wans,profile,priority):
    from .config import IDENT,validate
    result=canonical(cfg)
    if not isinstance(name,str) or not IDENT.fullmatch(name) or any(p['name']==name for p in result['policies']):raise ValueError('Укажите уникальное имя политики: латинские буквы, цифры, дефис или подчёркивание')
    if type(priority) is not int or not 1<=priority<=999999 or any(p.get('priority')==priority for p in result['policies']):raise ValueError('Приоритет должен быть уникальным целым числом 1–999999')
    src=selector(source_mode,source_value);dst=selector(destination_mode,destination_value)
    used={w['probe_table'] for w in result['wans']}|{p['table'] for p in result['policies']};table='sdwan-'+name[:25];index=1
    while table in used:
        suffix='-'+str(index);table='sdwan-'+name[:25-len(suffix)]+suffix;index+=1
    policy=dict(name=name,source=src.get('ip','0.0.0.0/0'),table=table,profile=profile,priority=priority,mode='prefer',wans=list(wans),allow_degraded=False)
    if 'list' in src:policy['source_list']=src['list']
    if 'ip' in dst:policy['destination']=dst['ip']
    if 'list' in dst:policy['destination_list']=dst['list']
    # Old source-only policies had implicit relative order. Make that order
    # explicit without altering existing ranks when introducing opaque lists.
    rank=max([priority]+[p.get('priority',0) for p in result['policies']])+10
    for p in ordered(result):
        if p['source'] and 'priority' not in p:p['priority']=rank;rank+=10
    result['policies'].append(policy)
    return validate(result)
