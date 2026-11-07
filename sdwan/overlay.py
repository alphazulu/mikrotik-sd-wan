"""IPv4 branch-overlay contract. Private WireGuard keys never belong in JSON."""
import base64
import ipaddress
import re

NAME=re.compile(r'[a-z][a-z0-9_-]{0,19}\Z')
HEALTH_DEFAULTS={'interval_seconds':2,'timeout_ms':500,'packet_count':3,'packet_interval_ms':100,'fail_windows':2,'recover_windows':3,'hold_down_seconds':6,'stale_seconds':10,'rtt_ms':150,'jitter_ms':50,'loss_percent':20}


def _need(condition,message):
    if not condition:raise ValueError('overlay: '+message)


def _keys(value,required,optional=()):
    _need(isinstance(value,dict),'settings must be an object')
    _need(not set(required)-value.keys(),'missing fields '+str(sorted(set(required)-value.keys())))
    _need(not value.keys()-set(required)-set(optional),'unknown fields '+str(sorted(value.keys()-set(required)-set(optional))))


def _integer(value,low,high,label):
    _need(type(value) is int and low<=value<=high,f'{label} must be {low}..{high}')


def _ip(raw):
    _need(isinstance(raw,str),'IPv4 address must be text')
    try:value=ipaddress.IPv4Address(raw)
    except ValueError:raise ValueError('overlay: invalid IPv4 address') from None
    _need(str(value)==raw and not (value.is_unspecified or value.is_multicast or value.is_loopback or value.is_link_local or value==ipaddress.IPv4Address('255.255.255.255')),'invalid unicast IPv4 address')
    return value


def _prefixes(values,label,allow_empty=False):
    _need(isinstance(values,list) and (0 if allow_empty else 1)<=len(values)<=64,label+' must contain 1..64 canonical IPv4 prefixes')
    parsed=[]
    for raw in values:
        _need(isinstance(raw,str),label+' prefixes must be text')
        try:net=ipaddress.IPv4Network(raw,strict=True)
        except ValueError:raise ValueError('overlay: invalid canonical IPv4 prefix') from None
        _need(str(net)==raw and net.prefixlen>0 and not any(net.overlaps(ipaddress.IPv4Network(p)) for p in ('0.0.0.0/8','127.0.0.0/8','169.254.0.0/16','224.0.0.0/3')),label+' contains a forbidden prefix')
        _need(not any(net.overlaps(other) for other in parsed),label+' contains duplicate/overlapping prefixes')
        parsed.append(net)
    return parsed


def public_key(value):
    _need(isinstance(value,str),'public key must be base64 text')
    try:decoded=base64.b64decode(value,validate=True)
    except (ValueError,TypeError):raise ValueError('overlay: invalid base64 public key') from None
    _need(len(decoded)==32 and any(decoded) and base64.b64encode(decoded).decode()==value,'public key must contain a canonical, nonzero 32-byte value')
    return value


def enabled(cfg):return cfg.get('overlay',{}).get('enabled',False)


def health(cfg):return dict(HEALTH_DEFAULTS,**cfg.get('overlay',{}).get('health',{}))


def interface_name(tunnel):return 'sdwan-wg-'+tunnel['name']


def probe_table(tunnel):return 'sdwan-ol-'+tunnel['name']


def effective_networks(cfg):
    networks=list(cfg['local_networks'])
    if enabled(cfg):
        overlay=cfg['overlay'];networks+=overlay['local_prefixes']+overlay['remote_prefixes']
        networks += [str(ipaddress.IPv4Interface(t['address']).network) for t in overlay['tunnels']]
    return list(dict.fromkeys(networks))


