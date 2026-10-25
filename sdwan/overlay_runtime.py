"""One-time key preparation. Network/peer changes use protected deployment.

Only public WireGuard properties are ever requested from the RouterOS API.
"""
from .overlay import NAME,interface_name,public_key
from .deployment import read_state,TERMINAL

PROPERTIES='.id,name,public-key,listen-port,mtu,disabled,comment'
PREFIX='sdwan:v1:overlay:interface:'


def inventory(router):
    rows=router.call('interface/wireguard/print',{'.proplist':PROPERTIES},'POST')
    if not isinstance(rows,list) or len(rows)>256:raise ValueError('WireGuard inventory exceeds the bounded preparation budget')
    result=[]
    for row in rows:
        item={key:row[key] for key in PROPERTIES.split(',') if key in row}
        result.append(item)
    return result


def prepare_keys(router,requests,expected):
    """Create disabled owned interfaces only; return their public identities.

    No peers, addresses, routes, firewall or existing interface settings change.
    A caller can safely repeat preparation after exchanging only public keys.
    """
    if router.call('system/identity')['name']!=expected:raise ValueError('Router identity changed')
    state=read_state(router)
    if state and state.get('phase') not in TERMINAL:raise ValueError('Wait for the pending protected deployment before preparing keys')
    if not isinstance(requests,list) or not 1<=len(requests)<=16:raise ValueError('Prepare 1..16 tunnel identities at a time')
    names=set();ports=set()
    for request in requests:
        if not isinstance(request,dict) or not {'name','listen_port'}<=request.keys() or request.keys()-{'name','listen_port','mtu'}:raise ValueError('Key preparation accepts name, listen_port and optional mtu only')
        name=request['name'];port=request['listen_port'];mtu=request.get('mtu',1380)
        if not isinstance(name,str) or not NAME.fullmatch(name) or name in names:raise ValueError('Invalid/duplicate prepared tunnel name')
        if type(port) is not int or not 1024<=port<=65535 or port in ports:raise ValueError('Invalid/duplicate prepared listen port')
        if type(mtu) is not int or not 1280<=mtu<=1420:raise ValueError('Invalid prepared MTU')
        names.add(name);ports.add(port)
    existing=inventory(router)
    # Validate every collision before creating the first identity.
    for request in requests:
        name=interface_name(request);owned=PREFIX+request['name'];matching=[row for row in existing if row.get('name')==name]
        if len(matching)>1:raise ValueError('Ambiguous existing WireGuard interface')
        for row in matching:
            if row.get('comment')!=owned:raise ValueError('Foreign interface name collision: '+name)
            if int(row['listen-port'])!=request['listen_port'] or int(row['mtu'])!=request.get('mtu',1380):raise ValueError('Use protected installation to change existing tunnel settings: '+name)
            public_key(row['public-key'])
        if any(int(row['listen-port'])==request['listen_port'] and row.get('name')!=name for row in existing):raise ValueError('WireGuard listen port already belongs to another interface')
    created=[]
    try:
        for request in requests:
            name=interface_name(request)
            if any(row.get('name')==name for row in existing):continue
            # RouterOS generates the private key locally. Never supply or read it.
            row=router.call('interface/wireguard',{'name':name,'listen-port':str(request['listen_port']),'mtu':str(request.get('mtu',1380)),'disabled':'true','comment':PREFIX+request['name']},'PUT')
            created.append((row['.id'],name,PREFIX+request['name']))
        rows=inventory(router);result=[]
        for request in requests:
            matches=[row for row in rows if row.get('name')==interface_name(request) and row.get('comment')==PREFIX+request['name']]
            if len(matches)!=1:raise RuntimeError('Prepared identity changed during readback')
            row=matches[0];public_key(row['public-key'])
            result.append({'name':request['name'],'interface':row['name'],'listen_port':int(row['listen-port']),'mtu':int(row['mtu']),'public_key':row['public-key']})
        return result
    except Exception:
        # Remove only interfaces created by this call that are still untouched.
        rows=inventory(router)
        for identifier,name,comment in reversed(created):
            match=next((r for r in rows if r.get('.id')==identifier and r.get('name')==name and r.get('comment')==comment and r.get('disabled') in (True,'true','yes')),None)
            if match and not router.call('interface/wireguard/peers/print',{'.proplist':'.id','.query':['interface='+name]},'POST') and not router.call('ip/address/print',{'.proplist':'.id','.query':['interface='+name]},'POST'):
                router.call('interface/wireguard/'+identifier,method='DELETE')
        raise
