#!/usr/bin/env python3
"""Native NAT insertion regression on an explicitly named disposable CHR.

Exercises the real VPN/DNS functions and RouterOS firewall commands with empty
and populated NAT tables. VPN identity/restart and conntrack are isolated here;
the normal VPN cold-restart and traffic suites verify those dependencies.
Never target an existing overlay node or a production router.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sdwan.router import Router

TAG = 'sdwan-nat-regression'
POLICY = 'read,write,policy,test,sensitive'
SOURCE = r'''
/system/scheduler/disable [/system/scheduler/find where name="sdwan-nat-regression"]
:global sdwanNATRegressionJSON
:onerror failed in={
    /import file-name="nat-regression-vpn.rsc"
    /import file-name="nat-regression-dns.rsc"
    :global sdwanVPNBinding do={ :return {"id"="*0";"kind"=($spec->"vpn_type");"interface"=($spec->"interface");"listen_port"=51911;"endpoint"="198.18.100.1";"port"=1701;"protocol"="udp";"ipsec"="no"} }
    :global sdwanVPNRestart do={ :return true }
    :global sdwanConntrackFind do={ :return [:toarray ""] }
    :global sdwanVPNTransport
    :global sdwanState {"default/wan1"="healthy"}
    :global sdwanVPNTick
    :global sdwanDNSBootstrap
    :local results [:toarray ""]
    :foreach kind in={"wireguard";"l2tp";"dns"} do={
        :foreach populated in={false;true} do={
            /ip/firewall/nat/remove [/ip/firewall/nat/find]
            /ip/firewall/mangle/remove [/ip/firewall/mangle/find]
            /ip/route/remove [/ip/route/find where comment~"^sdwan:v1:"]
            :local sentinel ""
            :if ($populated) do={ :set sentinel [/ip/firewall/nat/add chain=srcnat src-address=192.0.2.1 action=accept comment="sdwan-nat-regression:sentinel"] }
            /ip/firewall/mangle/add chain=sdwan-output action=return comment="sdwan:v1:router-reply:wan1"
            :set sdwanVPNTransport [:toarray ""]
            :local physical {"name"="wan1";"kind"="static";"interface"="ether1";"address"="10.0.2.15";"route_gateway"="ether1";"probe_table"="sdwan-nat-regression";"ready"=true}
            :local vpn {"name"="vpn1";"kind"="vpn";"interface"="vpn-regression";"vpn_type"=$kind;"vpn_endpoint"="198.18.100.1";"underlays"={"wan1"};"ready"=true}
            :if ($kind = "dns") do={ :set ($vpn->"vpn_endpoint") "nat-regression.test" }
            :local wans [:toarray ""]
            :set ($wans->0) $physical
            :set ($wans->1) $vpn
            :local cfg {"wans"=$wans;"policies"={{"source"="";"profile"="default"}};"local_networks"={"10.0.2.0/24"};"overlay"={"enabled"=false}}
            :local ok true
            :local reason ""
            :local expected 1
            :local tag "sdwan:v1:vpn:transport:vpn1"
            :onerror rejected in={
                :if ($kind = "dns") do={
                    :set tag "sdwan:v1:dns-bootstrap"
                    :set expected 2
                    :local count [$sdwanDNSBootstrap cfg=$cfg force=true]
                    :if ($count != 1) do={ :error "DNS bootstrap did not install its resolver" }
                } else={
                    :local resolved [$sdwanVPNTick cfg=$cfg]
                    :if ((($sdwanVPNTransport->"vpn1")->"ready") != true) do={ :error "VPN transport was rejected" }
                }
                :local installed [/ip/firewall/nat/find where comment=$tag]
                :if ([:len $installed] != $expected) do={ :error "unexpected managed NAT count" }
                :local first [:pick [/ip/firewall/nat/find where dynamic=no] 0]
                :if ([/ip/firewall/nat/get $first comment] != $tag) do={ :error "managed NAT was not inserted first" }
                :if ($populated) do={
                    :if ([:pick [/ip/firewall/nat/find where dynamic=no] $expected] != $sentinel) do={ :error "existing NAT rule moved or replaced" }
                }
            } do={ :set ok false; :set reason $rejected }
            :set ($results->[:len $results]) {"kind"=$kind;"populated"=$populated;"pass"=$ok;"error"=$reason}
        }
    }
    /ip/firewall/nat/remove [/ip/firewall/nat/find]
    /ip/firewall/mangle/remove [/ip/firewall/mangle/find]
    /ip/route/remove [/ip/route/find where comment~"^sdwan:v1:"]
    :set sdwanNATRegressionJSON [:serialize to=json value=$results options=json.no-string-conversion]
} do={ :set sdwanNATRegressionJSON [:serialize to=json value={"error"=$failed} options=json.no-string-conversion] }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--router-url', required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--library-root', type=Path, default=ROOT)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    router = Router(ROOT, args.router_url, credentials=args.credentials)
    created = []
    files = []
    original_dns = None
    try:
        assert router.call('system/identity')['name'] == TAG, 'Requires the dedicated disposable CHR'
        assert router.call('system/resource')['version'].split()[0] == '7.24.5'
        for menu in ('ip/firewall/nat', 'ip/firewall/mangle', 'system/scheduler'):
            assert not router.call(menu+'/print', {'.proplist': '.id'}, 'POST'), 'Requires a virgin test router: '+menu
        assert not router.file_entry('sdwan-active.json'), 'Refuse an installed controller'
        original_dns = router.call('ip/dns/print', {'.proplist': 'servers,use-doh-server'}, 'POST')[0]
        router.call('ip/dns/set', {'servers': '198.18.0.53', 'use-doh-server': ''}, 'POST')
        table = router.call('routing/table/add', {'name': TAG, 'fib': 'yes'}, 'POST')['ret']
        created.append(('routing/table', table))
        for module in ('vpn', 'dns'):
            filename = 'nat-regression-'+module+'.rsc'
            assert not router.file_entry(filename)
            router.upload(filename, (args.library_root/'native'/('sdwan-'+module+'.rsc')).read_text())
            files.append(filename)
        for row in router.call('system/script/environment/print', {'.proplist': '.id', '.query': ['name=sdwanNATRegressionJSON']}, 'POST'):
            router.call('system/script/environment/'+row['.id'], method='DELETE')
        for menu, data in [('system/script', {'source': SOURCE}), ('system/scheduler', {'interval': '1s', 'on-event': '/system/script/run '+TAG})]:
            item = router.call(menu+'/add', dict(data, name=TAG, policy=POLICY, comment=TAG), 'POST')['ret']
            created.append((menu, item))
        end = time.monotonic()+30
        while time.monotonic() < end:
            rows = router.call('system/script/environment/print', {'.proplist': 'value', '.query': ['name=sdwanNATRegressionJSON']}, 'POST')
            if rows and rows[0].get('value', '').startswith(('[', '{')):
                break
            time.sleep(.2)
        else:
            raise AssertionError('Native NAT regression did not return a report')
        result = json.loads(rows[0]['value'])
        args.report.write_text(json.dumps(result, indent=2)+'\n')
        assert isinstance(result, list) and len(result) == 6, result
        assert all(row['pass'] for row in result), result
        print('PASS real RouterOS NAT insertion: empty/existing table, WireGuard/PPP/DNS (6 cases)')
    finally:
        for menu, item in reversed(created):
            router.call(menu+'/'+item, method='DELETE')
        for filename in files:
            row = router.file_entry(filename)
            if row:
                router.call('file/'+row['.id'], method='DELETE')
        if original_dns is not None:
            router.call('ip/dns/set', original_dns, 'POST')
        router.close()


if __name__ == '__main__':
    main()
