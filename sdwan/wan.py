"""Addressing contract for WANs; this module never mutates a router.

Dynamic address/gateway values belong to runtime state, not saved configuration.
Native execution lives in sdwan-links.rsc.
"""
import ipaddress

KINDS=('static','dhcp','pppoe','lte')


def addressing_kind(wan):
    kind=wan.get('kind','static')
    if kind not in KINDS:raise ValueError('WAN kind must be static, dhcp, pppoe or lte')
    if kind=='static':
        for field in ('address','gateway'):
            value=wan.get(field)
            if not isinstance(value,str) or not value:raise ValueError('Static WAN requires '+field)
            ip=ipaddress.IPv4Address(value)
            if ip.is_unspecified or ip.is_multicast or str(ip)=='255.255.255.255':raise ValueError('Invalid static WAN '+field)
        if wan['address']==wan['gateway']:raise ValueError('WAN address and gateway must differ')
    else:
        for field in ('address','gateway'):
            if field in wan and wan[field]!='':raise ValueError('Dynamic WAN '+field+' must not contain a lease snapshot')
    if kind=='lte':
        profile=wan.get('apn_profile')
        if not isinstance(profile,str) or not 1<=len(profile)<=64 or ',' in profile or any(ord(ch)<32 or ord(ch)==127 for ch in profile):raise ValueError('LTE requires one valid apn_profile name')
    elif wan.get('apn_profile') not in (None,''):raise ValueError('apn_profile is only valid for LTE')
    return kind


def inferred_kind(interface,dhcp_clients,pppoe_clients,lte_interfaces=()):
    def enabled(row):return row.get('disabled') not in (True,'true','yes','1')
    dhcp=[row for row in dhcp_clients if row.get('interface')==interface and enabled(row)]
    ppp=[row for row in pppoe_clients if row.get('name')==interface]
    lte=[row for row in lte_interfaces if row.get('name')==interface]
    if len(lte)>1 or (lte and (dhcp or ppp)):raise ValueError('Ambiguous native LTE addressing on '+interface)
    if lte:return 'lte'
    if len(dhcp)>1 or len(ppp)>1:raise ValueError('Multiple address clients on interface '+interface)
    if dhcp and ppp:raise ValueError('Both DHCP and PPPoE configured on logical interface '+interface)
    return 'pppoe' if ppp else ('dhcp' if dhcp else 'static')


def adopted_dynamic_route(route,wans):
    """Match provider routes by protocol/interface, never by an ephemeral ID."""
    def yes(value):return value in (True,'true','yes','1')
    if not yes(route.get('dynamic')):return False
    for wan in wans:
        iface=wan['interface'];kind=wan.get('kind','static')
        if kind=='dhcp' and yes(route.get('dhcp')) and route.get('vrf-interface')==iface:return True
        if kind=='pppoe' and route.get('gateway','').split('@')[0]==iface:return True
        if kind=='lte' and yes(route.get('modem')):
            gw=route.get('gateway','').split('@')[0]
            if gw==iface or gw.rsplit('%',1)[-1]==iface or route.get('vrf-interface')==iface:return True
    return False
