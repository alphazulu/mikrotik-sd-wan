# Optional IPv4 branch overlay. Functions are loaded only during installation
# or when enabled; no external controller, key export or periodic file writes.
:global sdwanOverlayNetworks do={
    :local result ($cfg->"local_networks")
    :local overlay ($cfg->"overlay")
    :if (($overlay->"enabled") = true) do={
        :foreach field in={"local_prefixes";"remote_prefixes"} do={ :foreach prefix in=($overlay->$field) do={ :set result ($result,$prefix) } }
        # Link prefixes stay local even while an OSPF template is withdrawn.
        :foreach tunnel in=($overlay->"tunnels") do={
            :local address [:tostr ($tunnel->"address")]
            :local slash [:find $address "/"]
            :local bits [:pick $address ($slash + 1) [:len $address]]
            :local ip [:toip [:pick $address 0 $slash]]
            :local mask 255.255.255.254
            :if ($bits = "30") do={ :set mask 255.255.255.252 }
            :set result ($result,([:tostr ($ip & $mask)] . "/" . $bits))
        }
    }
    :local unique [:toarray ""]
    :local seen [:toarray ""]
    :foreach prefix in=$result do={ :if (($seen->$prefix) != true) do={ :set ($seen->$prefix) true; :set unique ($unique,$prefix) } }
    :return $unique
}
:global sdwanOverlayPrefix do={
    :local text [:tostr $value]
    :if ((!($text ~ "^[0-9.]+/[0-9]+\$")) || ([:len $text] > 18)) do={ :error "invalid overlay IPv4 prefix" }
    :local slash [:find $text "/"]
    :local ip [:toip [:pick $text 0 $slash]]
    :local bits [:tonum [:pick $text ($slash + 1) [:len $text]]]
    :if (([:typeof $ip] != "ip") || ([:typeof $bits] != "num") || ($bits < 1) || ($bits > 32) || ($ip < 1.0.0.0) || ($ip >= 224.0.0.0) || (($ip >= 127.0.0.0) && ($ip < 128.0.0.0))) do={ :error "forbidden overlay IPv4 prefix" }
    # Input is digits/dots/slash only, so this cannot inject script/filter text.
    :local mask (255.255.255.255 << (32 - $bits))
    :local network ($ip & $mask)
    :if (($allowHost != true) && ($network != $ip)) do={ :error "overlay site prefix must be canonical" }
    :local prefix [[:parse (":return " . [:tostr $network] . "/" . $bits)]]
    :if ((0.0.0.0 in $prefix) || (127.0.0.1 in $prefix) || (169.254.0.1 in $prefix) || (224.0.0.0 in $prefix)) do={ :error "overlay prefix contains a forbidden range" }
    :return $prefix
}
:global sdwanOverlayValidate do={
    :global sdwanOverlayPrefix
    :local overlay ($cfg->"overlay")
    :local on (($overlay->"enabled") = true)
    :foreach row in=[/interface/list/print as-value where name="sdwan-overlay"] do={ :if (($row->"comment") != "sdwan:v1:overlay:list") do={ :error "foreign overlay interface-list name" } }
    :foreach row in=[/interface/list/member/print as-value where list="sdwan-overlay"] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign overlay interface-list member" } }
    # Reserved instance/filter names are never adopted from another application.
    :foreach row in=[/routing/ospf/instance/print as-value where name="sdwan-overlay"] do={ :if (($row->"comment") != "sdwan:v1:overlay:instance") do={ :error "foreign overlay OSPF instance name" } }
    :foreach row in=[/routing/ospf/area/print as-value where name="sdwan-overlay-backbone"] do={ :if (($row->"comment") != "sdwan:v1:overlay:area") do={ :error "foreign overlay OSPF area name" } }
    :foreach row in=[/routing/filter/rule/print as-value where chain="sdwan-overlay-out"] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign overlay output filter rule" } }
    :foreach row in=[/routing/ospf/instance/print as-value] do={ :if ((($row->"out-filter-chain") = "sdwan-overlay-out") && (($row->"comment") != "sdwan:v1:overlay:instance")) do={ :error "foreign OSPF instance references overlay filter" } }
    :foreach row in=[/routing/ospf/interface-template/print as-value] do={ :if ((($row->"area") = "sdwan-overlay-backbone") && (!(($row->"comment") ~ "^sdwan:v1:overlay:"))) do={ :error "foreign template references overlay area" } }
    :foreach row in=[/routing/ospf/area/print as-value] do={ :if ((($row->"instance") = "sdwan-overlay") && (($row->"comment") != "sdwan:v1:overlay:area")) do={ :error "foreign area references overlay instance" } }
    :foreach iid in=[/interface/wireguard/find where comment~"^sdwan:v1:overlay:interface:"] do={
        :local iface [/interface/wireguard/get $iid name]
        :foreach row in=[/interface/wireguard/peers/print as-value where interface=$iface] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign peer on owned overlay interface" } }
        :foreach row in=[/ip/address/print as-value where interface=$iface] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign address on owned overlay interface" } }
    }
    :if (!$on) do={ :return true }
    :if ((($overlay->"role") != "site") && (($overlay->"role") != "hub")) do={ :error "invalid overlay role" }
    :if (([:typeof ($overlay->"tunnels")] != "array") || ([:len ($overlay->"tunnels")] < 1) || ([:len ($overlay->"tunnels")] > 16)) do={ :error "overlay tunnel budget exceeded" }
    :if ([:typeof [:toip ($overlay->"router_id")]] != "ip") do={ :error "invalid overlay router ID" }
    :local health ($overlay->"health")
    :if (([:typeof $health] != "nil") && ([:typeof $health] != "nothing")) do={
        :if ([:typeof $health] != "array") do={ :error "invalid overlay health settings" }
        :local ranges {"interval_seconds"={1;60};"timeout_ms"={100;2000};"packet_count"={2;20};"packet_interval_ms"={10;500};"fail_windows"={1;10};"recover_windows"={1;20};"hold_down_seconds"={0;300};"stale_seconds"={2;300};"rtt_ms"={1;5000};"jitter_ms"={1;5000};"loss_percent"={0;99}}
        :foreach key,value in=$health do={ :local range ($ranges->$key); :if (([:typeof $range] != "array") || ([:typeof $value] != "num") || ($value < ($range->0)) || ($value > ($range->1))) do={ :error "invalid overlay health range" } }
    }
    :local mtu ($overlay->"mtu")
    :if (([:typeof $mtu] != "nil") && ([:typeof $mtu] != "nothing")) do={ :if (([:typeof $mtu] != "num") || ($mtu < 1280) || ($mtu > 1420)) do={ :error "invalid overlay MTU" } }
    :foreach field in={"local_prefixes";"remote_prefixes"} do={
        :if (([:typeof ($overlay->$field)] != "array") || ([:len ($overlay->$field)] > 64)) do={ :error "invalid overlay prefix list" }
        :foreach value in=($overlay->$field) do={ :local prefix [$sdwanOverlayPrefix value=$value] }
    }
    :local names [:toarray ""]
    :local ports [:toarray ""]
    :foreach tunnel in=($overlay->"tunnels") do={
        :local tn [:tostr ($tunnel->"name")]
        :if ((!($tn ~ "^[a-z][a-z0-9_-]*\$")) || ([:len $tn] > 20) || (($names->$tn) = true)) do={ :error "invalid overlay tunnel name" }
        :set ($names->$tn) true
        :local port ($tunnel->"listen_port")
        :if (([:typeof $port] != "num") || ($port < 1024) || ($port > 65535) || (($ports->[:tostr $port]) = true)) do={ :error "invalid overlay UDP port" }
        :set ($ports->[:tostr $port]) true
        :local iface ("sdwan-wg-" . $tn)
        :local iid [/interface/wireguard/find where name=$iface]
        :if (([:len $iid] != 1) || ([/interface/wireguard/get $iid comment] != ("sdwan:v1:overlay:interface:" . $tn)) || ([/interface/wireguard/get $iid public-key] != ($tunnel->"local_public_key"))) do={ :error "prepare or rediscover the matching overlay public identity" }
        :foreach row in=[/interface/wireguard/print as-value where listen-port=$port] do={ :if (($row->"name") != $iface) do={ :error "overlay listen port belongs to another interface" } }
        :local peer [:toip ($tunnel->"peer_address")]
        :local subnet [$sdwanOverlayPrefix value=($tunnel->"address") allowHost=(true)]
        :local ownAddress [:tostr ($tunnel->"address")]
        :local ownIP [:toip [:pick $ownAddress 0 [:find $ownAddress "/"]]]
        :if (([:typeof $peer] != "ip") || ($peer = $ownIP) || (!($peer in $subnet))) do={ :error "overlay peer must be on its link subnet" }
        :local address [:tostr ($tunnel->"address")]
        :local slash [:find $address "/"]
        :local bits [:tonum [:pick $address ($slash + 1) [:len $address]]]
        :if (($bits != 30) && ($bits != 31)) do={ :error "overlay link must use /30 or /31" }
        :local wanFound false
        :foreach wan in=($cfg->"wans") do={ :if (($wan->"name") = ($tunnel->"wan")) do={ :set wanFound true; :if (($wan->"interface") = $iface) do={ :error "overlay cannot be its own underlay" } } }
        :if (!$wanFound) do={ :error "unknown overlay underlay WAN" }
        :if (([:typeof ($tunnel->"cost")] != "num") || (($tunnel->"cost") < 1) || (($tunnel->"cost") > 65535)) do={ :error "invalid overlay OSPF cost" }
        :foreach value in=($tunnel->"peer_prefixes") do={ :local prefix [$sdwanOverlayPrefix value=$value] }
        :if (($overlay->"role") = "site") do={
            :if (([:len [:tostr ($tunnel->"endpoint")]] = 0) || ([:typeof ($tunnel->"endpoint_port")] != "num")) do={ :error "CGNAT site requires a reachable hub endpoint" }
        }
        :local table ("sdwan-ol-" . $tn)
        :if (([:len [/routing/table/find where name=$table]] > 0) && ([:len [/ip/route/find where comment=("sdwan:v1:overlay:guard:" . $tn)]] != 1)) do={ :error "overlay table has no ownership proof" }
        # Prevent a broad foreign OSPF template from also activating on WG.
        :foreach row in=[/routing/ospf/interface-template/print as-value where disabled=no] do={
            :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={
                :local matchInterface ([:len ($row->"interfaces")] = 0)
                :foreach ref in=($row->"interfaces") do={
                    :if (([:tostr $ref] = $iface) || ([:tostr $ref] = "all") || ([:tostr $ref] = "static")) do={ :set matchInterface true }
                    :if ([:len [/interface/list/member/find where list=$ref and interface=$iface]] > 0) do={ :set matchInterface true }
                }
                :local matchNetwork ([:len ($row->"networks")] = 0)
                :foreach network in=($row->"networks") do={ :onerror ipv6 in={ :local net [[:parse (":return " . [:tostr $network])]]; :if ($peer in $net) do={ :set matchNetwork true } } do={} }
                :if ($matchInterface && $matchNetwork) do={ :error "foreign OSPF template would match the overlay interface" }
            }
        }
    }
    :return true
}
:global sdwanOverlayHealth do={
    :local h ($overlay->"health")
    :local defaults {"interval_seconds"=2;"timeout_ms"=500;"packet_count"=3;"packet_interval_ms"=100;"fail_windows"=2;"recover_windows"=3;"hold_down_seconds"=6;"stale_seconds"=10;"rtt_ms"=150;"jitter_ms"=50;"loss_percent"=20}
    :foreach key,value in=$defaults do={ :if ([:typeof ($h->$key)] = "num") do={ :set ($defaults->$key) ($h->$key) } }
    :return $defaults
}
:global sdwanOverlayInstall do={
    :global sdwanOverlayHealth
    :local overlay ($cfg->"overlay")
    :local on (($overlay->"enabled") = true)
    :local wanted [:toarray ""]
    :local keepInterfaces [:toarray ""]
    :local ensure do={
        :local id [/ip/firewall/mangle/find where comment=$tag]
        :if ([:len $id] > 1) do={ :error "duplicate overlay mangle ownership" }
        :if ([:len $id] = 0) do={ /ip/firewall/mangle/add chain=output action=passthrough comment=$tag disabled=yes; :set id [/ip/firewall/mangle/find where comment=$tag] }
        :return $id
    }
    :if ($on) do={
        :local h [$sdwanOverlayHealth overlay=$overlay]
        :local mtu ($overlay->"mtu")
        :if ([:typeof $mtu] != "num") do={ :set mtu 1380 }
        :if ([:len [/interface/list/find where name="sdwan-overlay"]] = 0) do={ /interface/list/add name=sdwan-overlay comment="sdwan:v1:overlay:list" }
        /ip/firewall/address-list/remove [/ip/firewall/address-list/find where comment~"^sdwan:v1:overlay:"]
        :local prefixes (($overlay->"local_prefixes"),($overlay->"remote_prefixes"))
        :foreach prefix in=$prefixes do={ /ip/firewall/address-list/add list=sdwan-overlay-sites address=$prefix comment=("sdwan:v1:overlay:site-address:" . $prefix) }
        # Exact explicit export list; never export WANs, default or link prefixes.
        /routing/filter/rule/remove [/routing/filter/rule/find where chain="sdwan-overlay-out" and comment~"^sdwan:v1:overlay:"]
        :foreach prefix in=($overlay->"local_prefixes") do={ /routing/filter/rule/add chain=sdwan-overlay-out rule=("if (dst == " . $prefix . ") { accept; }") comment=("sdwan:v1:overlay:export:" . $prefix) }
        /routing/filter/rule/add chain=sdwan-overlay-out rule="reject;" comment="sdwan:v1:overlay:export:reject"
        :local instance [/routing/ospf/instance/find where name="sdwan-overlay"]
        :if ([:len $instance] = 0) do={ /routing/ospf/instance/add name=sdwan-overlay version=2 router-id=($overlay->"router_id") originate-default=never redistribute=connected out-filter-chain=sdwan-overlay-out comment="sdwan:v1:overlay:instance" } else={ /routing/ospf/instance/set $instance router-id=($overlay->"router_id") originate-default=never redistribute=connected out-filter-chain=sdwan-overlay-out disabled=no }
        :local area [/routing/ospf/area/find where name="sdwan-overlay-backbone"]
        :if ([:len $area] = 0) do={ /routing/ospf/area/add name=sdwan-overlay-backbone area-id=0.0.0.0 instance=sdwan-overlay comment="sdwan:v1:overlay:area" }
        :foreach tunnel in=($overlay->"tunnels") do={
            :local tn ($tunnel->"name")
            :local iface ("sdwan-wg-" . $tn)
            :set ($keepInterfaces->$iface) true
            :local memberTag ("sdwan:v1:overlay:member:" . $tn)
            :set ($wanted->$memberTag) true
            :if ([:len [/interface/list/member/find where comment=$memberTag]] = 0) do={ /interface/list/member/add list=sdwan-overlay interface=$iface comment=$memberTag }
            :local iid [/interface/wireguard/find where name=$iface]
            /interface/wireguard/set $iid listen-port=($tunnel->"listen_port") mtu=$mtu disabled=no
            :local tag ""
            :set tag ("sdwan:v1:overlay:address:" . $tn)
            :set ($wanted->$tag) true
            :local aid [/ip/address/find where comment=$tag]
            :if ([:len $aid] = 0) do={ /ip/address/add address=($tunnel->"address") interface=$iface comment=$tag } else={ /ip/address/set $aid address=($tunnel->"address") interface=$iface disabled=no }
            :local address [:tostr ($tunnel->"address")]
            :local source [:pick $address 0 [:find $address "/"]]
            :local table ("sdwan-ol-" . $tn)
            :if ([:len [/routing/table/find where name=$table]] = 0) do={ /routing/table/add name=$table fib }
            :set tag ("sdwan:v1:overlay:guard:" . $tn); :set ($wanted->$tag) true
            :if ([:len [/ip/route/find where comment=$tag]] = 0) do={ /ip/route/add blackhole dst-address=0.0.0.0/0 routing-table=$table distance=254 comment=$tag }
            :set tag ("sdwan:v1:overlay:probe-route:" . $tn); :set ($wanted->$tag) true
            :local rid [/ip/route/find where comment=$tag]
            :if ([:len $rid] = 0) do={ /ip/route/add dst-address=(($tunnel->"peer_address") . "/32") gateway=$iface routing-table=$table comment=$tag } else={ /ip/route/set $rid dst-address=(($tunnel->"peer_address") . "/32") gateway=$iface routing-table=$table disabled=no }
            :set tag ("sdwan:v1:overlay:probe-rule:" . $tn); :set ($wanted->$tag) true
            :set rid [/routing/rule/find where comment=$tag]
            # Use recreate/place-before; rule move wedged earlier 7.24.5 CHR
            # reinstall/rollback tests. This source/peer rule must stay first.
            :if ([:len $rid] > 0) do={ /routing/rule/remove $rid }
            :local first [:pick [/routing/rule/find] 0]
            :if ([:len $first] = 0) do={ /routing/rule/add src-address=($source . "/32") dst-address=(($tunnel->"peer_address") . "/32") action=lookup-only-in-table table=$table comment=$tag } else={ /routing/rule/add src-address=($source . "/32") dst-address=(($tunnel->"peer_address") . "/32") action=lookup-only-in-table table=$table comment=$tag place-before=$first }
            :local wanSpec [:toarray ""]
            :foreach wan in=($cfg->"wans") do={ :if (($wan->"name") = ($tunnel->"wan")) do={ :set wanSpec $wan } }
            :set tag ("sdwan:v1:overlay:outer-pin:" . $tn); :set ($wanted->$tag) true
            :local id [$ensure tag=$tag]
            /ip/firewall/mangle/set $id chain=output action=mark-routing protocol=udp src-port=($tunnel->"listen_port") new-routing-mark=($wanSpec->"probe_table") passthrough=no disabled=no
            :set first [:pick [/ip/firewall/mangle/find where chain=output] 0]
            :if ([:tostr $id] != [:tostr $first]) do={ /ip/firewall/mangle/move $id destination=$first }
            :set tag ("sdwan:v1:overlay:nat:" . $tn); :set ($wanted->$tag) true
            :set id [/ip/firewall/nat/find where comment=$tag]
            :if ([:len $id] = 0) do={ /ip/firewall/nat/add chain=srcnat protocol=udp src-port=($tunnel->"listen_port") out-interface=($wanSpec->"interface") action=masquerade comment=$tag; :set id [/ip/firewall/nat/find where comment=$tag] } else={ /ip/firewall/nat/set $id src-port=($tunnel->"listen_port") out-interface=($wanSpec->"interface") disabled=no }
            :set first [:pick [/ip/firewall/nat/find where chain=srcnat] 0]
            :if ([:tostr $id] != [:tostr $first]) do={ /ip/firewall/nat/move $id destination=$first }
            # Listener, inner ICMP and OSPF are the only router input openings.
            :foreach purpose in={"listener";"icmp";"ospf"} do={
                :set tag ("sdwan:v1:overlay:" . $purpose . ":" . $tn); :set ($wanted->$tag) true
                :set id [/ip/firewall/filter/find where comment=$tag]
                :if ([:len $id] = 0) do={ /ip/firewall/filter/add chain=input action=accept comment=$tag disabled=yes; :set id [/ip/firewall/filter/find where comment=$tag] }
                :if ($purpose = "listener") do={ /ip/firewall/filter/set $id protocol=udp dst-port=($tunnel->"listen_port") in-interface=($wanSpec->"interface") disabled=no } else={
                    :if ($purpose = "icmp") do={ /ip/firewall/filter/set $id protocol=icmp src-address=(($tunnel->"peer_address") . "/32") dst-address=($source . "/32") in-interface=$iface disabled=no } else={ /ip/firewall/filter/set $id protocol=ospf in-interface=$iface disabled=no }
                }
                :set first [:pick [/ip/firewall/filter/find where chain=input] 0]
                :if ([:tostr $id] != [:tostr $first]) do={ /ip/firewall/filter/move $id destination=$first }
            }
            :set tag ("sdwan:v1:overlay:peer:" . $tn)
            :set ($wanted->$tag) true
            :local pid [/interface/wireguard/peers/find where comment=$tag]
            :if ([:len $pid] = 0) do={ /interface/wireguard/peers/add interface=$iface public-key=($tunnel->"peer_public_key") allowed-address=(($tunnel->"peer_address") . "/32") comment=$tag disabled=yes; :set pid [/interface/wireguard/peers/find where comment=$tag] }
            :local allowed (($tunnel->"peer_address") . "/32,224.0.0.5/32")
            :foreach prefix in=($tunnel->"peer_prefixes") do={ :set allowed ($allowed . "," . $prefix) }
            /interface/wireguard/peers/set $pid interface=$iface public-key=($tunnel->"peer_public_key") allowed-address=$allowed
            :if (($overlay->"role") = "site") do={
                :local keepalive ($tunnel->"keepalive_seconds")
                :if ([:typeof $keepalive] != "num") do={ :set keepalive 25 }
                /interface/wireguard/peers/set $pid endpoint-address=($tunnel->"endpoint") endpoint-port=($tunnel->"endpoint_port") persistent-keepalive=($keepalive . "s") responder=no
            } else={ /interface/wireguard/peers/set $pid endpoint-address="" endpoint-port=0 persistent-keepalive=0s responder=yes }
            /interface/wireguard/peers/enable $pid
            :set tag ("sdwan:v1:overlay:probe:" . $tn); :set ($wanted->$tag) true
            :set id [/tool/netwatch/find where comment=$tag]
            :if ([:len $id] = 0) do={ /tool/netwatch/add type=icmp host=($tunnel->"peer_address") src-address=$source comment=$tag disabled=yes; :set id [/tool/netwatch/find where comment=$tag] }
            /tool/netwatch/set $id type=icmp host=($tunnel->"peer_address") src-address=$source interval=(($h->"interval_seconds") . "s") timeout=(($h->"timeout_ms") . "ms") packet-count=($h->"packet_count") packet-interval=(($h->"packet_interval_ms") . "ms") thr-avg=(($h->"rtt_ms") . "ms") thr-jitter=(($h->"jitter_ms") . "ms") thr-max=5s thr-stdev=5s thr-loss-percent=(($h->"loss_percent") . "%") start-delay=1s startup-delay=0s disabled=no
            :set tag ("sdwan:v1:overlay:ospf:" . $tn); :set ($wanted->$tag) true
            :set id [/routing/ospf/interface-template/find where comment=$tag]
            :if ([:len $id] = 0) do={ /routing/ospf/interface-template/add area=sdwan-overlay-backbone interfaces=$iface type=ptp cost=($tunnel->"cost") hello-interval=1s dead-interval=4s disabled=yes comment=$tag } else={ /routing/ospf/interface-template/set $id interfaces=$iface cost=($tunnel->"cost") }
        }
        :foreach prefix in=($overlay->"remote_prefixes") do={
            :local tag ("sdwan:v1:overlay:remote-guard:" . $prefix); :set ($wanted->$tag) true
            :if ([:len [/ip/route/find where comment=$tag]] = 0) do={ /ip/route/add blackhole dst-address=$prefix routing-table=main distance=254 comment=$tag }
        }
        # Every accepted new forwarded flow must have an authenticated WG leg
        # and both endpoints in the explicit site prefix list.
        :foreach direction in={"in";"out"} do={
            :local tag ("sdwan:v1:overlay:forward:" . $direction); :set ($wanted->$tag) true
            :local id [/ip/firewall/filter/find where comment=$tag]
            :if ([:len $id] = 0) do={ /ip/firewall/filter/add chain=forward src-address-list=sdwan-overlay-sites dst-address-list=sdwan-overlay-sites action=accept comment=$tag disabled=yes; :set id [/ip/firewall/filter/find where comment=$tag] }
            :if ($direction = "in") do={ /ip/firewall/filter/set $id in-interface-list=sdwan-overlay disabled=no } else={ /ip/firewall/filter/set $id out-interface-list=sdwan-overlay disabled=no }
            :local first [:pick [/ip/firewall/filter/find where chain=forward] 0]
            :if ([:tostr $id] != [:tostr $first]) do={ /ip/firewall/filter/move $id destination=$first }
        }
        :if (($overlay->"mss_clamp") = true) do={
            :local tag "sdwan:v1:overlay:mss"; :set ($wanted->$tag) true
            :local id [$ensure tag=$tag]
            /ip/firewall/mangle/set $id chain=forward protocol=tcp tcp-flags=syn out-interface-list=sdwan-overlay action=change-mss new-mss=($mtu - 40) tcp-mss=(($mtu - 39) . "-65535") passthrough=yes disabled=no
        }

    }
    # Retire only this module's stale objects. Keep disabled key identities so
    # disabling/re-enabling the optional overlay never regenerates private keys.
    :foreach id in=[/routing/ospf/interface-template/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/routing/ospf/interface-template/get $id comment]) != true) do={ /routing/ospf/interface-template/remove $id } }
    :foreach id in=[/tool/netwatch/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/tool/netwatch/get $id comment]) != true) do={ /tool/netwatch/remove $id } }
    :foreach id in=[/routing/rule/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/routing/rule/get $id comment]) != true) do={ /routing/rule/remove $id } }
    :local retiredTables [:toarray ""]
    :foreach id in=[/ip/route/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/ip/route/get $id comment]) != true) do={ :local table [/ip/route/get $id routing-table]; :if ([:tostr $table] ~ "^sdwan-ol-") do={ :set ($retiredTables->[:tostr $table]) true }; /ip/route/remove $id } }
    :foreach id in=[/ip/firewall/mangle/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/ip/firewall/mangle/get $id comment]) != true) do={ /ip/firewall/mangle/remove $id } }
    :foreach id in=[/ip/firewall/nat/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/ip/firewall/nat/get $id comment]) != true) do={ /ip/firewall/nat/remove $id } }
    :foreach id in=[/ip/firewall/filter/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/ip/firewall/filter/get $id comment]) != true) do={ /ip/firewall/filter/remove $id } }
    :foreach id in=[/ip/address/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/ip/address/get $id comment]) != true) do={ /ip/address/remove $id } }
    :foreach id in=[/interface/wireguard/peers/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/interface/wireguard/peers/get $id comment]) != true) do={ /interface/wireguard/peers/remove $id } }
    :foreach id in=[/interface/list/member/find where comment~"^sdwan:v1:overlay:"] do={ :if (($wanted->[/interface/list/member/get $id comment]) != true) do={ /interface/list/member/remove $id } }
    :foreach table,value in=$retiredTables do={ /routing/table/remove [/routing/table/find where name=$table] }
    :foreach id in=[/interface/wireguard/find where comment~"^sdwan:v1:overlay:interface:"] do={ :if (($keepInterfaces->[/interface/wireguard/get $id name]) != true) do={ :if (![/interface/wireguard/get $id disabled]) do={ /interface/wireguard/disable $id } } }
    :if (!$on) do={
        /routing/ospf/area/remove [/routing/ospf/area/find where comment="sdwan:v1:overlay:area"]
        /routing/ospf/instance/remove [/routing/ospf/instance/find where comment="sdwan:v1:overlay:instance"]
        /routing/filter/rule/remove [/routing/filter/rule/find where comment~"^sdwan:v1:overlay:"]
        /ip/firewall/address-list/remove [/ip/firewall/address-list/find where comment~"^sdwan:v1:overlay:"]
    }
}
:global sdwanOverlayTick do={
    :global sdwanOverlayState
    :global sdwanOverlayHealth
    :local overlay ($cfg->"overlay")
    :local report [:toarray ""]
    :if (($overlay->"enabled") != true) do={ :set sdwanOverlayState [:toarray ""]; :return $report }
    :local h [$sdwanOverlayHealth overlay=$overlay]
    :local next [:toarray ""]
    :if ([:typeof $sdwanOverlayState] != "array") do={ :set sdwanOverlayState [:toarray ""] }
    :foreach tunnel in=($overlay->"tunnels") do={
        :local tn ($tunnel->"name")
        :local probe [/tool/netwatch/find where comment=("sdwan:v1:overlay:probe:" . $tn)]
        :local template [/routing/ospf/interface-template/find where comment=("sdwan:v1:overlay:ospf:" . $tn)]
        :if (([:len $probe] != 1) || ([:len $template] != 1)) do={ :error "missing owned overlay probe/template" }
        :local wanSpec [:toarray ""]
        :foreach wan in=($cfg->"wans") do={ :if (($wan->"name") = ($tunnel->"wan")) do={ :set wanSpec $wan } }
        :local signature (($tunnel->"local_public_key") . ":" . ($tunnel->"peer_public_key") . ":" . ($tunnel->"address") . ":" . ($wanSpec->"address") . ":" . ($wanSpec->"route_gateway") . ":" . [:tostr $probe] . ":" . [:serialize to=json value=$h options=json.no-string-conversion])
        :local epoch [/tool/netwatch/get $probe done-tests]
        :if ([:typeof $epoch] != "num") do={ :set epoch 0 }
        :local state ($sdwanOverlayState->$tn)
        :if (([:typeof $state] != "array") || (($state->"signature") != $signature)) do={ :set state [:toarray ""]; :set ($state->"signature") $signature; :set ($state->"good") 0; :set ($state->"bad") 0; :set ($state->"fresh_at") $now; :set ($state->"last_bad") ($now - ($h->"hold_down_seconds")); :set ($state->"healthy") false; :set ($state->"epoch") $epoch; :set ($state->"not_before") ($now + ($h->"interval_seconds") + ((($h->"timeout_ms") + 999) / 1000) + 1) }
        # Netwatch may expose nil before its first test. A comparison with nil
        # is not a true freshness predicate on RouterOS; normalize both sides.
        :if ([:typeof ($state->"epoch")] != "num") do={ :set ($state->"epoch") 0 }
        :local fresh ($epoch != ($state->"epoch"))
        :if ($fresh) do={ :set ($state->"epoch") $epoch; :set ($state->"fresh_at") $now }
        :local ready (($wanSpec->"ready") = true)
        :local admin [:tostr ($wanSpec->"admin_state")]
        :if (($admin != "") && ($admin != "enabled")) do={ :set ready false }
        :local stale (($now - ($state->"fresh_at")) > ($h->"stale_seconds"))
        :local warming ($now < ($state->"not_before"))
        :local good ($ready && (!$stale) && (!$warming) && ([/tool/netwatch/get $probe status] = "up"))
        :if ((!$warming) && ($fresh || (!$ready) || $stale)) do={
            :if ($good) do={
                :set ($state->"good") (($state->"good") + 1); :set ($state->"bad") 0
                :if ((($state->"good") >= ($h->"recover_windows")) && (($now - ($state->"last_bad")) >= ($h->"hold_down_seconds"))) do={ :set ($state->"healthy") true }
            } else={
                :set ($state->"bad") (($state->"bad") + 1); :set ($state->"good") 0; :set ($state->"last_bad") $now
                :if ((!$ready) || $stale || (($state->"bad") >= ($h->"fail_windows"))) do={ :set ($state->"healthy") false }
            }
        }
        :if ((!$ready) || $warming || $stale) do={ :set ($state->"healthy") false }
        :local enabled (($state->"healthy") = true)
        :if ([/routing/ospf/interface-template/get $template disabled] = $enabled) do={ /routing/ospf/interface-template/set $template disabled=(!$enabled) }
        :set ($next->$tn) $state
        :local reason "recovering"
        :if ($enabled) do={ :set reason "healthy" }
        :if (!$good) do={ :set reason "probe-down" }
        :if ($warming) do={ :set reason "warming" }
        :if ($stale) do={ :set reason "stale" }
        :if (!$ready) do={ :set reason "physical-or-admin-down" }
        :local row [:toarray ""]; :set ($row->"reason") $reason; :set ($row->"healthy") $enabled; :set ($row->"wan") ($tunnel->"wan"); :set ($row->"cost") ($tunnel->"cost"); :set ($row->"probe_up") $good; :set ($row->"sample_age_seconds") ($now - ($state->"fresh_at")); :set ($row->"good_windows") ($state->"good"); :set ($row->"bad_windows") ($state->"bad")
        :set ($report->$tn) $row
    }
    :set sdwanOverlayState $next
    :return $report
}
:global sdwanOverlayLoaded 1
