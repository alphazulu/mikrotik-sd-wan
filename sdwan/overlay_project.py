"""Local overlay editor and bounded PUBLIC key exchange; no router control loop."""
import copy
import json
from .overlay import NAME,interface_name,public_key

FIELDS={'name','interface','listen_port','mtu','public_key'}

def exchange(identity,identities):
    if not isinstance(identity,str) or not 1<=len(identity)<=64 or any(ord(c)<32 or ord(c)==127 for c in identity):raise ValueError('Invalid public exchange router identity')
    if not isinstance(identities,list) or not 1<=len(identities)<=16:raise ValueError('Exchange requires 1..16 public identities')
    result=[];names=set();ports=set();keys=set()
    for row in identities:
        if not isinstance(row,dict) or row.keys()!=FIELDS:raise ValueError('Exchange accepts public identity fields only; no credentials/private keys')
        name=row['name'];port=row['listen_port'];mtu=row['mtu'];key=public_key(row['public_key'])
        if not isinstance(name,str) or not NAME.fullmatch(name) or name in names:raise ValueError('Invalid/duplicate public tunnel name')
        if row['interface']!=interface_name(row):raise ValueError('Public interface name does not match tunnel name')
        if type(port) is not int or not 1024<=port<=65535 or port in ports:raise ValueError('Invalid/duplicate public listen port')
        if type(mtu) is not int or not 1280<=mtu<=1420 or key in keys:raise ValueError('Invalid MTU or duplicate public identity')
        names.add(name);ports.add(port);keys.add(key);result.append(dict(row))
    return {'schema_version':1,'router':identity,'identities':result}

def decode_exchange(text):
    if not isinstance(text,str) or len(text.encode('utf-8'))>32768:raise ValueError('Public exchange exceeds 32 KiB')
    value=json.loads(text)
    if not isinstance(value,dict) or value.keys()!={'schema_version','router','identities'} or type(value['schema_version']) is not int or value['schema_version']!=1:raise ValueError('Unsupported public exchange format')
    return exchange(value['router'],value['identities'])

def with_local_keys(tunnels,identities,mtu):
    """Bind readback to the exact requested local names/ports/MTU, never index order."""
    rows={r['name']:r for r in exchange('local',identities)['identities']};result=copy.deepcopy(tunnels)
    if len(result)!=len(rows) or {t['name'] for t in result}!=rows.keys():raise ValueError('Prepared identities do not match the current draft')
    for tunnel in result:
        row=rows[tunnel['name']]
        if tunnel['listen_port']!=row['listen_port'] or mtu!=row['mtu']:raise ValueError('Draft port/MTU changed during key preparation')
        tunnel['local_public_key']=row['public_key']
    return result

def configure(cfg,overlay):
    from .config import validate
    result=copy.deepcopy(cfg);result['overlay']=copy.deepcopy(overlay) if overlay.get('enabled') else {'enabled':False}
    return validate(result)
