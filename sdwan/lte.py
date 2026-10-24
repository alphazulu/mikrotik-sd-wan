"""Read-only native LTE/APN contract. Never treats LTE as an IP DHCP client.

The full LTE installer/controller integration is separate. Only allowlisted
routing metadata is returned; APN credentials and SIM parameters stay on RouterOS.
"""


def profile_names(radio):
    """7.24 uses apn-profiles; newer RouterOS also exposes apn-profile."""
    raw=radio.get('apn-profile') or radio.get('apn-profiles') or ''
    if isinstance(raw,(list,tuple)):return [str(x).strip() for x in raw if str(x).strip()]
    return [name.strip() for name in str(raw).split(',') if name.strip()]


def apn_binding(interface,lte_interfaces,apn_profiles,*,expected_profile=None,managed_interfaces=()):
    """Validate one routed IPv4 APN, including shared-profile ownership.

    A profile shared with any unselected modem is rejected before mutation.
    Multi-APN and passthrough need separate per-session routing and are not
    silently flattened into one source address or fake DHCP client.
    """
    radios=[row for row in lte_interfaces if row.get('name')==interface]
    if len(radios)!=1:raise ValueError('Missing or ambiguous native LTE interface: '+interface)
    profiles=profile_names(radios[0])
    if len(profiles)!=1:raise ValueError('LTE requires exactly one APN profile: '+interface)
    name=profiles[0]
    if expected_profile is not None and expected_profile!=name:raise ValueError('LTE APN profile changed; reconnect and regenerate: '+interface)
    matching=[row for row in apn_profiles if row.get('name')==name]
    if len(matching)!=1:raise ValueError('Missing or ambiguous LTE APN profile: '+name)
    apn=matching[0]
    passthrough=str(apn.get('passthrough-interface') or '').strip()
    if passthrough not in ('','none'):raise ValueError('LTE passthrough is not a routed WAN on this router: '+interface)
    if apn.get('ip-type','auto') not in ('auto','ipv4','ipv4-ipv6'):raise ValueError('LTE APN does not provide IPv4: '+name)
    route_mode=apn.get('add-default-route')
    if not (route_mode is True or route_mode is False or (isinstance(route_mode,str) and route_mode in ('true','false','yes','no','1','0'))):
        raise ValueError('LTE APN automatic-route setting is unavailable: '+name)
    managed=set(managed_interfaces)|{interface}
    unselected=[row['name'] for row in lte_interfaces if row.get('name') not in managed and name in profile_names(row)]
    if unselected:raise ValueError('LTE APN shared with unselected modems; assign a separate profile: '+name+' ('+', '.join(unselected)+')')
    return {'interface':interface,'apn_profile':name,'apn_id':apn.get('.id',''),
            'add_default_route':apn.get('add-default-route'),
            'default_route_distance':apn.get('default-route-distance'),
            'ip_type':apn.get('ip-type','auto')}
