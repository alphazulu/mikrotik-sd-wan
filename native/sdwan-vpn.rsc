# Optional existing VPN exits. No credentials, keys or certificates are read.
# The existing controller drives transport and SLA; no extra scheduler or files.
:global sdwanVPNFind do={
    :if ($kind = "wireguard") do={ :return [/interface/wireguard/find where name=$iface] }
    :if ($kind = "l2tp") do={ :return [/interface/l2tp-client/find where name=$iface] }
    :if ($kind = "sstp") do={ :return [/interface/sstp-client/find where name=$iface] }
    :if ($kind = "openvpn") do={ :return [/interface/ovpn-client/find where name=$iface] }
    :error "unknown VPN type"
}
:global sdwanVPNGet do={
    :if ($kind = "wireguard") do={ :return [/interface/wireguard/get $id $field] }
    :if ($kind = "l2tp") do={ :return [/interface/l2tp-client/get $id $field] }
    :if ($kind = "sstp") do={ :return [/interface/sstp-client/get $id $field] }
    :if ($kind = "openvpn") do={ :return [/interface/ovpn-client/get $id $field] }
    :error "unknown VPN type"
}
:global sdwanVPNRoutingSet do={
    :if ($kind = "l2tp") do={ :if ([/interface/l2tp-client/get $id add-default-route] != $auto) do={ /interface/l2tp-client/set $id add-default-route=$auto }; :return true }
    :if ($kind = "sstp") do={ :if ([/interface/sstp-client/get $id add-default-route] != $auto) do={ /interface/sstp-client/set $id add-default-route=$auto }; :return true }
    :if ($kind = "openvpn") do={ :if (([/interface/ovpn-client/get $id add-default-route] != $auto) || ([/interface/ovpn-client/get $id route-nopull] != $nopull)) do={ /interface/ovpn-client/set $id add-default-route=$auto route-nopull=$nopull }; :return true }
    :error "unknown PPP VPN type"
}
:global sdwanVPNRestart do={
    :if ($kind = "l2tp") do={ :if (![/interface/l2tp-client/get $id disabled]) do={ /interface/l2tp-client/disable $id; /interface/l2tp-client/enable $id }; :return true }
    :if ($kind = "sstp") do={ :if (![/interface/sstp-client/get $id disabled]) do={ /interface/sstp-client/disable $id; /interface/sstp-client/enable $id }; :return true }
    :if ($kind = "openvpn") do={ :if (![/interface/ovpn-client/get $id disabled]) do={ /interface/ovpn-client/disable $id; /interface/ovpn-client/enable $id }; :return true }
    :return false
}
# Binding validates immutable public identity, never availability/credentials.
:global sdwanVPNBinding do={
    :global sdwanVPNFind
    :global sdwanVPNGet
    :local kind ($spec->"vpn_type")
    :local iface ($spec->"interface")
    :local id [$sdwanVPNFind kind=$kind iface=$iface]
    :if ([:len $id] != 1) do={ :error "missing or ambiguous VPN client" }
    :local row [:toarray ""]
    :set ($row->"id") [:tostr $id]
    :set ($row->"kind") $kind
    :set ($row->"interface") $iface
    :set ($row->"disabled") [$sdwanVPNGet kind=$kind id=$id field="disabled"]
    :if ($kind = "wireguard") do={
        :local peers [/interface/wireguard/peers/find where interface=$iface and disabled=no]
        :if ([:len $peers] != 1) do={ :error "VPN exit requires one enabled WireGuard exit peer" }
        :local allowed [/interface/wireguard/peers/get $peers allowed-address]
        :local full false
        :foreach prefix in=$allowed do={ :if ([:tostr $prefix] = "0.0.0.0/0") do={ :set full true } }
        :if (!$full) do={ :error "WireGuard exit must allow 0.0.0.0/0; branch links cannot be adopted" }
        :if (([/interface/wireguard/peers/get $peers public-key] != ($spec->"vpn_peer_public_key")) || ([/interface/wireguard/get $id listen-port] != ($spec->"vpn_listen_port"))) do={ :error "VPN WireGuard identity/listen port changed" }
        :set ($row->"endpoint") [:tostr [/interface/wireguard/peers/get $peers endpoint-address]]
        :set ($row->"port") [/interface/wireguard/peers/get $peers endpoint-port]
        :set ($row->"protocol") "udp"
        :set ($row->"listen_port") [/interface/wireguard/get $id listen-port]
    } else={
        :set ($row->"endpoint") [:tostr [$sdwanVPNGet kind=$kind id=$id field="connect-to"]]
        :set ($row->"original_add") [$sdwanVPNGet kind=$kind id=$id field="add-default-route"]
        :local port 1701
        :local protocol "udp"
        :if ($kind = "sstp") do={
            :local proxy [:tostr [$sdwanVPNGet kind=$kind id=$id field="http-proxy"]]
            :if (($proxy != "") && ($proxy != "::") && ($proxy != "0.0.0.0") && ($proxy != "none")) do={ :error "SSTP HTTP proxy transport is not supported" }
            :set port [$sdwanVPNGet kind=$kind id=$id field="port"]; :set protocol "tcp"
        }
        :if ($kind = "l2tp") do={ :set ($row->"ipsec") [:tostr [$sdwanVPNGet kind=$kind id=$id field="use-ipsec"]] }
        :if ($kind = "openvpn") do={
            :if ([:tostr [$sdwanVPNGet kind=$kind id=$id field="mode"]] != "ip") do={ :error "OpenVPN exit requires routed IP mode" }
            :set port [$sdwanVPNGet kind=$kind id=$id field="port"]
            :set protocol [:tostr [$sdwanVPNGet kind=$kind id=$id field="protocol"]]
            :set ($row->"original_nopull") [$sdwanVPNGet kind=$kind id=$id field="route-nopull"]
        }
        :set ($row->"port") $port
        :set ($row->"protocol") $protocol
    }
    :if (($row->"endpoint") != ($spec->"vpn_endpoint")) do={ :error "VPN endpoint changed; rediscover" }
    :return $row
}
# Canonical containment is required for nonzero /31 host-bit link addresses.
:global sdwanVPNEndpointCheck do={
    :local ip [:toip $value]
    :if ([:typeof $ip] != "ip") do={ :return false }
    :if (($ip < 1.0.0.0) || ($ip >= 224.0.0.0) || (($ip >= 127.0.0.0) && ($ip < 128.0.0.0))) do={ :error "forbidden VPN endpoint address" }
    :local networks ($cfg->"local_networks")
    :if ((($cfg->"overlay")->"enabled") = true) do={
        :global sdwanOverlayNetworks
        :if ([:typeof $sdwanOverlayNetworks] != "array") do={ :error "overlay boundaries are not initialized" }
        :set networks [$sdwanOverlayNetworks cfg=$cfg]
    }
    :foreach prefix in=$networks do={
        :local slash [:find $prefix "/"]
        :local mask (255.255.255.255 << (32 - [:tonum [:pick $prefix ($slash + 1) [:len $prefix]]]))
        :local net ([:toip [:pick $prefix 0 $slash]] & $mask)
        :if (($ip & $mask) = $net) do={ :error "VPN endpoint recurses into a local/branch network" }
    }
    :return true
}
:global sdwanVPNValidate do={
    :global sdwanVPNEndpointCheck
    :global sdwanVPNBinding
    :local opts ($cfg->"vpn_egress")
    :local on (($opts->"enabled") = true)
    :if (([:typeof $opts] != "nil") && ([:typeof $opts] != "nothing")) do={
        :if ([:typeof $opts] != "array") do={ :error "invalid vpn_egress settings" }
        :foreach key,value in=$opts do={
            :if ((($key != "enabled") && ($key != "masquerade") && ($key != "allow_selected_forward")) || ([:typeof $value] != "bool")) do={ :error "invalid vpn_egress flag" }
        }
    }
    :local physical [:toarray ""]
    :foreach w in=($cfg->"wans") do={ :if (($w->"kind") != "vpn") do={ :set ($physical->($w->"name")) true } }
    :local ports [:toarray ""]
    :foreach w in=($cfg->"wans") do={
        :if (($w->"kind") = "vpn") do={
            :if (!$on) do={ :error "VPN WAN requires explicit vpn_egress.enabled=true" }
            :local parents ($w->"underlays")
            :if (([:typeof $parents] != "array") || ([:len $parents] < 1)) do={ :error "VPN requires physical underlays" }
            :local seen [:toarray ""]
            :foreach parent in=$parents do={
                :if ((($physical->$parent) != true) || (($seen->$parent) = true)) do={ :error "VPN underlays must be distinct physical WANs" }
                :set ($seen->$parent) true
            }
            :if (([:len [:tostr ($w->"address")]] > 0) || ([:len [:tostr ($w->"gateway")]] > 0)) do={ :error "VPN must not save an address snapshot" }
            :local endpoint [:tostr ($w->"vpn_endpoint")]
            :if (([:len $endpoint] < 1) || ([:len $endpoint] > 253) || (!($endpoint ~ "^[a-zA-Z0-9.-]+\$"))) do={ :error "invalid VPN endpoint" }
            :if (($w->"vpn_type") = "wireguard") do={
                :local port ($w->"vpn_listen_port")
                :if (([:typeof $port] != "num") || ($port < 1024) || ($port > 65535) || (($ports->[:tostr $port]) = true)) do={ :error "invalid/duplicate VPN listen port" }
                :set ($ports->[:tostr $port]) true
                :foreach other in=[/interface/wireguard/find where listen-port=$port] do={ :if ([/interface/wireguard/get $other name] != ($w->"interface")) do={ :error "VPN UDP port belongs to another interface" } }
            }
            :foreach t in=(($cfg->"overlay")->"tunnels") do={ :if ((($t->"wan") = ($w->"name")) || (("sdwan-wg-" . ($t->"name")) = ($w->"interface")) || (($t->"listen_port") = ($w->"vpn_listen_port"))) do={ :error "branch overlay and external VPN identities must be distinct" } }
            :local validEndpoint [$sdwanVPNEndpointCheck value=$endpoint cfg=$cfg]
            :local listName ("sdwan-vpn-endpoint-" . ($w->"name"))
            :local listTag ("sdwan:v1:vpn:endpoint:" . ($w->"name"))
            :foreach id in=[/ip/firewall/address-list/find where list=$listName and dynamic=no] do={ :if ([/ip/firewall/address-list/get $id comment] != $listTag) do={ :error "foreign VPN endpoint Address List collision" } }
            :local binding [$sdwanVPNBinding spec=$w]
        }
    }
    :foreach policy in=($cfg->"policies") do={
        :foreach wn in=($policy->"wans") do={
            :if (($physical->$wn) != true) do={
                :if ((($policy->"source") = "") || ([:len [:tostr ($policy->"destination_list")]] = 0)) do={ :error "VPN belongs only to destination Address List policies" }
            }
        }
    }
    :return true
}
# Capture all original PPP routing options before the installer persists backup.
:global sdwanVPNCapture do={
    :global sdwanVPNBinding
    :local result $entries
    :if ([:typeof $result] != "array") do={ :set result [:toarray ""] }
    :foreach spec in=($cfg->"wans") do={
        :if ((($spec->"kind") = "vpn") && (($spec->"vpn_type") != "wireguard")) do={
            :local row [$sdwanVPNBinding spec=$spec]
            :local key (($row->"kind") . ":" . ($row->"interface"))
            :local previous ($result->$key)
            :if ([:typeof $previous] = "array") do={
                :if ((($previous->"id") != ($row->"id")) || (($previous->"endpoint") != ($row->"endpoint")) || (($row->"original_add") != false) || ((($row->"kind") = "openvpn") && (($row->"original_nopull") != true))) do={ :error "managed VPN client routing/identity changed; baseline rollback required" }
            } else={ :set ($result->$key) $row }
        }
    }
    :return $result
}
# Retired PPP defaults stay suppressed until explicit baseline rollback.
:global sdwanVPNAdopt do={
    :global sdwanVPNFind
    :global sdwanVPNRoutingSet
    :foreach key,row in=$entries do={
        :local id [$sdwanVPNFind kind=($row->"kind") iface=($row->"interface")]
        :if ([:tostr $id] != ($row->"id")) do={ :error "managed PPP VPN identity changed" }
        :local ignored [$sdwanVPNRoutingSet kind=($row->"kind") id=$id auto=(false) nopull=(true)]
    }
}
:global sdwanVPNRestore do={
    :global sdwanVPNFind
    :global sdwanVPNGet
    :global sdwanVPNRoutingSet
    :foreach key,row in=$entries do={
        :local kind ($row->"kind")
        :local id [$sdwanVPNFind kind=$kind iface=($row->"interface")]
        :if (([:tostr $id] = ($row->"id")) && ([:tostr [$sdwanVPNGet kind=$kind id=$id field="connect-to"]] = ($row->"endpoint"))) do={
            :local untouched (![$sdwanVPNGet kind=$kind id=$id field="add-default-route"])
            :if ($kind = "openvpn") do={ :set untouched ($untouched && [$sdwanVPNGet kind=$kind id=$id field="route-nopull"]) }
            :if ($untouched) do={ :local ignored [$sdwanVPNRoutingSet kind=$kind id=$id auto=($row->"original_add") nopull=($row->"original_nopull")] } else={ :log warning "SDWAN skipped changed VPN routing options during baseline restore" }
        } else={ :log warning "SDWAN skipped changed VPN identity during baseline restore" }
    }
}
# Install only the optional transport objects and explicitly approved NAT/ACLs.
:global sdwanVPNInstall do={
    :local wanted [:toarray ""]
    :local on ((($cfg->"vpn_egress")->"enabled") = true)
    :if ($on) do={
        :foreach w in=($cfg->"wans") do={ :if (($w->"kind") = "vpn") do={
            :set ($wanted->("sdwan:v1:vpn:endpoint:" . ($w->"name"))) true
            :set ($wanted->("sdwan:v1:vpn:transport:" . ($w->"name"))) true
        } }
    }
    :foreach id in=[/ip/firewall/mangle/find where comment~"^sdwan:v1:vpn:"] do={ :if (($wanted->[/ip/firewall/mangle/get $id comment]) != true) do={ /ip/firewall/mangle/remove $id } }
    :foreach id in=[/ip/route/find where comment~"^sdwan:v1:vpn:"] do={ :if (($wanted->[/ip/route/get $id comment]) != true) do={ /ip/route/remove $id } }
    :foreach id in=[/ip/firewall/nat/find where comment~"^sdwan:v1:vpn:"] do={ :if (($wanted->[/ip/firewall/nat/get $id comment]) != true) do={ /ip/firewall/nat/remove $id } }
    /ip/firewall/filter/remove [/ip/firewall/filter/find where comment~"^sdwan:v1:vpn:"]
    :foreach id in=[/ip/firewall/address-list/find where dynamic=no and comment~"^sdwan:v1:vpn:"] do={ :if (($wanted->[/ip/firewall/address-list/get $id comment]) != true) do={ /ip/firewall/address-list/remove $id } }
    :if (!$on) do={ :global sdwanVPNTransport; :set sdwanVPNTransport [:toarray ""]; :return true }
    :foreach w in=($cfg->"wans") do={
        :if (($w->"kind") = "vpn") do={
            :local wn ($w->"name")
            :local endpoint ($w->"vpn_endpoint")
            :local endpointTag ("sdwan:v1:vpn:endpoint:" . $wn)
            :local entry [/ip/firewall/address-list/find where comment=$endpointTag and dynamic=no]
            :if ([:len $entry] > 1) do={ :error "duplicate owned VPN endpoint" }
            :if (([:len $entry] = 1) && ([:tostr [/ip/firewall/address-list/get $entry address]] != $endpoint)) do={ /ip/firewall/address-list/remove $entry; :set entry "" }
            :if ([:len $entry] = 0) do={ /ip/firewall/address-list/add list=("sdwan-vpn-endpoint-" . $wn) address=$endpoint comment=$endpointTag }
            :foreach p in=($cfg->"policies") do={
                :foreach selected in=($p->"wans") do={
                    :if ($selected = $wn) do={
                        :local mark ("sdwan-out-" . ($p->"name") . ":" . $wn)
                        :local tag ("sdwan:v1:vpn:egress:" . ($p->"name") . ":" . $wn)
                        :if ((($cfg->"vpn_egress")->"masquerade") = true) do={ /ip/firewall/nat/add chain=srcnat out-interface=($w->"interface") connection-mark=$mark action=masquerade comment=$tag }
                        :if ((($cfg->"vpn_egress")->"allow_selected_forward") = true) do={
                            :local before [:pick [/ip/firewall/filter/find where dynamic=no] 0]
                            :if ([:len $before] = 0) do={ /ip/firewall/filter/add chain=forward out-interface=($w->"interface") connection-mark=$mark connection-state=new,established,related action=accept comment=$tag } else={ /ip/firewall/filter/add chain=forward out-interface=($w->"interface") connection-mark=$mark connection-state=new,established,related action=accept comment=$tag place-before=$before }
                        }
                    }
                }
            }
        }
    }
    :return true
}
# Pick a physical transport, then feed logical VPN readiness into normal SLA.
# Config/route mutations happen only on a geometry transition. DNS list entries
# are maintained by RouterOS; no resolve/fetch or periodic storage writes here.
:global sdwanVPNTick do={
    :global sdwanVPNEndpointCheck
    :global sdwanVPNBinding
    :global sdwanVPNRestart
    :global sdwanVPNTransport
    :global sdwanState
    :if ([:typeof $sdwanVPNTransport] != "array") do={ :set sdwanVPNTransport [:toarray ""] }
    :local result ($cfg->"wans")
    :local physicalProfile ""
    :foreach policy in=($cfg->"policies") do={ :if (($policy->"source") = "") do={ :set physicalProfile ($policy->"profile") } }
    :local next [:toarray ""]
    :foreach index,w in=$result do={
        :if (($w->"kind") = "vpn") do={
            :local wn ($w->"name")
            :onerror transportError in={
            :local binding [:toarray ""]
            :local bindingReason ""
            :onerror changed in={ :set binding [$sdwanVPNBinding spec=$w] } do={ :set bindingReason $changed }
            :if ([:len $binding] > 0) do={
            :local parent [:toarray ""]
            :local candidate [:toarray ""]
            :foreach name in=($w->"underlays") do={
                :foreach physical in=$result do={
                    :local admin [:tostr ($physical->"admin_state")]
                    :if ((($physical->"name") = $name) && (($physical->"kind") != "vpn") && (($physical->"ready") = true) && (($admin = "") || ($admin = "enabled"))) do={
                        :if ([:len $candidate] = 0) do={ :set candidate $physical }
                        :if (([:len $parent] = 0) && (($sdwanState->($physicalProfile . "/" . $name)) = "healthy")) do={ :set parent $physical }
                    }
                }
            }
            :if ([:len $parent] = 0) do={ :set parent $candidate }
            :local live ([:len $parent] > 0)
            :local signature ((($binding->"id") . ":" . ($binding->"kind") . ":" . ($binding->"interface") . ":" . ($binding->"listen_port") . ":" . ($binding->"endpoint") . ":" . ($binding->"port") . ":" . ($binding->"protocol")) . ":" . ($parent->"name") . ":" . ($parent->"address") . ":" . ($parent->"route_gateway"))
            :local old ($sdwanVPNTransport->$wn)
            :local tag ("sdwan:v1:vpn:transport:" . $wn)
            :local endpoints [:toarray ""]
            :local addresses [/ip/firewall/address-list/find where list=("sdwan-vpn-endpoint-" . $wn)]
            :if ([:len $addresses] > 32) do={ :error "VPN endpoint DNS budget exceeded" }
            :foreach id in=$addresses do={
                :local ip [:toip [/ip/firewall/address-list/get $id address]]
                :if ([:typeof $ip] = "ip") do={
                    :local checked [$sdwanVPNEndpointCheck value=$ip cfg=$cfg]
                    :set ($endpoints->[:tostr $ip]) true
                }
            }
            :set signature ($signature . ":" . [:serialize to=json value=$endpoints options=json.no-string-conversion])
            :if (([:typeof $old] != "array") || (($old->"signature") != $signature)) do={
                /ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment=$tag]
                /ip/firewall/nat/remove [/ip/firewall/nat/find where comment=$tag]
                /ip/route/remove [/ip/route/find where comment=$tag]
                :local anchor [:pick [/ip/firewall/mangle/find where dynamic=no] 0]
                :local kind ($w->"vpn_type")
                :if ($kind = "wireguard") do={
                    # A unique source port escapes stale cached socket sources.
                    :if ($live) do={
                        /ip/firewall/mangle/add chain=output protocol=udp src-port=($binding->"listen_port") action=mark-routing new-routing-mark=($parent->"probe_table") passthrough=no comment=$tag place-before=$anchor
                        /ip/firewall/nat/add chain=srcnat protocol=udp src-port=($binding->"listen_port") out-interface=($parent->"interface") action=masquerade comment=$tag place-before=0
                    } else={ /ip/firewall/mangle/add chain=output protocol=udp src-port=($binding->"listen_port") action=drop comment=$tag place-before=$anchor }
                    # Retire only this local socket's managed physical transports.
                    :foreach cid in=[/ip/firewall/connection/find where protocol=udp and src-port=($binding->"listen_port")] do={
                        :onerror expired in={
                            :local mark [/ip/firewall/connection/get $cid connection-mark]
                            :if ($mark ~ "^sdwan-router-") do={ /ip/firewall/connection/remove $cid }
                        } do={ :if ([:len [/ip/firewall/connection/find where .id=$cid]] > 0) do={ :error $expired } }
                    }
                } else={
                    # Source-bound probes are untouched: PPP sockets start on a
                    # physical source selected by the endpoint bootstrap route.
                    :local anchor [/ip/firewall/mangle/find where comment=("sdwan:v1:router-reply:" . ((($cfg->"wans")->0)->"name"))]
                    :if ([:len $anchor] != 1) do={ :error "missing VPN transport insertion point" }
                    :foreach physical in=$result do={
                        :if ((($physical->"kind") != "vpn") && ([:len [:tostr ($physical->"address")]] > 0)) do={
                            :local source (($physical->"address") . "/32")
                            :local protocol ($binding->"protocol")
                            :local ports [:tostr ($binding->"port")]
                            :if ($kind = "l2tp") do={ :set ports "1-65535" }
                            :if ($live) do={ /ip/firewall/mangle/add chain=sdwan-output src-address=$source dst-address-list=("sdwan-vpn-endpoint-" . $wn) protocol=$protocol dst-port=$ports action=mark-routing new-routing-mark=($parent->"probe_table") passthrough=no comment=$tag place-before=$anchor } else={ /ip/firewall/mangle/add chain=sdwan-output src-address=$source dst-address-list=("sdwan-vpn-endpoint-" . $wn) protocol=$protocol dst-port=$ports action=drop comment=$tag place-before=$anchor }
                            :if (($kind = "l2tp") && (($binding->"ipsec") != "no")) do={
                                :if ($live) do={ /ip/firewall/mangle/add chain=sdwan-output src-address=$source dst-address-list=("sdwan-vpn-endpoint-" . $wn) protocol=ipsec-esp action=mark-routing new-routing-mark=($parent->"probe_table") passthrough=no comment=$tag place-before=$anchor } else={ /ip/firewall/mangle/add chain=sdwan-output src-address=$source dst-address-list=("sdwan-vpn-endpoint-" . $wn) protocol=ipsec-esp action=drop comment=$tag place-before=$anchor }
                            }
                        }
                    }
                }
                :if ($live && ($kind != "wireguard")) do={
                    :local ports [:tostr ($binding->"port")]
                    :if ($kind = "l2tp") do={ :set ports "1-65535" }
                    /ip/firewall/nat/add chain=srcnat dst-address-list=("sdwan-vpn-endpoint-" . $wn) protocol=($binding->"protocol") dst-port=$ports out-interface=($parent->"interface") src-address-type=local action=masquerade comment=$tag place-before=0
                }
                :if ($live) do={
                    :foreach ip,exists in=$endpoints do={ /ip/route/add dst-address=($ip . "/32") gateway=($parent->"route_gateway") routing-table=main distance=1 comment=$tag }
                }
                :if ($kind != "wireguard") do={ :local ignored [$sdwanVPNRestart kind=$kind id=($binding->"id")] }
            }
            :local row [:toarray ""]
            :set ($row->"signature") $signature
            :set ($row->"underlay") ($parent->"name")
            :set ($row->"ready") $live
            :set ($next->$wn) $row
            :if (!$live) do={ :set ($w->"ready") false; :set ($w->"link_reason") "no admitted physical VPN underlay"; :set ($result->$index) $w }
            } else={
                :set ($w->"ready") false
                :set ($w->"link_reason") "VPN binding unavailable or changed"
                :set ($result->$index) $w
                :local tag ("sdwan:v1:vpn:transport:" . $wn)
                /ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment=$tag]
                /ip/firewall/nat/remove [/ip/firewall/nat/find where comment=$tag]
                /ip/route/remove [/ip/route/find where comment=$tag]
                :set ($next->$wn) {"ready"=false;"underlay"=""}
            }
            } do={
                :set ($w->"ready") false
                :set ($w->"link_reason") "VPN transport unavailable or unsafe"
                :set ($result->$index) $w
                :local tag ("sdwan:v1:vpn:transport:" . $wn)
                /ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment=$tag]
                /ip/firewall/nat/remove [/ip/firewall/nat/find where comment=$tag]
                /ip/route/remove [/ip/route/find where comment=$tag]
                :set ($next->$wn) {"ready"=false;"underlay"=""}
            }
        }
    }
    :set sdwanVPNTransport $next
    :return $result
}
:global sdwanVPNOrder do={
    :local output [/ip/firewall/mangle/find where comment="sdwan:v1:jump:output"]
    :local source [/ip/firewall/mangle/find where comment=("sdwan:v1:router-reply:" . ((($cfg->"wans")->0)->"name"))]
    :if (([:len $output] != 1) || ([:len $source] != 1)) do={ :error "missing VPN transport order anchors" }
    :foreach w in=($cfg->"wans") do={
        :if (($w->"kind") = "vpn") do={
            :local tag ("sdwan:v1:vpn:transport:" . ($w->"name"))
            :foreach id in=[/ip/firewall/mangle/find where comment=$tag] do={
                :if (($w->"vpn_type") = "wireguard") do={ /ip/firewall/mangle/move $id destination=$output } else={ /ip/firewall/mangle/move $id destination=$source }
            }
        }
    }
}
:global sdwanVPNLoaded 1
