# A DNS socket needs an initial main route before output mangle is evaluated.
# Only configured resolver/DoH IPv4 hosts receive a low-priority /32 bootstrap.
# Unadmitted client flows are dropped by their policy child-chain guard first.
:global sdwanDNSBootstrap do={
    :global sdwanDNSBootstrapSignature
    :global sdwanState
    :global sdwanDNSDoHCache
    :local now ([:tonsec [/system/resource/get uptime]] / 1000000000)
    :local forced false
    :if ([:typeof $force] = "bool") do={ :set forced $force }
    :local parents [:toarray ""]
    :foreach w in=($cfg->"wans") do={
        :if ((($w->"kind") = "vpn") && ([:typeof [:toip ($w->"vpn_endpoint")]] != "ip")) do={ :foreach parentName in=($w->"underlays") do={ :set ($parents->$parentName) true } }
    }
    :local overlay ($cfg->"overlay")
    :if (($overlay->"enabled") = true) do={ :foreach tunnel in=($overlay->"tunnels") do={ :if (([:len [:tostr ($tunnel->"endpoint")]] > 0) && ([:typeof [:toip ($tunnel->"endpoint")]] != "ip")) do={ :set ($parents->($tunnel->"wan")) true } } }
    :local physicalProfile ""
    :foreach policy in=($cfg->"policies") do={ :if (($policy->"source") = "") do={ :set physicalProfile ($policy->"profile") } }
    :local parent [:toarray ""]
    :local candidate [:toarray ""]
    :foreach w in=($cfg->"wans") do={
        :local admin [:tostr ($w->"admin_state")]
        :if ((($parents->($w->"name")) = true) && (($w->"kind") != "vpn") && (($w->"ready") = true) && (($admin = "") || ($admin = "enabled"))) do={
            :if ([:len $candidate] = 0) do={ :set candidate $w }
            :if (([:len $parent] = 0) && (($sdwanState->($physicalProfile . "/" . ($w->"name"))) = "healthy")) do={ :set parent $w }
        }
    }
    :if ([:len $parent] = 0) do={ :set parent $candidate }
    :local targets [:toarray ""]
    :if ([:len $parent] > 0) do={
        :foreach server in=([/ip/dns/get servers],[/ip/dns/get dynamic-servers]) do={
            # Explicit @vrf, IPv6 and non-address servers retain operator routing.
            :local ip [:toip [:tostr $server]]
            :if (([:typeof $ip] = "ip") && ($ip > 0.0.0.0) && ($ip < 224.0.0.0)) do={ :set ($targets->[:tostr $ip]) "53" }
        }
        # Observe DoH bootstrap A/CNAME cache; never perform a blocking resolver
        # call, replace its URL/certificate settings, or persist a new DNS list.
        :local doh [/ip/dns/get use-doh-server]
        :local dohTargets [:toarray ""]
        :if ([:pick $doh 0 8] = "https://") do={
            :local pathStart [:find $doh "/" 8]
            :if ([:typeof $pathStart] = "nil") do={ :set pathStart [:len $doh] }
            :local authority [:pick $doh 8 $pathStart]
            :local port "443"
            :local colon [:find $authority ":"]
            :if ([:typeof $colon] != "nil") do={ :set port [:pick $authority ($colon + 1) [:len $authority]]; :set authority [:pick $authority 0 $colon] }
            :local portNumber [:tonum $port]
            :if (([:typeof $portNumber] = "num") && ($portNumber > 0) && ($portNumber < 65536)) do={
                :local host $authority
                :for hop from=0 to=4 do={
                    :if ($host != "") do={
                    :local ip [:toip $host]
                    :if ([:typeof $ip] = "ip") do={ :set ($dohTargets->[:tostr $ip]) ("53," . $port); :set host "" } else={
                        :local aliases [/ip/dns/cache/find where name=$host and type="CNAME"]
                        :local records [/ip/dns/cache/find where name=$host and type="A"]
                        :if ([:len $records] <= 32) do={ :foreach id in=$records do={ :local cachedIP [:toip [/ip/dns/cache/get $id data]]; :if ([:typeof $cachedIP] = "ip") do={ :set ($dohTargets->[:tostr $cachedIP]) ("53," . $port) } } }
                        :if ([:len $aliases] = 1) do={ :set host [:tostr [/ip/dns/cache/get $aliases data]] } else={ :set host "" }
                    }
                    }
                }
            }
        }
        # A cache TTL shorter than the DoH retry period must not remove the
        # initial route between resolution and the next HTTPS attempt. Retain
        # last observed addresses in RAM for at most 60s, replacing them as soon
        # as fresh A data arrives; a URL change never inherits another host.
        :if ([:len $dohTargets] > 32) do={ :set dohTargets [:toarray ""]; :set sdwanDNSDoHCache [:toarray ""] }
        :if ([:len $dohTargets] > 0) do={
            :set sdwanDNSDoHCache {"url"=$doh;"observed_at"=$now;"addresses"=$dohTargets}
        } else={
            :local observed ($sdwanDNSDoHCache->"observed_at")
            :if (([:typeof $observed] = "num") && (($sdwanDNSDoHCache->"url") = $doh) && (($now - $observed) >= 0) && (($now - $observed) <= 60)) do={ :set dohTargets ($sdwanDNSDoHCache->"addresses") } else={ :set sdwanDNSDoHCache [:toarray ""] }
        }
        :foreach addressText,ports in=$dohTargets do={ :set ($targets->$addressText) $ports }
    }
    :local localNetworks ($cfg->"local_networks")
    :if (($overlay->"enabled") = true) do={ :set localNetworks ($localNetworks,($overlay->"local_prefixes"),($overlay->"remote_prefixes")); :foreach tunnel in=($overlay->"tunnels") do={ :set localNetworks ($localNetworks,($tunnel->"address")) } }
    :local external [:toarray ""]
    :foreach resolverIPText,ports in=$targets do={
        :local ip [:toip $resolverIPText]
        :local localTarget (($ip < 1.0.0.0) || ($ip >= 224.0.0.0) || (($ip >= 127.0.0.0) && ($ip < 128.0.0.0)) || ([:len [/ip/address/find where address~("^" . $resolverIPText . "/")]] > 0))
        :foreach network in=$localNetworks do={
            :local slash [:find $network "/"]
            :local mask (255.255.255.255 << (32 - [:tonum [:pick $network ($slash + 1) [:len $network]]]))
            :if (($ip & $mask) = ([:toip [:pick $network 0 $slash]] & $mask)) do={ :set localTarget true }
        }
        :if (!$localTarget) do={ :set ($external->$resolverIPText) $ports }
    }
    # Oversized or unavailable inventories fail closed; IPv4 helper stays bounded.
    :if ([:len $external] > 32) do={ :set external [:toarray ""] }
    :local tag "sdwan:v1:dns-bootstrap"
    :local signature (($parent->"name") . ":" . ($parent->"address") . ":" . ($parent->"route_gateway") . ":" . [:serialize to=json value=$external options=json.no-string-conversion])
    :local wantedRules (2 * [:len $external])
    :if ((!$forced) && ($sdwanDNSBootstrapSignature = $signature) && ([:len [/ip/route/find where comment=$tag]] = [:len $external]) && ([:len [/ip/firewall/mangle/find where comment=$tag]] = $wantedRules) && ([:len [/ip/firewall/nat/find where comment=$tag]] = $wantedRules)) do={ :return 0 }
    /ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment=$tag]
    /ip/route/remove [/ip/route/find where comment=$tag]
    /ip/firewall/nat/remove [/ip/firewall/nat/find where comment=$tag]
    # Preserve explicitly source-bound SLA probes, ingress replies and PPP
    # transport pinning, which precede the router-originated source anchors.
    :local anchor [/ip/firewall/mangle/find where comment=("sdwan:v1:router-reply:" . ((($cfg->"wans")->0)->"name"))]
    :if ([:len $anchor] != 1) do={ :error "missing DNS bootstrap ordering anchor" }
    :foreach resolverIPText,ports in=$external do={
        /ip/route/add dst-address=($resolverIPText . "/32") gateway=($parent->"route_gateway") routing-table=main distance=250 comment=$tag
        :foreach protocol in={"udp";"tcp"} do={
            :local destinationPorts "53"
            :if ($protocol = "tcp") do={ :set destinationPorts $ports }
            /ip/firewall/nat/add chain=srcnat src-address-type=local dst-address=($resolverIPText . "/32") protocol=$protocol dst-port=$destinationPorts out-interface=($parent->"interface") action=masquerade comment=$tag place-before=0
            :if ([:len $anchor] = 0) do={ /ip/firewall/mangle/add chain=sdwan-output src-address-type=local dst-address=($resolverIPText . "/32") protocol=$protocol dst-port=$destinationPorts action=mark-routing new-routing-mark=($parent->"probe_table") passthrough=no comment=$tag } else={ /ip/firewall/mangle/add chain=sdwan-output src-address-type=local dst-address=($resolverIPText . "/32") protocol=$protocol dst-port=$destinationPorts action=mark-routing new-routing-mark=($parent->"probe_table") passthrough=no comment=$tag place-before=$anchor }
        }
    }
    :set sdwanDNSBootstrapSignature $signature
    :return [:len $external]
}

:global sdwanDNSLoaded 2
