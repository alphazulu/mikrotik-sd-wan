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

def addresses(config):
    network=ipaddress.IPv4Network(settings(config)['subnet'])
    return network,str(network.network_address+1),str(network.network_address+2)

def validate_backend(config):
    backend=config.get('controller_backend','routeros')
    if backend not in ('routeros','container'):raise ValueError('controller_backend must be routeros or container')
    supplied=config.get('container',{})
    if not isinstance(supplied,dict) or set(supplied)-set(DEFAULTS):raise ValueError('Unknown container settings; credentials must be kept in separate mounted files')
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