def validate(cfg):
    if 'overlay' not in cfg:return cfg
    overlay=cfg['overlay'];_keys(overlay,('enabled',),('role','router_id','local_prefixes','remote_prefixes','tunnels','mtu','mss_clamp','health'))
    _need(type(overlay['enabled']) is bool,'enabled must be boolean')
    if not overlay['enabled']:
        _need(set(overlay)=={'enabled'},'disabled overlay must contain only enabled=false; store unfinished topology in a project file')
        return cfg
    _keys(overlay,('enabled','role','router_id','local_prefixes','remote_prefixes','tunnels'),('mtu','mss_clamp','health'))
    role=overlay['role'];_need(role in ('site','hub'),'role must be site or hub');_ip(overlay['router_id'])
    _integer(overlay.get('mtu',1380),1280,1420,'mtu');_need(type(overlay.get('mss_clamp',False)) is bool,'mss_clamp must be boolean')
    local=_prefixes(overlay['local_prefixes'],'local_prefixes',allow_empty=role=='hub');remote=_prefixes(overlay['remote_prefixes'],'remote_prefixes')
    _need(not any(a.overlaps(b) for a in local for b in remote),'local and remote prefixes overlap')
    h=overlay.get('health',{});_keys(h,(),HEALTH_DEFAULTS.keys());h=health(cfg)
    for field,low,high in [('interval_seconds',1,60),('timeout_ms',100,2000),('packet_count',2,20),('packet_interval_ms',10,500),('fail_windows',1,10),('recover_windows',1,20),('hold_down_seconds',0,300),('stale_seconds',2,300),('rtt_ms',1,5000),('jitter_ms',1,5000),('loss_percent',0,99)]:_integer(h[field],low,high,field)
    _need((h['packet_count']-1)*h['packet_interval_ms']+h['timeout_ms']<h['interval_seconds']*1000,'inner ICMP train does not fit the interval')
    _need(h['stale_seconds']>=2*h['interval_seconds'],'stale_seconds must cover two inner intervals')
    tunnels=overlay['tunnels'];_need(isinstance(tunnels,list) and 1<=len(tunnels)<=16,'1..16 independent tunnels required')
    wan_names={w['name'] for w in cfg['wans']};names=set();ports=set();subnets=[];keys=set()
    other_tables={w['probe_table'] for w in cfg['wans']}|{p['table'] for p in cfg['policies']}
    for tunnel in tunnels:
        _keys(tunnel,('name','wan','listen_port','address','peer_address','local_public_key','peer_public_key','peer_prefixes','cost'),('endpoint','endpoint_port','keepalive_seconds'))
        name=tunnel['name'];_need(isinstance(name,str) and NAME.fullmatch(name) and name not in names,'invalid/duplicate tunnel name');names.add(name)
        _need(probe_table(tunnel) not in other_tables,'overlay table collides with policy or WAN probe table')
        _need(isinstance(tunnel['wan'],str) and tunnel['wan'] in wan_names,'unknown underlay WAN')
        _need(next(w for w in cfg['wans'] if w['name']==tunnel['wan']).get('kind','static')!='vpn','overlay requires a physical underlay WAN')
        _integer(tunnel['listen_port'],1024,65535,'listen_port');_need(tunnel['listen_port'] not in ports,'duplicate local WireGuard listen port');ports.add(tunnel['listen_port'])
        try:address=ipaddress.IPv4Interface(tunnel['address'])
        except (ValueError,TypeError):raise ValueError('overlay: invalid tunnel IPv4 interface') from None
        _need(str(address)==tunnel['address'] and address.network.prefixlen in (30,31),'tunnel address must be canonical /30 or /31')
        local_ip=_ip(str(address.ip));peer=_ip(tunnel['peer_address']);net=address.network
        _need(peer in net and peer!=local_ip and (net.prefixlen==31 or (local_ip not in (net.network_address,net.broadcast_address) and peer not in (net.network_address,net.broadcast_address))),'peer must be the other usable address on its tunnel subnet')
        _need(not any(net.overlaps(n) for n in local+remote+subnets),'tunnel subnet overlaps site prefixes or another tunnel');subnets.append(net)
        own=public_key(tunnel['local_public_key']);other=public_key(tunnel['peer_public_key']);_need(own!=other,'local and peer public keys must differ')
        _need(own not in keys,'each tunnel requires its own local WireGuard identity');keys.add(own)
        peer_prefixes=_prefixes(tunnel['peer_prefixes'],'peer_prefixes');_need(all(any(n.subnet_of(r) for r in remote) for n in peer_prefixes),'peer prefixes must be covered by declared remote prefixes')
        _integer(tunnel['cost'],1,65535,'cost')
        if role=='site':
            endpoint=tunnel.get('endpoint');_need(isinstance(endpoint,str) and 1<=len(endpoint)<=253,'site requires a reachable public hub endpoint')
            try:endpoint_ip=ipaddress.IPv4Address(endpoint)
            except ValueError:
                _need(bool(re.fullmatch(r'(?=.{1,253}\Z)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',endpoint)) and ':' not in endpoint and '..' not in endpoint,'invalid hub endpoint hostname');endpoint_ip=None
            if endpoint_ip is not None:_ip(endpoint)
            _integer(tunnel.get('endpoint_port'),1024,65535,'endpoint_port');_integer(tunnel.get('keepalive_seconds',25),10,60,'keepalive_seconds')
        else:
            _need('endpoint' not in tunnel and 'endpoint_port' not in tunnel,'hub is responder-only; endpoints belong on CGNAT sites')
            _integer(tunnel.get('keepalive_seconds',0),0,0,'hub keepalive_seconds')
    for tunnel in tunnels:
        endpoint=tunnel.get('endpoint','')
        try:ip=ipaddress.IPv4Address(endpoint)
        except ValueError:continue
        _need(not any(ip in n for n in local+remote+subnets),'hub endpoint would recurse into the overlay')
    for wan in cfg['wans']:
        _need(wan['interface'] not in {interface_name(t) for t in tunnels},'owned overlay interface cannot be an underlay WAN')
        if wan.get('kind','static')=='static':_need(not any(ipaddress.IPv4Address(wan['address']) in n for n in local+remote+subnets),'site/tunnel prefix overlaps an underlay WAN address')
    return cfg
