"""Isolated DHCP/PPPoE services on the existing CHR lab, without default routes."""
from contextlib import contextmanager
from pathlib import Path
import secrets
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lab


@contextmanager
def dynamic_wans(component_tables=True):
    resources=[]
    def add(node,menu,data):
        # REST requires a stable item ID; numeric CLI position 0 is not an API ID.
        if data.get('place-before')=='0':
            data=dict(data)
            existing=lab.api(node,menu)
            if existing:data['place-before']=existing[0]['.id']
            else:data.pop('place-before')
        row=lab.api(node,menu,data,'PUT');resources.append((node,menu,row['.id']))
        if menu.startswith('ip/firewall/'):
            end=time.monotonic()+5
            while lab.api(node,menu+'/'+row['.id']).get('invalid')=='true':
                if time.monotonic()>end:raise AssertionError('Fixture rule stayed invalid: '+node+'/'+menu)
                time.sleep(.1)
        return row['.id']
    for node in ('edge','isp2','isp3'):
        assert lab.api(node,'system/identity')['name']=='sdwan-'+node
    try:
        tag='dynamic-wan-acceptance-only'
        if component_tables:add('edge','routing/table',{'name':'sdwan-test-acquire','fib':'true'})
        add('isp2','ip/dhcp-server/option',{'name':'sdwan-test-classless','code':'121','value':'0x00ac1f0201'})
        add('edge','interface/vlan',{'name':'sdwan-test-dhcp-vlan','interface':'ether3','vlan-id':'992','comment':tag})
        add('isp2','interface/vlan',{'name':'sdwan-test-dhcp-vlan','interface':'ether2','vlan-id':'992','comment':tag})
        add('isp2','ip/firewall/filter',{'chain':'forward','in-interface':'sdwan-test-dhcp-vlan','out-interface':'ether1','action':'accept','src-address':'172.31.2.0/24','place-before':'0','comment':tag})
        add('isp3','ip/firewall/filter',{'chain':'forward','out-interface':'ether1','action':'accept','src-address':'172.31.3.0/24','place-before':'0','comment':tag})
        add('isp2','ip/address',{'address':'172.31.2.1/24','interface':'sdwan-test-dhcp-vlan','comment':tag})
        pool=add('isp2','ip/pool',{'name':'sdwan-test-dhcp-pool','ranges':'172.31.2.2-172.31.2.3'})
        network=add('isp2','ip/dhcp-server/network',{'address':'172.31.2.0/24','gateway':'172.31.2.1','comment':tag})
        server=add('isp2','ip/dhcp-server',{'name':'sdwan-test-dhcp','interface':'sdwan-test-dhcp-vlan','address-pool':'sdwan-test-dhcp-pool','lease-time':'1m','disabled':'false'})
        dhcp=add('edge','ip/dhcp-client',{'interface':'sdwan-test-dhcp-vlan','add-default-route':'no','use-peer-dns':'no','use-peer-ntp':'no','disabled':'false','comment':tag})
        password=secrets.token_urlsafe(24)
        profile=add('isp3','ppp/profile',{'name':'sdwan-test-ppp-profile','local-address':'172.31.3.1','remote-address':'172.31.3.2'})
        secret=add('isp3','ppp/secret',{'name':'sdwan-test-ppp-user','password':password,'service':'pppoe','profile':'sdwan-test-ppp-profile'})
        ppp_server=add('isp3','interface/pppoe-server/server',{'interface':'ether2','service-name':'sdwan-test','default-profile':'sdwan-test-ppp-profile','authentication':'pap','disabled':'false'})
        ppp=add('edge','interface/pppoe-client',{'name':'sdwan-test-pppoe','interface':'ether4','service-name':'sdwan-test','user':'sdwan-test-ppp-user','password':password,'add-default-route':'no','use-peer-dns':'no','allow':'pap','disabled':'false'})
        end=time.monotonic()+30
        while time.monotonic()<end:
            d=lab.api('edge','ip/dhcp-client/'+dhcp)
            p=next(x for x in lab.api('edge','interface') if x['name']=='sdwan-test-pppoe')
            if d.get('status')=='bound' and p.get('running')=='true':break
            time.sleep(.3)
        else:raise AssertionError('Lab DHCP lease or PPPoE session did not establish')
        yield {'dhcp':dhcp,'dhcp_server':server,'dhcp_network':network,'dhcp_pool':pool,'pppoe':ppp,'pppoe_server':ppp_server,'ppp_profile':profile,'ppp_secret':secret,'add':add}
    finally:
        for node,menu,identifier in reversed(resources):
            try:lab.api(node,menu+'/'+identifier,method='DELETE')
            except RuntimeError as error:
                if ': 404 ' not in str(error):raise
