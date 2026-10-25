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
# Shared install-only schema checks. Explicit JSON null is never a default.
:global sdwanOverlayKeys do={
    :if ([:typeof $value] != "array") do={ :error "overlay settings must be an object" }
    :local present [:toarray ""]
    :foreach key,item in=$value do={
        :if (([:typeof $key] != "str") || ([:typeof ($allowed->$key)] = "nothing") || ([:typeof $item] = "nil") || ([:typeof $item] = "nothing")) do={ :error "unknown or null overlay option" }
        :set ($present->$key) true
    }
    :foreach key in=$required do={ :if (($present->$key) != true) do={ :error "missing overlay option" } }
    :return true
}
:global sdwanOverlayIP do={
    :if ([:typeof $value] != "str") do={ :error "overlay IPv4 address must be text" }
    :local ip [:toip $value]
    :if (([:typeof $ip] != "ip") || ([:tostr $ip] != $value) || ($ip = 0.0.0.0) || ($ip >= 224.0.0.0) || (($ip >= 127.0.0.0) && ($ip < 128.0.0.0)) || (($ip >= 169.254.0.0) && ($ip < 169.255.0.0))) do={ :error "invalid overlay unicast IPv4 address" }
    :return $ip
}
:global sdwanOverlayPrefix do={
    :if ([:typeof $value] != "str") do={ :error "overlay prefix must be text" }
    :local text $value
    :if ((!($text ~ "^[0-9.]+/[0-9]+\$")) || ([:len $text] > 18)) do={ :error "invalid overlay IPv4 prefix" }
    :local slash [:find $text "/"]
    :local ip [:toip [:pick $text 0 $slash]]
    :local bits [:tonum [:pick $text ($slash + 1) [:len $text]]]
    :if (([:typeof $ip] != "ip") || ([:typeof $bits] != "num") || ($bits < 1) || ($bits > 32) || (([:tostr $ip] . "/" . $bits) != $text)) do={ :error "invalid canonical overlay prefix" }
    # Only canonical digits/dots/slash reach :parse; no untrusted script text.
    :local mask (255.255.255.255 << (32 - $bits))
    :local network ($ip & $mask)
    :if (($allowHost != true) && ($network != $ip)) do={ :error "overlay site prefix must be canonical" }
    :local prefix [[:parse (":return " . [:tostr $network] . "/" . $bits)]]
    :if ($allowHost != true) do={
        :if (($network < 1.0.0.0) || (($network >= 127.0.0.0) && ($network < 128.0.0.0)) || (($network >= 169.254.0.0) && ($network < 169.255.0.0)) || ($network >= 224.0.0.0) || (127.0.0.0 in $prefix) || (169.254.0.0 in $prefix) || (224.0.0.0 in $prefix)) do={ :error "overlay prefix overlaps a forbidden range" }
    }
    :return $prefix
}
:global sdwanOverlayOverlap do={
    :local l [:tostr $left]
    :local r [:tostr $right]
    :local a [:toip [:pick $l 0 [:find $l "/"]]]
    :local b [:toip [:pick $r 0 [:find $r "/"]]]
    :return (($a in $right) || ($b in $left))
}
:global sdwanOverlayPrefixes do={
    :global sdwanOverlayPrefix
    :global sdwanOverlayOverlap
    :if (([:typeof $value] != "array") || ([:len $value] > 64) || (([:len $value] = 0) && ($allowEmpty != true))) do={ :error "overlay prefixes must be a bounded nonempty list" }
    :local result [:toarray ""]
    :foreach key,item in=$value do={ :if ([:typeof $key] != "num") do={ :error "overlay prefixes must be a list" } }
    :if ([:len $value] = 0) do={ :return $result }
    :for index from=0 to=([:len $value] - 1) do={
        :local item ($value->$index)
        :if ([:typeof $item] != "str") do={ :error "overlay prefix list contains a null or non-text item" }
        :local prefix [$sdwanOverlayPrefix value=$item]
        :foreach previous in=$result do={ :if ([$sdwanOverlayOverlap left=$prefix right=$previous]) do={ :error "duplicate or overlapping overlay prefixes" } }
        :set result ($result,$prefix)
    }
    :return $result
}
:global sdwanOverlayPublicKey do={
    # Canonical 32-byte base64:43 data characters, one pad, zero pad bits.
    :if (([:typeof $value] != "str") || ([:len $value] != 44) || (!($value ~ "^[A-Za-z0-9+/]+=\$")) || (!([:pick $value 42 43] ~ "^[AEIMQUYcgkosw048]\$")) || ($value = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")) do={ :error "invalid canonical nonzero overlay public key" }
    :return true
}
# Bounded install-only list resolution. include -> exclude -> explicit members
# matches RouterOS order, including nested lists and the four built-in lists.
:global sdwanOverlayListHas do={
    :global sdwanOverlayListHas
    :global sdwanOverlayListCache
    :global sdwanOverlayListCalls
    :if (([:typeof $depth] != "num") || ($depth > 64)) do={ :error "overlay list nesting exceeds preflight budget" }
    :set sdwanOverlayListCalls ($sdwanOverlayListCalls + 1)
    :if ($sdwanOverlayListCalls > 4096) do={ :error "overlay interface-list resolution budget exceeded" }
    :if ($listName = "all") do={ :return true }
    :if ($listName = "none") do={ :return false }
    :if (($listName = "static") || ($listName = "dynamic")) do={
        :local ids [/interface/find where name=$iface]
        :if ([:len $ids] != 1) do={ :error "overlay interface disappeared" }
        :local isDynamic ([:tostr [/interface/get $ids dynamic]] = "true")
        :if ($listName = "dynamic") do={ :return $isDynamic }
        :return (!$isDynamic)
    }
    :local cacheKey ($iface . ":" . $listName)
    :if ([:typeof ($sdwanOverlayListCache->$cacheKey)] = "bool") do={ :return ($sdwanOverlayListCache->$cacheKey) }
    :if (($seen->$listName) = true) do={ :error "cyclic interface-list prevents overlay ownership validation" }
    :set ($seen->$listName) true
    :local rows [/interface/list/print as-value where name=$listName]
    :if ([:len $rows] != 1) do={ :error "unknown interface-list in overlay preflight" }
    :local row [:pick $rows 0]
    :local result false
    :foreach child in=[:toarray ($row->"include")] do={
        :if ([:len [:tostr $child]] > 0) do={ :if ([$sdwanOverlayListHas listName=[:tostr $child] iface=$iface seen=$seen depth=($depth + 1)]) do={ :set result true } }
    }
    :foreach child in=[:toarray ($row->"exclude")] do={
        :if ([:len [:tostr $child]] > 0) do={ :if ([$sdwanOverlayListHas listName=[:tostr $child] iface=$iface seen=$seen depth=($depth + 1)]) do={ :set result false } }
    }
    :foreach member in=[/interface/list/member/print as-value where list=$listName and interface=$iface] do={ :if (($member->"disabled") != true) do={ :set result true } }
    :set ($sdwanOverlayListCache->$cacheKey) $result
    :return $result
}
:global sdwanOverlayMainVRF do={
    :global sdwanOverlayListHas
    :foreach row in=[/ip/vrf/print as-value] do={
        :if (($row->"disabled") != true) do={
            :local matches false
            :foreach ref in=[:toarray ($row->"interfaces")] do={
                :if ([:tostr $ref] = $iface) do={ :set matches true } else={
                    :if ([:len [/interface/list/find where name=[:tostr $ref]]] > 0) do={ :if ([$sdwanOverlayListHas listName=[:tostr $ref] iface=$iface seen=[:toarray ""] depth=(0)]) do={ :set matches true } }
                }
            }
            :if ($matches) do={ :if (($row->"name") != "main") do={ :error "overlay interfaces and underlay WANs require main VRF" }; :return true }
        }
    }
    :error "overlay interface has no main VRF assignment"
}
# RouterOS7.24.5 drops null elements while deserializing JSON lists. Inspect
# the original JSON as well; quotes/escapes ensure an Address List named "null"
# or a hostname containing that text is never treated as a JSON null token.
:global sdwanOverlayJSON do={
    :if (([:typeof $value] != "str") || ([:len $value] > 60000)) do={ :error "overlay preflight requires bounded original JSON text" }
    :local quoted false
    :local escaped false
    :local stringStart 0
    :local scopes [:toarray ""]
    :local depth 0
    :local expected ""
    :local nextScope "other"
    :for i from=0 to=([:len $value] - 1) do={
        :local char [:pick $value $i ($i + 1)]
        :if ($quoted) do={
            :if ($escaped) do={ :set escaped false } else={
                :if ($char = "\\") do={ :set escaped true } else={
                    :if ($char = "\"") do={
                        :set quoted false
                        :local next ($i + 1)
                        :while (($next < [:len $value]) && ([:typeof [:find " \r\n\t" [:pick $value $next ($next + 1)]]] != "nil")) do={ :set next ($next + 1) }
                        :if ([:pick $value $next ($next + 1)] = ":") do={
                            # Deserialize keys too: escaped Unicode field names
                            # must obey the same structure as literal names.
                            :local key [:deserialize from=json options=json.no-string-conversion value=[:pick $value $stringStart ($i + 1)]]
                            :local parent ($scopes->($depth - 1))
                            :set expected ""
                            :set nextScope "other"
                            :if (($parent = "root") && ($key = "overlay")) do={ :set expected "{"; :set nextScope "overlay" }
                            :if ($parent = "overlay") do={
                                :if ($key = "health") do={ :set expected "{" }
                                :if (($key = "local_prefixes") || ($key = "remote_prefixes") || ($key = "tunnels")) do={ :set expected "[" }
                                :if ($key = "tunnels") do={ :set nextScope "tunnels" }
                            }
                            :if (($parent = "tunnel") && ($key = "peer_prefixes")) do={ :set expected "[" }
                        }
                    }
                }
            }
        } else={
            :if (([:typeof [:find " \r\n\t" $char]] = "nil") && ($char != ":") && ($char != ",")) do={
                :if ([:pick $value $i ($i + 4)] = "null") do={ :error "JSON null is not an overlay configuration value" }
                :if (($expected != "") && ($char != $expected)) do={ :error "overlay JSON object/list type mismatch" }
                :if (($char = "{") || ($char = "[")) do={
                    :local child $nextScope
                    :if ($depth = 0) do={ :set child "root" } else={ :if ((($scopes->($depth - 1)) = "tunnels") && ($char = "{")) do={ :set child "tunnel" } }
                    :if ($depth >= 64) do={ :error "overlay JSON nesting exceeds validation budget" }
                    :set ($scopes->$depth) $child
                    :set depth ($depth + 1)
                }
                :if (($char = "}") || ($char = "]")) do={ :set depth ($depth - 1) }
                :set expected ""
                :set nextScope "other"
                :if ($char = "\"") do={ :set quoted true; :set stringStart $i }
            }
        }
    }
    :return true
}
:global sdwanOverlayValidate do={
    :global sdwanOverlayListHas
    :global sdwanOverlayMainVRF
    :global sdwanOverlayListCache [:toarray ""]
    :global sdwanOverlayListCalls 0
    :global sdwanOverlayJSON
    :if ([:typeof $rawJSON] = "str") do={ :local checkedJSON [$sdwanOverlayJSON value=$rawJSON] }
    :global sdwanOverlayKeys
    :global sdwanOverlayIP
    :global sdwanOverlayPrefix
    :global sdwanOverlayPrefixes
    :global sdwanOverlayOverlap
    :global sdwanOverlayPublicKey
    :global sdwanOverlayHealth
    :local overlay ($cfg->"overlay")
    :local declared false
    :foreach key,value in=$cfg do={ :if ($key = "overlay") do={ :set declared true } }
    :if ($declared) do={
        :local ok [$sdwanOverlayKeys value=$overlay required=({"enabled"}) allowed=({"enabled"=true;"role"=true;"router_id"=true;"local_prefixes"=true;"remote_prefixes"=true;"tunnels"=true;"mtu"=true;"mss_clamp"=true;"health"=true})]
        :if ([:typeof ($overlay->"enabled")] != "bool") do={ :error "overlay enabled must be boolean" }
        :if ((($overlay->"enabled") = false) && ([:len $overlay] != 1)) do={ :error "disabled overlay must contain only enabled=false" }
    }
    :local on (($overlay->"enabled") = true)
    :foreach row in=[/interface/list/print as-value where name="sdwan-overlay"] do={
        :if (($row->"comment") != "sdwan:v1:overlay:list") do={ :error "foreign overlay interface-list name" }
        :if (([:len ($row->"include")] > 0) || ([:len ($row->"exclude")] > 0)) do={ :error "overlay interface-list must contain only owned explicit members" }
    }
    :foreach row in=[/ip/firewall/address-list/print as-value where list="sdwan-overlay-sites"] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign entry in reserved overlay site Address List" } }
    :foreach row in=[/interface/list/member/print as-value where list="sdwan-overlay"] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign overlay interface-list member" } }
    # Reserved instance/filter names are never adopted from another application.
    :foreach row in=[/routing/ospf/instance/print as-value where name="sdwan-overlay"] do={
        :if (($row->"comment") != "sdwan:v1:overlay:instance") do={ :error "foreign overlay OSPF instance name" }
        :if ((([:tostr ($row->"vrf")] != "") && ([:tostr ($row->"vrf")] != "main")) || (([:tostr ($row->"routing-table")] != "") && ([:tostr ($row->"routing-table")] != "main"))) do={ :error "owned overlay OSPF instance requires main VRF/table" }
    }
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
    :local ok [$sdwanOverlayKeys value=$overlay required=({"enabled";"role";"router_id";"local_prefixes";"remote_prefixes";"tunnels"}) allowed=({"enabled"=true;"role"=true;"router_id"=true;"local_prefixes"=true;"remote_prefixes"=true;"tunnels"=true;"mtu"=true;"mss_clamp"=true;"health"=true})]
    :if ((($overlay->"role") != "site") && (($overlay->"role") != "hub")) do={ :error "invalid overlay role" }
    :local routerID [$sdwanOverlayIP value=($overlay->"router_id")]
    :foreach key,value in=$overlay do={
        :if (($key = "mtu") && (([:typeof $value] != "num") || ($value < 1280) || ($value > 1420))) do={ :error "invalid overlay MTU" }
        :if (($key = "mss_clamp") && ([:typeof $value] != "bool")) do={ :error "overlay MSS clamp must be boolean" }
        :if ($key = "health") do={
            :local ignored [$sdwanOverlayKeys value=$value required=[:toarray ""] allowed=({"interval_seconds"=true;"timeout_ms"=true;"packet_count"=true;"packet_interval_ms"=true;"fail_windows"=true;"recover_windows"=true;"hold_down_seconds"=true;"stale_seconds"=true;"rtt_ms"=true;"jitter_ms"=true;"loss_percent"=true})]
            :local ranges {"interval_seconds"={1;60};"timeout_ms"={100;2000};"packet_count"={2;20};"packet_interval_ms"={10;500};"fail_windows"={1;10};"recover_windows"={1;20};"hold_down_seconds"={0;300};"stale_seconds"={2;300};"rtt_ms"={1;5000};"jitter_ms"={1;5000};"loss_percent"={0;99}}
            :foreach field,item in=$value do={ :local range ($ranges->$field); :if (([:typeof $item] != "num") || ($item < ($range->0)) || ($item > ($range->1))) do={ :error "invalid overlay health range" } }
        }
    }
    :local h [$sdwanOverlayHealth overlay=$overlay]
    :if (((($h->"packet_count") - 1) * ($h->"packet_interval_ms") + ($h->"timeout_ms")) >= (($h->"interval_seconds") * 1000)) do={ :error "overlay probe train exceeds interval" }
    :if (($h->"stale_seconds") < (2 * ($h->"interval_seconds"))) do={ :error "overlay stale budget must cover two intervals" }
    :local localNets [$sdwanOverlayPrefixes value=($overlay->"local_prefixes") allowEmpty=(($overlay->"role") = "hub")]
    :local remoteNets [$sdwanOverlayPrefixes value=($overlay->"remote_prefixes")]
    :foreach a in=$localNets do={ :foreach b in=$remoteNets do={ :if ([$sdwanOverlayOverlap left=$a right=$b]) do={ :error "overlay site prefixes overlap" } } }
    :local allNets ($localNets,$remoteNets)
    :local tunnels ($overlay->"tunnels")
    :if (([:typeof $tunnels] != "array") || ([:len $tunnels] < 1) || ([:len $tunnels] > 16)) do={ :error "overlay tunnel budget exceeded" }
    :local names [:toarray ""]
    :local ports [:toarray ""]
    :local keys [:toarray ""]
    :foreach index,tunnel in=$tunnels do={ :if ([:typeof $index] != "num") do={ :error "overlay tunnels must be a list" } }
    :for index from=0 to=([:len $tunnels] - 1) do={
        :local tunnel ($tunnels->$index)
        :if ([:typeof $tunnel] != "array") do={ :error "overlay tunnel must be an object" }
        :local ignored [$sdwanOverlayKeys value=$tunnel required=({"name";"wan";"listen_port";"address";"peer_address";"local_public_key";"peer_public_key";"peer_prefixes";"cost"}) allowed=({"name"=true;"wan"=true;"listen_port"=true;"address"=true;"peer_address"=true;"local_public_key"=true;"peer_public_key"=true;"peer_prefixes"=true;"cost"=true;"endpoint"=true;"endpoint_port"=true;"keepalive_seconds"=true})]
        :local tn ($tunnel->"name")
        :if (([:typeof $tn] != "str") || (!($tn ~ "^[a-z][a-z0-9_-]*\$")) || ([:len $tn] > 20) || (($names->$tn) = true)) do={ :error "invalid overlay tunnel name" }
        :set ($names->$tn) true
        :local port ($tunnel->"listen_port")
        :if (([:typeof $port] != "num") || ($port < 1024) || ($port > 65535) || (($ports->[:tostr $port]) = true)) do={ :error "invalid overlay UDP port" }
        :set ($ports->[:tostr $port]) true
        :local ignored [$sdwanOverlayPublicKey value=($tunnel->"local_public_key")]
        :local ignored [$sdwanOverlayPublicKey value=($tunnel->"peer_public_key")]
        :if ((($tunnel->"local_public_key") = ($tunnel->"peer_public_key")) || (($keys->($tunnel->"local_public_key")) = true)) do={ :error "overlay local/peer identities must be distinct" }
        :set ($keys->($tunnel->"local_public_key")) true
        :local iface ("sdwan-wg-" . $tn)
        :local ifaceVRF [$sdwanOverlayMainVRF iface=$iface]
        :local iid [/interface/wireguard/find where name=$iface]
        :if (([:len $iid] != 1) || ([/interface/wireguard/get $iid comment] != ("sdwan:v1:overlay:interface:" . $tn)) || ([/interface/wireguard/get $iid public-key] != ($tunnel->"local_public_key"))) do={ :error "prepare or rediscover the matching overlay public identity" }
        :foreach row in=[/interface/wireguard/print as-value where listen-port=$port] do={ :if (($row->"name") != $iface) do={ :error "overlay listen port belongs to another interface" } }
        :local subnet [$sdwanOverlayPrefix value=($tunnel->"address") allowHost=(true)]
        :local address ($tunnel->"address")
        :local slash [:find $address "/"]
        :local bits [:tonum [:pick $address ($slash + 1) [:len $address]]]
        :if (($bits != 30) && ($bits != 31)) do={ :error "overlay link must use /30 or /31" }
        :local ownIP [$sdwanOverlayIP value=[:pick $address 0 $slash]]
        :local peer [$sdwanOverlayIP value=($tunnel->"peer_address")]
        :if (($peer = $ownIP) || (!($peer in $subnet))) do={ :error "overlay peer must be on its link subnet" }
        :if ($bits = 30) do={
            :local network ($ownIP & 255.255.255.252)
            :local broadcast ($network | 0.0.0.3)
            :if (($ownIP = $network) || ($ownIP = $broadcast) || ($peer = $network) || ($peer = $broadcast)) do={ :error "overlay /30 must use two usable host addresses" }
        }
        :foreach previous in=$allNets do={ :if ([$sdwanOverlayOverlap left=$subnet right=$previous]) do={ :error "overlay link overlaps site or other link" } }
        :set allNets ($allNets,$subnet)
        :local wanFound false
        :if ([:typeof ($tunnel->"wan")] != "str") do={ :error "overlay WAN name must be text" }
        :foreach wan in=($cfg->"wans") do={ :if (($wan->"name") = ($tunnel->"wan")) do={ :set wanFound true; :if ((($wan->"interface") = $iface) || (($wan->"kind") = "vpn")) do={ :error "overlay requires a physical underlay WAN" } } }
        :if (!$wanFound) do={ :error "unknown overlay underlay WAN" }
        :if (([:typeof ($tunnel->"cost")] != "num") || (($tunnel->"cost") < 1) || (($tunnel->"cost") > 65535)) do={ :error "invalid overlay OSPF cost" }
        :local peerNets [$sdwanOverlayPrefixes value=($tunnel->"peer_prefixes")]
        :foreach net in=$peerNets do={
            :local text [:tostr $net]
            :local sep [:find $text "/"]
            :local ip [:toip [:pick $text 0 $sep]]
            :local length [:tonum [:pick $text ($sep + 1) [:len $text]]]
            :local covered false
            :foreach remote in=$remoteNets do={ :local r [:tostr $remote]; :local prefixLength [:tonum [:pick $r ([:find $r "/"] + 1) [:len $r]]]; :if (($ip in $remote) && ($length >= $prefixLength)) do={ :set covered true } }
            :if (!$covered) do={ :error "overlay peer prefixes outside declared remote networks" }
        }
        :if (($overlay->"role") = "site") do={
            :local endpoint ($tunnel->"endpoint")
            :if (([:typeof $endpoint] != "str") || ([:len $endpoint] < 1) || ([:len $endpoint] > 253)) do={ :error "site requires a hub endpoint" }
            :local endpointIP [:toip $endpoint]
            :if ([:typeof $endpointIP] = "ip") do={ :local ignored [$sdwanOverlayIP value=$endpoint] } else={
                :if ((!($endpoint ~ "^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]\$")) && (!($endpoint ~ "^[A-Za-z0-9]\$"))) do={ :error "invalid overlay hub hostname" }
                :if ([:typeof [:find $endpoint ".."]] != "nil") do={ :error "invalid overlay hub hostname" }
            }
            :local endpointPort ($tunnel->"endpoint_port")
            :if (([:typeof $endpointPort] != "num") || ($endpointPort < 1024) || ($endpointPort > 65535)) do={ :error "invalid overlay endpoint port" }
            :foreach key,item in=$tunnel do={ :if (($key = "keepalive_seconds") && (([:typeof $item] != "num") || ($item < 10) || ($item > 60))) do={ :error "invalid overlay keepalive" } }
        } else={
            :foreach key,item in=$tunnel do={
                :if (($key = "endpoint") || ($key = "endpoint_port")) do={ :error "overlay hub is responder-only" }
                :if (($key = "keepalive_seconds") && (([:typeof $item] != "num") || ($item != 0))) do={ :error "overlay hub keepalive must be zero" }
            }
        }
        :local probeTable ("sdwan-ol-" . $tn)
        :if (([:len [/routing/table/find where name=$probeTable]] > 0) && ([:len [/ip/route/find where comment=("sdwan:v1:overlay:guard:" . $tn)]] != 1)) do={ :error "overlay table has no ownership proof" }
        :foreach wan in=($cfg->"wans") do={
            :if (($wan->"probe_table") = $probeTable) do={ :error "overlay table collides with WAN probe table" }
            :if (($wan->"name") = ($tunnel->"wan")) do={ :local underlayVRF [$sdwanOverlayMainVRF iface=($wan->"interface")] }
        }
        :foreach policy in=($cfg->"policies") do={ :if (($policy->"table") = $probeTable) do={ :error "overlay table collides with policy table" } }
        :foreach row in=[/ip/route/print as-value where routing-table=$probeTable] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign route in owned overlay probe table" } }
        :foreach row in=[/routing/rule/print as-value where table=$probeTable] do={ :if (!(($row->"comment") ~ "^sdwan:v1:overlay:")) do={ :error "foreign rule references owned overlay probe table" } }
        # Prevent a broad foreign OSPF template from also activating on WG.
        :foreach row in=[/routing/ospf/interface-template/print as-value] do={
            :if (([:tostr ($row->"disabled")] != "true") && (!(($row->"comment") ~ "^sdwan:v1:overlay:"))) do={
                :local matchInterface ([:len ($row->"interfaces")] = 0)
                :foreach ref in=($row->"interfaces") do={
                    :if ([:tostr $ref] = $iface) do={ :set matchInterface true } else={
                        :if ([:len [/interface/list/find where name=[:tostr $ref]]] > 0) do={ :if ([$sdwanOverlayListHas listName=[:tostr $ref] iface=$iface seen=[:toarray ""] depth=(0)]) do={ :set matchInterface true } }
                    }
                }
                :local matchNetwork ([:len ($row->"networks")] = 0)
                :local linkMask 255.255.255.254
                :if ($bits = 30) do={ :set linkMask 255.255.255.252 }
                :local networkIP ($ownIP & $linkMask)
                :foreach network in=($row->"networks") do={ :onerror ipv6 in={ :local net [[:parse (":return " . [:tostr $network])]]; :if ($networkIP in $net) do={ :set matchNetwork true } } do={} }
                :if ($matchInterface && $matchNetwork) do={ :error "foreign OSPF template would match the overlay interface" }
            }
        }
    }
    # All link prefixes are known now; endpoints cannot recurse into a later link.
    :foreach tunnel in=$tunnels do={
        :local endpoint [:toip ($tunnel->"endpoint")]
        :if ([:typeof $endpoint] = "ip") do={ :foreach net in=$allNets do={ :if ($endpoint in $net) do={ :error "overlay endpoint recurses through overlay" } } }
        :foreach wan in=($cfg->"wans") do={ :if (($wan->"interface") = ("sdwan-wg-" . ($tunnel->"name"))) do={ :error "owned overlay interface cannot be any WAN" } }
    }
    :foreach wan in=($cfg->"wans") do={
        :if (([:typeof ($wan->"kind")] = "nothing") || (($wan->"kind") = "static")) do={
            :local ip [:toip ($wan->"address")]
            :foreach net in=$allNets do={ :if ($ip in $net) do={ :error "overlay prefixes overlap an underlay WAN address" } }
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
            :global sdwanForwardAnchor
            :local first [$sdwanForwardAnchor]
            :if (([:len $first] > 0) && ([:tostr $id] != [:tostr $first])) do={ /ip/firewall/filter/move $id destination=$first }
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
