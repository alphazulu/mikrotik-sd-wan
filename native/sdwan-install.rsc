:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
# Import after uploading sdwan-config.json and sdwan-controller.rsc.
:local cfg [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "sdwan-config.json")] contents]]
:if (($cfg->"schema_version") != 1) do={ :error "unsupported SDWAN schema" }
:if (([:len [/file/find where name=($dir . "sdwan-dataplane.rsc")]] != 1) || ([:len [/file/find where name=($dir . "sdwan-links.rsc")]] != 1)) do={ :error "upload dataplane and links libraries before installation" }
:global sdwanResolveWANs
:global sdwanLTEBinding
:global sdwanLTEAPNCapture
:global sdwanLTEAPNApply
:global sdwanPolicyExtended
:global sdwanProbeNativeType
:global sdwanConfigureProbe
/import file-name=($dir . "sdwan-links.rsc")
:global sdwanValidateStrict
:global sdwanStrictConfigure
$sdwanValidateStrict cfg=$cfg
:global sdwanMaintenance
:local checkedMaintenance [$sdwanMaintenance wans=($cfg->"wans") now=([:tonsec [/system/resource/get uptime]] / 1000000000)]
# Refuse collisions before mutating any named worker/scheduler.
:foreach ownedName in={"sdwan-strict-worker-0";"sdwan-strict-worker-1";"sdwan-strict-timeout-0";"sdwan-strict-timeout-1";"sdwan-strict-dispatch"} do={
    :foreach id in=[/system/script/find where name=$ownedName] do={ :if ([/system/script/get $id comment] != "sdwan:v1:strict") do={ :error "foreign strict worker name collision" } }
}
:foreach id in=[/system/scheduler/find where name="sdwan-strict-dispatch"] do={ :if ([/system/scheduler/get $id comment] != "sdwan:v1:strict") do={ :error "foreign strict scheduler name collision" } }
:if ([:tostr [/ip/firewall/connection/tracking/get enabled]] = "no") do={ :error "connection tracking must be enabled" }
:foreach id in=[/ip/firewall/mangle/find where disabled=no] do={
    :local action [/ip/firewall/mangle/get $id action]
    :if ((($action = "mark-routing") || ($action = "mark-connection") || ($action = "route")) && (!([/ip/firewall/mangle/get $id comment] ~ "^sdwan:v1:"))) do={ :error "foreign mangle marks must be reconciled before SDWAN installation" }
}
:if ([:len [/ip/firewall/raw/find where action=notrack and disabled=no]] > 0) do={ :error "RAW notrack conflicts with SDWAN" }
:foreach id in=[/ip/firewall/filter/find where action=fasttrack-connection and disabled=no] do={
    :local declared false
    :foreach selector in=($cfg->"disable_fasttrack") do={ :if ([:tostr ($selector->".id")] = [:tostr $id]) do={ :set declared true } }
    :if (!$declared) do={ :error "FastTrack must be declared for disabling" }
}
# Validate policy invariants before making any changes, including manual imports.
:local names [:toarray ""]
:foreach w in=($cfg->"wans") do={
    :local name ($w->"name")
    :if (($name = "") || (($names->$name) = true)) do={ :error "empty or duplicate WAN name" }
    :set ($names->$name) true
    :if (!(($w->"probe_table") ~ "^sdwan-")) do={ :error "probe table must start sdwan-" }
}
:local priorities [:toarray ""]
:local defaults 0
:foreach p in=($cfg->"policies") do={
    :if ((($p->"mode") != "prefer") && (($p->"mode") != "strict")) do={ :error "unknown policy mode" }
    :if ((($p->"mode") = "strict") && ([:len ($p->"wans")] != 1)) do={ :error "strict policy requires exactly one WAN" }
    :if ([:typeof (($cfg->"sla_profiles")->($p->"profile"))] != "array") do={ :error "unknown SLA profile" }
    :foreach name in=($p->"wans") do={ :if (($names->$name) != true) do={ :error "unknown policy WAN" } }
    :local rank ($p->"priority")
    :if ([:len [:tostr $rank]] > 0) do={
        :if (([:typeof $rank] != "num") || ($rank < 1) || ($rank > 999999) || (($priorities->[:tostr $rank]) = true)) do={ :error "invalid or duplicate policy priority" }
        :set ($priorities->[:tostr $rank]) true
    }
    :foreach field in={"source_group";"destination_group"} do={ :if ([:len [:tostr ($p->$field)]] > 0) do={ :if ([:typeof (($cfg->"groups")->($p->$field))] != "array") do={ :error "unknown policy group" } } }
    :local ingress [:tostr ($p->"in_interface")]
    :if (($ingress != "") && ([:len [/interface/find where name=$ingress]] != 1)) do={ :error "unknown policy input interface" }
    :local proto [:tostr ($p->"protocol")]
    :if (($proto != "") && ($proto != "any") && ($proto != "tcp") && ($proto != "udp") && ($proto != "icmp")) do={ :error "unsupported policy protocol" }
    :if ((([:len [:tostr ($p->"src_ports")]] > 0) || ([:len [:tostr ($p->"dst_ports")]] > 0)) && ($proto != "tcp") && ($proto != "udp")) do={ :error "policy ports require TCP or UDP" }
    :if (($p->"source") = "") do={
        :if ([$sdwanPolicyExtended policy=$p] || ([:len [:tostr $rank]] > 0)) do={ :error "default policy must not have selectors or priority" }
        :set defaults ($defaults + 1)
        :if (($p->"table") != "main") do={ :error "default policy must use main" }
    } else={ :if (!(($p->"table") ~ "^sdwan-")) do={ :error "client table must start sdwan-" } }
}
:if ($defaults != 1) do={ :error "exactly one default policy required" }
:local h ($cfg->"health")
:if ((($h->"quorum") < 1) || (($h->"fail_windows") < 1) || (($h->"recover_windows") < 1)) do={ :error "invalid SDWAN health parameters" }
:foreach w in=($cfg->"wans") do={
    :if ([:len [/interface/find where name=($w->"interface")]] != 1) do={ :error ("unknown WAN interface " . ($w->"interface")) }
    :if ([:len ($w->"probes")] < ($h->"quorum")) do={ :error "quorum exceeds target count" }
    :local mode [:tostr ($w->"kind")]
    :if (($mode = "") || ($mode = "static")) do={
        :local present false
        :foreach addr in=[/ip/address/find where interface=($w->"interface") and dynamic=no] do={
            :local ip [/ip/address/get $addr address]
            :if ([:pick $ip 0 [:find $ip "/"]] = ($w->"address")) do={ :set present true }
        }
        :if (!$present) do={ :error ("static WAN source address is not configured: " . ($w->"address")) }
    } else={
        :if (($mode != "dhcp") && ($mode != "pppoe") && ($mode != "lte")) do={ :error "unknown WAN kind" }
        :if (([:len [:tostr ($w->"address")]] > 0) || ([:len [:tostr ($w->"gateway")]] > 0)) do={ :error "dynamic WAN must not save a lease snapshot" }
        :if ($mode = "lte") do={
            :local binding [$sdwanLTEBinding iface=($w->"interface") profile=($w->"apn_profile")]
        } else={
            :local clients ""
            :if ($mode = "dhcp") do={ :set clients [/ip/dhcp-client/find where interface=($w->"interface")] } else={ :set clients [/interface/pppoe-client/find where name=($w->"interface")] }
            :if ([:len $clients] != 1) do={ :error "missing or ambiguous provider client" }
        }
    }
}
:local scheduler [/system/scheduler/find where name="sdwan-controller"]
:if ([:len $scheduler] > 0) do={ /system/scheduler/disable $scheduler }
:local attempts 0
:while (([/system/script/job/print count-only where script="sdwan-controller"] > 0) && ($attempts < 50)) do={ :delay 100ms; :set attempts ($attempts + 1) }
:if ([/system/script/job/print count-only where script="sdwan-controller"] > 0) do={ :error "SDWAN controller is busy" }
/tool/netwatch/disable [/tool/netwatch/find where comment~"^sdwan:v1:"]
:if ([:len [/file/find where name=($dir . "sdwan-backup.json")]] = 0) do={
    :local backup [:toarray ""]
    :local routes [:toarray ""]
    :foreach tag in=($cfg->"takeover_route_comments") do={
        :local id [/ip/route/find where comment=$tag]
        :if ([:len $id] > 1) do={ :error "duplicate takeover route comment" }
        :if ([:len $id] = 1) do={ :set ($routes->$tag) [/ip/route/get $id disabled] }
    }
    :set ($backup->"routes") $routes
    :local oldrule ($cfg->"takeover_rule")
    :local rules [:toarray ""]
    :if (($oldrule->"src-address") != "") do={ :foreach id in=[/routing/rule/find where src-address=($oldrule->"src-address") and table=($oldrule->"table")] do={ :set ($rules->[:tostr $id]) [/routing/rule/get $id disabled] } }
    :set ($backup->"rules") $rules
    /file/add name=($dir . "sdwan-backup.json") type=file contents=[:serialize to=json value=$backup options=json.no-string-conversion]
}
# Exact selectors let the configurator adopt uncommented routes without renaming them.
:local backup [/file/get [/file/find where name=($dir . "sdwan-backup.json")] contents]
:set backup [:deserialize from=json options=json.no-string-conversion value=$backup]
:local routeFlags ($backup->"route_selectors")
:if ([:typeof $routeFlags] != "array") do={ :set routeFlags [:toarray ""] }
:if ([:typeof ($cfg->"takeover_routes")] = "array") do={
    :foreach selector in=($cfg->"takeover_routes") do={
        :local id [:tostr ($selector->".id")]
        :if ([:len [/ip/route/find where .id=$id]] != 1) do={ :error "selected route no longer exists" }
        :local actualTable [:tostr [/ip/route/get $id routing-table]]
        :if ($actualTable = "") do={ :set actualTable "main" }
        :if (([:tostr [/ip/route/get $id gateway]] != ($selector->"gateway")) || ([:tostr [/ip/route/get $id dst-address]] != ($selector->"dst-address")) || ($actualTable != ($selector->"routing-table")) || [/ip/route/get $id dynamic]) do={ :error "selected route changed; rediscover configuration" }
        :if ([:typeof ($routeFlags->$id)] != "array") do={
            :local item [:toarray ""]
            :set ($item->"disabled") [/ip/route/get $id disabled]
            :set ($item->"gateway") ($selector->"gateway")
            :set ($item->"dst-address") ($selector->"dst-address")
            :set ($item->"routing-table") ($selector->"routing-table")
            :set ($routeFlags->$id) $item
        }
    }
}
:local fastFlags ($backup->"fasttrack")
:if ([:typeof $fastFlags] != "array") do={ :set fastFlags [:toarray ""] }
:if ([:typeof ($cfg->"disable_fasttrack")] = "array") do={
    :foreach selector in=($cfg->"disable_fasttrack") do={
        :local id [:tostr ($selector->".id")]
        :if (([/ip/firewall/filter/get $id action] != "fasttrack-connection") || ([/ip/firewall/filter/get $id chain] != "forward")) do={ :error "FastTrack selector changed" }
        :if ([:typeof ($fastFlags->$id)] != "bool") do={ :set ($fastFlags->$id) [/ip/firewall/filter/get $id disabled] }
    }
}
# Preserve automatic-route settings before accepting dynamic clients.
:local providerFlags ($backup->"provider_clients")
:if ([:typeof $providerFlags] != "array") do={ :set providerFlags [:toarray ""] }
:local providersWanted [:toarray ""]
:foreach spec in=($cfg->"wans") do={
    :local mode [:tostr ($spec->"kind")]
    :if (($mode = "dhcp") || ($mode = "pppoe")) do={
        :local iface ($spec->"interface")
        :local key ($mode . ":" . $iface)
        :set ($providersWanted->$key) true
        :local id ""
        :if ($mode = "dhcp") do={ :set id [/ip/dhcp-client/find where interface=$iface] } else={ :set id [/interface/pppoe-client/find where name=$iface] }
        :local item ($providerFlags->$key)
        :if (([:typeof $item] != "array") || (($item->"id") != [:tostr $id])) do={
            :set item [:toarray ""]
            :set ($item->"kind") $mode
            :set ($item->"interface") $iface
            :set ($item->"id") [:tostr $id]
            :if ($mode = "dhcp") do={
                :set ($item->"original_add") [/ip/dhcp-client/get $id add-default-route]
                :set ($item->"original_tables") [/ip/dhcp-client/get $id default-route-tables]
            } else={ :set ($item->"original_add") [/interface/pppoe-client/get $id add-default-route] }
        }
        :if ($mode = "dhcp") do={
            :local routeMode ($item->"original_add")
            :if ([:tostr $routeMode] = "no") do={ :set routeMode "yes" }
            :set ($item->"managed_add") $routeMode
            :set ($item->"managed_tables") ($spec->"probe_table")
        } else={ :set ($item->"managed_add") false }
        :set ($providerFlags->$key) $item
    }
}
# A removed provider must not recreate defaults in main when its table retires.
# Its original settings remain available for the explicit baseline rollback.
:foreach key,item in=$providerFlags do={
    :if (($providersWanted->$key) != true) do={
        :if (($item->"kind") = "dhcp") do={ :set ($item->"managed_add") "no"; :set ($item->"managed_tables") "default" }
        :set ($providerFlags->$key) $item
    }
}
# APN baseline is per profile; a shared selected profile is adopted once.
:local apnFlags ($backup->"lte_apns")
:if ([:typeof $apnFlags] != "array") do={ :set apnFlags [:toarray ""] }
:local selectedLTE [:toarray ""]
:foreach spec in=($cfg->"wans") do={ :if (($spec->"kind") = "lte") do={ :set selectedLTE ($selectedLTE,($spec->"interface")) } }
:local apnsWanted [:toarray ""]
:local apnExpected [:toarray ""]
:foreach spec in=($cfg->"wans") do={
    :if (($spec->"kind") = "lte") do={
        :local profileName ($spec->"apn_profile")
        :if (($apnsWanted->$profileName) != true) do={
            :local captured [$sdwanLTEAPNCapture profile=$profileName selected=$selectedLTE]
            :local entry ($apnFlags->$profileName)
            :if ([:typeof $entry] = "array") do={
                :if (($entry->"id") != ($captured->"id")) do={ :error "managed LTE APN identity changed; baseline rollback required" }
                :if (($captured->"original_add") != ($entry->"managed_add")) do={ :error "managed LTE APN routing changed; reconcile before reapply" }
                :local retained ($entry->"interfaces")
                :foreach iface in=$selectedLTE do={
                    :local seen false
                    :foreach existing in=$retained do={ :if ($existing = $iface) do={ :set seen true } }
                    :if (!$seen) do={ :set retained ($retained,$iface) }
                }
                :set ($entry->"interfaces") $retained
            } else={ :set entry $captured }
            :set ($apnFlags->$profileName) $entry
            :set ($apnExpected->$profileName) ($captured->"original_add")
            :set ($apnsWanted->$profileName) true
        }
    }
}
:set ($backup->"lte_apns") $apnFlags
:set ($backup->"provider_clients") $providerFlags
:set ($backup->"route_selectors") $routeFlags
:set ($backup->"fasttrack") $fastFlags
:if ([/ip/settings/get rp-filter] = "strict") do={ :if ([:typeof ($backup->"rp_filter")] != "str") do={ :set ($backup->"rp_filter") "strict" } }
/file/set [/file/find where name=($dir . "sdwan-backup.json")] contents=[:serialize to=json value=$backup options=json.no-string-conversion]
:if ([/ip/settings/get rp-filter] = "strict") do={ /ip/settings/set rp-filter=loose }
# Tables must exist before DHCP moves any automatic routes into them.
:foreach spec in=($cfg->"wans") do={
    :local tableName ($spec->"probe_table")
    :if ([:len [/routing/table/find where name=$tableName]] = 0) do={ /routing/table/add name=$tableName fib }
}
:foreach key,item in=$providerFlags do={
    :local id ($item->"id")
    :local iface ($item->"interface")
    :if (($item->"kind") = "dhcp") do={
        :if ([:tostr [/ip/dhcp-client/find where interface=$iface]] = $id) do={
            # Avoid a transient main default: routing table first, then mode.
            /ip/dhcp-client/set $id add-default-route=no
            /ip/dhcp-client/set $id default-route-tables=($item->"managed_tables")
            /ip/dhcp-client/set $id add-default-route=($item->"managed_add")
        }
    } else={ :if ([:tostr [/interface/pppoe-client/find where name=$iface]] = $id) do={ /interface/pppoe-client/set $id add-default-route=no } }
}
# Baseline has been persisted before any APN mutation. Retired profiles remain
# suppressed until explicit baseline rollback; no accidental default in main.
:foreach profileName,entry in=$apnFlags do={
    :if (($apnsWanted->$profileName) = true) do={ $sdwanLTEAPNApply entry=$entry expected=($apnExpected->$profileName) }
}
:set ($cfg->"wans") [$sdwanResolveWANs wans=($cfg->"wans")]
# Placeholders remain disabled and are never promoted to the active JSON.
:foreach index,spec in=($cfg->"wans") do={
    :if (($spec->"kind") != "static") do={
        :if (($spec->"address") = "") do={ :set ($spec->"address") "0.0.0.0" }
        :if (($spec->"route_gateway") = "") do={ :set ($spec->"route_gateway") "127.0.0.1" }
        :set (($cfg->"wans")->$index) $spec
    }
}
:local wanted [:toarray ""]
:local wantedTables [:toarray ""]
:foreach w in=($cfg->"wans") do={
    :local wn ($w->"name")
    :local table ($w->"probe_table")
    :set ($wantedTables->$table) true
    :if ([:len [/routing/table/find where name=$table]] = 0) do={ /routing/table/add name=$table fib }
    :local tag ("sdwan:v1:pinroute:" . $wn)
    :set ($wanted->$tag) true
    :local id [/ip/route/find where comment=$tag]
    :local unavailable ((($w->"kind") != "static") && (!($w->"ready")))
    :if ([:len $id] = 0) do={ /ip/route/add dst-address=0.0.0.0/0 gateway=($w->"route_gateway") routing-table=$table comment=$tag disabled=$unavailable } else={ /ip/route/set $id gateway=($w->"route_gateway") routing-table=$table disabled=$unavailable }
    :local guardTag ("sdwan:v1:pin-blackhole:" . $wn)
    :set ($wanted->$guardTag) true
    :if ([:len [/ip/route/find where comment=$guardTag]] = 0) do={ /ip/route/add blackhole dst-address=0.0.0.0/0 routing-table=$table distance=254 comment=$guardTag }
    :set tag ("sdwan:v1:pinrule:" . $wn)
    :set ($wanted->$tag) true
    :set id [/routing/rule/find where comment=$tag]
    :if ([:len $id] = 0) do={
        :local before [:pick [/routing/rule/find] 0]
        :if ([:len $before] = 0) do={ /routing/rule/add src-address=(($w->"address") . "/32") action=lookup-only-in-table table=$table comment=$tag } else={ /routing/rule/add src-address=(($w->"address") . "/32") action=lookup-only-in-table table=$table comment=$tag place-before=$before }
    } else={ /routing/rule/set $id src-address=(($w->"address") . "/32") table=$table disabled=$unavailable }
    :if ($unavailable) do={ /routing/rule/disable [/routing/rule/find where comment=$tag] }
    # Initial route lookup for locally generated replies must also resolve when
    # SLA has disabled every main default. Include all additional WAN IPv4s.
    :foreach addr in=[/ip/address/find where interface=($w->"interface") and disabled=no and invalid=no] do={
        :local full [:tostr [/ip/address/get $addr address]]
        :local ip [:pick $full 0 [:find $full "/"]]
        :if (($ip != ($w->"address")) && (![/ip/address/get $addr dynamic])) do={
            :local aliasTag ("sdwan:v1:alias-pin:" . $wn . ":" . $ip)
            :set ($wanted->$aliasTag) true
            :local aliasId [/routing/rule/find where comment=$aliasTag]
            :if ([:len $aliasId] = 0) do={
                :local before [:pick [/routing/rule/find] 0]
                :if ([:len $before] = 0) do={ /routing/rule/add src-address=($ip . "/32") action=lookup-only-in-table table=$table comment=$aliasTag } else={ /routing/rule/add src-address=($ip . "/32") action=lookup-only-in-table table=$table comment=$aliasTag place-before=$before }
            } else={ /routing/rule/set $aliasId src-address=($ip . "/32") table=$table disabled=no }
        }
    }
    :set tag ("sdwan:v1:icmp:" . $wn)
    :set ($wanted->$tag) true
    :set id [/tool/netwatch/find where comment=$tag]
    :if ([:len $id] = 0) do={ /tool/netwatch/add comment=$tag type=icmp host=($w->"icmp_target") disabled=yes; :set id [/tool/netwatch/find where comment=$tag] }
    /tool/netwatch/set $id host=($w->"icmp_target") src-address=($w->"address") interval=(($h->"interval_seconds") . "s") timeout=(($h->"timeout_ms") . "ms") packet-count=($h->"packet_count") packet-interval=(($h->"packet_interval_ms") . "ms") thr-avg=5s thr-max=5s thr-stdev=5s thr-jitter=5s thr-loss-percent=100% start-delay=0s startup-delay=0s disabled=$unavailable
    :foreach p in=($w->"probes") do={
        :set tag ("sdwan:v1:probe:" . $wn . ":" . ($p->"name"))
        :set ($wanted->$tag) true
        :set id [/tool/netwatch/find where comment=$tag]
        :if ([:len $id] = 0) do={ /tool/netwatch/add comment=$tag type=[$sdwanProbeNativeType probe=$p] host=($p->"host") disabled=yes; :set id [/tool/netwatch/find where comment=$tag] }
        /tool/netwatch/set $id type=[$sdwanProbeNativeType probe=$p] host=($p->"host") src-address=($w->"address") interval=(($h->"interval_seconds") . "s") timeout=(($h->"timeout_ms") . "ms") start-delay=0s startup-delay=0s disabled=$unavailable
        $sdwanConfigureProbe pid=$id probe=$p
    }
}
:foreach policy in=($cfg->"policies") do={
    :local pn ($policy->"name")
    :local table ($policy->"table")
    :set ($wantedTables->$table) true
    :if ([:len [/routing/table/find where name=$table]] = 0) do={ /routing/table/add name=$table fib }
    :local distance 1
    :foreach wn in=($policy->"wans") do={
        :local gw ""
        :foreach w in=($cfg->"wans") do={ :if (($w->"name") = $wn) do={ :set gw ($w->"route_gateway") } }
        :if ($gw = "") do={ :error ("unknown policy WAN " . $wn) }
        :local tag ("sdwan:v1:route:" . $pn . ":" . $wn)
        :set ($wanted->$tag) true
        :local id [/ip/route/find where comment=$tag]
        :if ([:len $id] = 0) do={ /ip/route/add dst-address=0.0.0.0/0 gateway=$gw routing-table=$table distance=$distance check-gateway=none comment=$tag disabled=yes } else={ /ip/route/set $id gateway=$gw routing-table=$table distance=$distance check-gateway=none }
        :set distance ($distance + 1)
    }
    :if (($policy->"source") != "") do={
        :local guardTag ("sdwan:v1:policy-blackhole:" . $pn)
        :set ($wanted->$guardTag) true
        :if ([:len [/ip/route/find where comment=$guardTag]] = 0) do={ /ip/route/add blackhole dst-address=0.0.0.0/0 routing-table=$table distance=254 comment=$guardTag }
    }
    :if ((($policy->"source") != "") && (![$sdwanPolicyExtended policy=$policy])) do={
        :local tag ("sdwan:v1:client:" . $pn)
        :set ($wanted->$tag) true
        :local id [/routing/rule/find where comment=$tag]
        :if ([:len $id] = 0) do={ /routing/rule/add src-address=($policy->"source") action=lookup-only-in-table table=$table comment=$tag } else={ /routing/rule/set $id src-address=($policy->"source") table=$table disabled=no }
    }
}
:foreach network in=($cfg->"local_networks") do={
    :local tag ("sdwan:v1:local:" . $network)
    :set ($wanted->$tag) true
    :local id [/routing/rule/find where comment=$tag]
    # Recreate only our local bypass rules at the head. RouterOS 7.24.5 CHR
    # reproducibly wedged routing after move + rollback/reinstall; add/remove
    # avoids that path and still puts local destinations before WAN source pins.
    :if ([:len $id] > 0) do={ /routing/rule/remove $id }
    :local before [:pick [/routing/rule/find] 0]
    :if ([:len $before] = 0) do={ /routing/rule/add dst-address=$network table=main action=lookup-only-in-table comment=$tag } else={ /routing/rule/add dst-address=$network table=main action=lookup-only-in-table comment=$tag place-before=$before }
}
# Connection marks and route marks are installed only after all required tables exist.
/import file-name=($dir . "sdwan-dataplane.rsc")
# Reconcile removed managed rules, routes and probes; preserve all unowned objects.
:foreach id in=[/routing/rule/find where comment~"^sdwan:v1:"] do={ :if (($wanted->[/routing/rule/get $id comment]) != true) do={ /routing/rule/remove $id } }
:foreach id in=[/ip/route/find where comment~"^sdwan:v1:"] do={ :if (($wanted->[/ip/route/get $id comment]) != true) do={ /ip/route/remove $id } }
:foreach id in=[/tool/netwatch/find where comment~"^sdwan:v1:"] do={ :if (($wanted->[/tool/netwatch/get $id comment]) != true) do={ /tool/netwatch/remove $id } }
:foreach id in=[/routing/table/find where name~"^sdwan-"] do={ :if (($wantedTables->[/routing/table/get $id name]) != true) do={ /routing/table/remove $id } }
# Promote the complete, reconciled configuration. Editing the staging JSON alone is inert.
:local raw [/file/get [/file/find where name=($dir . "sdwan-config.json")] contents]
:local active [/file/find where name=($dir . "sdwan-active.json")]
:if ([:len $active] = 0) do={ /file/add name=($dir . "sdwan-active.json") type=file contents=$raw } else={ /file/set $active contents=$raw }
:local source [/file/get [/file/find where name=($dir . "sdwan-controller.rsc")] contents]
:local script [/system/script/find where name="sdwan-controller"]
:if ([:len $script] = 0) do={ /system/script/add name=sdwan-controller source=$source policy=read,write,policy,test,sensitive comment="sdwan:v1:controller" } else={ /system/script/set $script source=$source policy=read,write,policy,test,sensitive }
# Explicitly retire only the baseline objects declared in configuration.
:foreach tag in=($cfg->"takeover_route_comments") do={ /ip/route/disable [/ip/route/find where comment=$tag] }
:local oldrule ($cfg->"takeover_rule")
:if (($oldrule->"src-address") != "") do={ /routing/rule/disable [/routing/rule/find where src-address=($oldrule->"src-address") and table=($oldrule->"table")] }
:if ([:typeof ($cfg->"takeover_routes")] = "array") do={ :foreach selector in=($cfg->"takeover_routes") do={ /ip/route/disable ($selector->".id") } }
:if ([:typeof ($cfg->"disable_fasttrack")] = "array") do={ :foreach selector in=($cfg->"disable_fasttrack") do={ /ip/firewall/filter/disable ($selector->".id") } }
$sdwanStrictConfigure cfg=$cfg
:global sdwanStatusJSON "{\"controller\":\"initializing\"}"
:if ([:len $scheduler] = 0) do={ /system/scheduler/add name=sdwan-controller interval=1s on-event="/system/script/run sdwan-controller" policy=read,write,policy,test,sensitive start-time=startup comment="sdwan:v1:scheduler" } else={ /system/scheduler/set $scheduler interval=1s disabled=no }
:log warning "SDWAN native controller installed; probes warming up"
