"""Desired native mangle objects, for review/plan only; RouterOS installs them."""


from .policies import ordered


def objects(c):
    result={}
    def add(tag,chain,action,**fields):
        result[('ip/firewall/mangle','sdwan:v1:'+tag)]={'chain':chain,'action':action,**fields}
    for w in c['wans']:
        name=w['name'];table=w['probe_table']
        result[('ip/route','sdwan:v1:pin-blackhole:'+name)]={'dst-address':'0.0.0.0/0','routing-table':table,'blackhole':'true','distance':'254'}
        add('in:'+name,'sdwan-pre','mark-connection',**{'in-interface':w['interface'],'connection-state':'new','connection-mark':'no-mark','new-connection-mark':'sdwan-in-'+name,'passthrough':'true'})
        add('wan-return:'+name,'sdwan-pre','return',**{'in-interface':w['interface']})
    from .overlay import effective_networks
    for network in effective_networks(c):
        result[('ip/firewall/address-list','sdwan:v1:local-address:'+network)]={'list':'sdwan-local','address':network}
    for chain in ('sdwan-pre','sdwan-output'):
        add('local-router:'+chain,chain,'return',**{'dst-address-type':'local'})
        add('local-net:'+chain,chain,'return',**{'dst-address-list':'sdwan-local'})
        for w in c['wans']:
            add('reply:'+chain+':'+w['name'],chain,'mark-routing',**{'connection-mark':'sdwan-in-'+w['name'],'new-routing-mark':w['probe_table'],'passthrough':'false'})
    for group,members in c.get('groups',{}).items():
        for index,member in enumerate(members):
            result[('ip/firewall/address-list',f'sdwan:v1:group:{group}:{index}') ]={'list':'sdwan-group-'+group,'address':member}
    for p in ordered(c):
        selectors={'src-address':p['source'] or '0.0.0.0/0'}
        for field,native in [('source_group','src-address-list'),('source_list','src-address-list'),('destination','dst-address'),('destination_group','dst-address-list'),('destination_list','dst-address-list'),('in_interface','in-interface'),('src_ports','src-port'),('dst_ports','dst-port')]:
            if p.get(field):selectors[native]=('sdwan-group-' if field.endswith('_group') else '')+p[field]
        if p.get('protocol','any')!='any':selectors['protocol']=p['protocol']
        if p['source']:
            result[('ip/route','sdwan:v1:policy-blackhole:'+p['name'])]={'dst-address':'0.0.0.0/0','routing-table':p['table'],'blackhole':'true','distance':'254'}
        chain='sdwan-p-'+p['name']
        add('policy-jump:'+p['name'],'sdwan-pre','jump',**selectors,**{'connection-mark':'no-mark','connection-state':'established,related,new','jump-target':chain})
        for name in p['wans']:
            add('classify:'+p['name']+':'+name,chain,'mark-connection',**{'connection-state':'established,related,new','connection-mark':'no-mark','new-connection-mark':'sdwan-out-'+p['name']+':'+name,'passthrough':'true'})
        add('guard:'+p['name'],chain,'mark-routing',**{'connection-mark':'no-mark','new-routing-mark':p['table'],'passthrough':'false'})
        from .vpn_egress import wan_flag
        for name in p['wans']:
            wan=next(w for w in c['wans'] if w['name']==name);fields={'out-interface':wan['interface'],'connection-mark':'sdwan-out-'+p['name']+':'+name};tag='sdwan:v1:egress:'+p['name']+':'+name
            if wan_flag(c,wan,'masquerade'):result['ip/firewall/nat',tag]={'chain':'srcnat','action':'masquerade',**fields}
            if wan_flag(c,wan,'allow_selected_forward'):result['ip/firewall/filter',tag]={'chain':'forward','action':'accept','connection-state':'new,established,related',**fields}
    for p in c['policies']:
        for name in p['wans']:
            table=next(w['probe_table'] for w in c['wans'] if w['name']==name)
            for chain in ('sdwan-pre','sdwan-output'):
                add('flow:'+chain+':'+p['name']+':'+name,chain,'mark-routing',**{'connection-mark':'sdwan-out-'+p['name']+':'+name,'new-routing-mark':table,'passthrough':'false'})
    for w in c['wans']:
        targets=sorted({w['icmp_target']}|{p['dns_server'] if p['type']=='dns' else p['host'] for p in w['probes']})
        for index,target in enumerate(targets):
            result[('ip/firewall/address-list',f'sdwan:v1:probe-address:{w["name"]}:{index}') ]={'list':'sdwan-probes-'+w['name'],'address':target}
        for previous in ('no-mark','sdwan-router-'+w['name']):
            source={'src-address':w['address']+'/32'} if w.get('kind','static')=='static' else {}
            add('probe-classify:'+w['name']+':'+previous,'sdwan-output','mark-connection',**source,**{'dst-address-list':'sdwan-probes-'+w['name'],'connection-mark':previous,'new-connection-mark':'sdwan-probe-'+w['name'],'passthrough':'true'})
        add('probe-route:'+w['name'],'sdwan-output','mark-routing',**{'connection-mark':'sdwan-probe-'+w['name'],'new-routing-mark':w['probe_table'],'passthrough':'false'})
    for w in c['wans']:
        add('router-reply:'+w['name'],'sdwan-output','mark-routing',**{'connection-mark':'sdwan-router-'+w['name'],'new-routing-mark':w['probe_table'],'passthrough':'false'})
        source={'src-address':w['address']+'/32'} if w.get('kind','static')=='static' else {}
        add('source:'+w['name'],'sdwan-output','mark-routing',**source,**{'new-routing-mark':w['probe_table'],'passthrough':'false'})
        add('router-origin:'+w['name'],'sdwan-post','mark-connection',**{'src-address-type':'local','out-interface':w['interface'],'connection-mark':'no-mark','new-connection-mark':'sdwan-router-'+w['name'],'passthrough':'true'})
    for chain,target in [('prerouting','sdwan-pre'),('output','sdwan-output'),('postrouting','sdwan-post')]:
        add('jump:'+chain,chain,'jump',**{'jump-target':target})
    return result
