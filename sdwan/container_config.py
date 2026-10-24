"""Public container settings; credentials are deliberately absent from JSON."""
import ipaddress
import re

DEFAULTS={'subnet':'172.31.255.0/30','storage':'sdwan-container',
          'image_file':'sdwan-controller-amd64.tar','poll_ms':1000,
          'memory_max_bytes':16777216}
BRIDGE='sdwan-container-mgmt'
VETH='sdwan-container-veth'
NAME='sdwan-container-controller'
USER='sdwan-container'
HEARTBEAT_PORT=45999
PATH=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.\-/]{0,190}$')

def settings(config):
    return dict(DEFAULTS,**config.get('container',{}))

TELEMETRY_DEFAULTS={'enabled':False,'sample_seconds':10,'history_points':360,
                    'port':8080,'allowed_sources':[],'allowed_interfaces':[]}

def telemetry(config):
    return dict(TELEMETRY_DEFAULTS,**config.get('container',{}).get('telemetry',{}))

def validate_telemetry(config):
    supplied=config.get('container',{}).get('telemetry',{})
    if not isinstance(supplied,dict) or set(supplied)-set(TELEMETRY_DEFAULTS):raise ValueError('Unknown container.telemetry settings')
    cfg=telemetry(config)
    if type(cfg['enabled']) is not bool:raise ValueError('container.telemetry.enabled must be boolean')
    for field,low,high in [('sample_seconds',5,60),('history_points',12,600),('port',1024,65535)]:
        if type(cfg[field]) is not int or not low<=cfg[field]<=high:raise ValueError('Invalid container.telemetry.'+field)
    private=[ipaddress.IPv4Network(s) for s in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
    sources=cfg['allowed_sources'];interfaces=cfg['allowed_interfaces']
    for field,values in [('allowed_sources',sources),('allowed_interfaces',interfaces)]:
        if not isinstance(values,list) or len(values)>16 or any(not isinstance(v,str) or not v for v in values) or len(set(values))!=len(values):raise ValueError('Invalid container.telemetry.'+field)
    for value in sources:
        try:network=ipaddress.IPv4Network(value,strict=True)
        except (ValueError,TypeError):raise ValueError('Web allowed_sources require canonical private IPv4 CIDRs') from None
        if str(network)!=value:raise ValueError('Web allowed_sources require canonical address/prefix CIDRs')
        if not any(network.subnet_of(p) for p in private):raise ValueError('Web sources must stay within RFC1918 networks')
        if cfg['enabled'] and not any(network.subnet_of(ipaddress.IPv4Network(n)) for n in config.get('local_networks',[])):raise ValueError('Add web allowed_sources to local_networks before enabling telemetry')
    wan_interfaces={w.get('interface') for w in config.get('wans',[]) if isinstance(w,dict)}
    if any(len(i.encode())>255 or any(ord(c)<32 for c in i) or i in wan_interfaces|{BRIDGE,VETH} for i in interfaces):raise ValueError('Web allowed_interfaces must be explicit LAN interfaces, never WAN or container interfaces')
    if cfg['enabled'] and (config.get('controller_backend')!='container' or not sources or not interfaces):raise ValueError('Enabled telemetry requires container backend and explicit LAN sources/interfaces')

def addresses(config):
    network=ipaddress.IPv4Network(settings(config)['subnet'])
    return network,str(network.network_address+1),str(network.network_address+2)

def validate_backend(config):
    backend=config.get('controller_backend','routeros')
    if backend not in ('routeros','container'):raise ValueError('controller_backend must be routeros or container')
    supplied=config.get('container',{})
    if not isinstance(supplied,dict) or set(supplied)-set(DEFAULTS)-{'telemetry'}:raise ValueError('Unknown container settings; credentials must be kept in separate mounted files')
    validate_telemetry(config)
    cfg=settings(config)
    try:network=ipaddress.IPv4Network(cfg['subnet'],strict=True)
    except (ValueError,TypeError):raise ValueError('container.subnet must be a private IPv4 /30') from None
    private=(ipaddress.IPv4Network('10.0.0.0/8'),ipaddress.IPv4Network('172.16.0.0/12'),ipaddress.IPv4Network('192.168.0.0/16'))
    if network.prefixlen!=30 or not any(network.subnet_of(p) for p in private):raise ValueError('container.subnet must be a private IPv4 /30')
    for field in ('storage','image_file'):
        value=cfg[field]
        if not isinstance(value,str) or not PATH.fullmatch(value) or any(part in ('','..','.') for part in value.split('/')):raise ValueError('Invalid container.'+field+' RouterOS path')
    if not cfg['image_file'].endswith(('.tar','.tar.gz')):raise ValueError('container.image_file must be a tar or tar.gz archive already uploaded to RouterOS')
    if type(cfg['poll_ms']) is not int or not 500<=cfg['poll_ms']<=2000:raise ValueError('container.poll_ms must be 500..2000 for the 6-second heartbeat lease')
    if type(cfg['memory_max_bytes']) is not int or not 8388608<=cfg['memory_max_bytes']<=67108864:raise ValueError('container.memory_max_bytes must be 8..64 MiB')
    if backend=='container':
        # Requiring the explicit bypass avoids silently changing local routing.
        networks=config.get('local_networks',[])
        if not any(network.subnet_of(ipaddress.IPv4Network(item)) for item in networks):raise ValueError('Add container.subnet to local_networks so API replies bypass WAN policy routing')

