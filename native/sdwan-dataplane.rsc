:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
# Native connection tracking and symmetric routing. Imported by sdwan-install.rsc.
:local cfg [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "sdwan-config.json")] contents]]
:global sdwanResolveWANs
:if ([:typeof $sdwanResolveWANs] != "array") do={ /import file-name=($dir . "sdwan-links.rsc") }
:set ($cfg->"wans") [$sdwanResolveWANs wans=($cfg->"wans")]
:foreach index,w in=($cfg->"wans") do={ :if (($w->"address") = "") do={ :set ($w->"address") "0.0.0.0"; :set (($cfg->"wans")->$index) $w } }
:global sdwanOrderPolicies
:global sdwanApplyPolicyMatch
:global sdwanPolicySignature
:if ((($cfg->"overlay")->"enabled") = true) do={
    :global sdwanOverlayNetworks
    :set ($cfg->"local_networks") [$sdwanOverlayNetworks cfg=$cfg]
}
:global sdwanRecordEvent
:global sdwanConntrackRemoved
:local oldConfig false
:local classificationChanged false
:local activeFile [/file/find where name=($dir . "sdwan-active.json")]
:if ([:len $activeFile] = 1) do={
    :set oldConfig [:deserialize from=json options=json.no-string-conversion value=[/file/get $activeFile contents]]
    :set classificationChanged ([$sdwanPolicySignature cfg=$cfg] != [$sdwanPolicySignature cfg=$oldConfig])
}
:local wanted [:toarray ""]
:local marks [:toarray ""]
:local order [:toarray ""]
:local ensure do={
    :local id [/ip/firewall/mangle/find where comment=$tag]
    :if ([:len $id] > 1) do={ :error ("duplicate SDWAN mangle rule " . $tag) }
    :if ([:len $id] = 0) do={
        /ip/firewall/mangle/add chain=$chain action=passthrough comment=$tag disabled=yes
        :set id [/ip/firewall/mangle/find where comment=$tag]
    }
    :return $id
}
# Address list is confined to the SDWAN namespace.
:foreach id in=[/ip/firewall/address-list/find where dynamic=no and comment~"^sdwan:v1:"] do={ :if (!([/ip/firewall/address-list/get $id comment] ~ "^sdwan:v1:vpn:")) do={ /ip/firewall/address-list/remove $id } }
:foreach network in=($cfg->"local_networks") do={ /ip/firewall/address-list/add list=sdwan-local address=$network comment=("sdwan:v1:local-address:" . $network) }
# Mark incoming connections before DNAT; never mark their inbound packets for a WAN route.
:foreach w in=($cfg->"wans") do={
    :local wn ($w->"name")
    :local targets [:toarray ""]
    :set ($targets->[:tostr ($w->"icmp_target")]) true
    :foreach p in=($w->"probes") do={
        :local target [:tostr ($p->"host")]
        :if (($p->"type") = "dns") do={ :set target [:tostr ($p->"dns_server")] }
        :set ($targets->$target) true
    }
    :local index 0
    :foreach target,value in=$targets do={
        /ip/firewall/address-list/add list=("sdwan-probes-" . $wn) address=$target comment=("sdwan:v1:probe-address:" . $wn . ":" . $index)
        :set index ($index + 1)
    }
    :set ($marks->("sdwan-probe-" . $wn)) true
    :local mark ("sdwan-in-" . $wn)
    :set ($marks->$mark) true
    :local tag ("sdwan:v1:in:" . $wn)
    :local id [$ensure tag=$tag chain=sdwan-pre]
    /ip/firewall/mangle/set $id action=mark-connection in-interface=($w->"interface") connection-state=new connection-mark=no-mark new-connection-mark=$mark passthrough=yes disabled=no
    :set ($wanted->$tag) true; :set order ($order,$id)
    :set tag ("sdwan:v1:wan-return:" . $wn)
    :set id [$ensure tag=$tag chain=sdwan-pre]
    /ip/firewall/mangle/set $id action=return in-interface=($w->"interface") disabled=no
    :set ($wanted->$tag) true; :set order ($order,$id)
}
# Local destinations must not be sent to a provider by restored connection marks.
:foreach chain in={"sdwan-pre";"sdwan-output"} do={
    :local tag ("sdwan:v1:local-router:" . $chain)
    :local id [$ensure tag=$tag chain=$chain]
    /ip/firewall/mangle/set $id action=return dst-address-type=local disabled=no
    :set ($wanted->$tag) true; :set order ($order,$id)
    :set tag ("sdwan:v1:local-net:" . $chain)
    :set id [$ensure tag=$tag chain=$chain]
    /ip/firewall/mangle/set $id action=return dst-address-list=sdwan-local disabled=no
    :set ($wanted->$tag) true; :set order ($order,$id)
    :foreach w in=($cfg->"wans") do={
        :set tag ("sdwan:v1:reply:" . $chain . ":" . ($w->"name"))
        :set id [$ensure tag=$tag chain=$chain]
        /ip/firewall/mangle/set $id action=mark-routing connection-mark=("sdwan-in-" . ($w->"name")) new-routing-mark=($w->"probe_table") passthrough=no disabled=no
        :set ($wanted->$tag) true; :set order ($order,$id)
    }
}
# Groups are owned address lists. Rebuild only SDWAN entries above.
:foreach groupName,members in=($cfg->"groups") do={
    :local index 0
    :foreach member in=$members do={
        /ip/firewall/address-list/add list=("sdwan-group-" . $groupName) address=$member comment=("sdwan:v1:group:" . $groupName . ":" . $index)
        :set index ($index + 1)
    }
}
# Explicit priorities first, legacy source policies next, default always last.
:foreach p in=[$sdwanOrderPolicies policies=($cfg->"policies")] do={
    :local pn ($p->"name")
    :local policyChain ("sdwan-p-" . $pn)
    :local jumpTag ("sdwan:v1:policy-jump:" . $pn)
    /ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment=$jumpTag]
    :local jumpID [$ensure tag=$jumpTag chain="sdwan-pre"]
    /ip/firewall/mangle/set $jumpID action=jump jump-target=$policyChain connection-mark=no-mark connection-state=established,related,new disabled=no
    $sdwanApplyPolicyMatch rule=$jumpID policy=$p
    :set ($wanted->$jumpTag) true; :set order ($order,$jumpID)
    :foreach wn in=($p->"wans") do={
        :local mark ("sdwan-out-" . $pn . ":" . $wn)
        :set ($marks->$mark) true
        :local tag ("sdwan:v1:classify:" . $pn . ":" . $wn)
        # Fresh selector objects cannot retain constraints from an earlier edit.
        /ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment=$tag]
        :local id [$ensure tag=$tag chain=$policyChain]
        /ip/firewall/mangle/set $id action=mark-connection connection-mark=no-mark connection-state=established,related,new new-connection-mark=$mark passthrough=yes disabled=yes
        :set ($wanted->$tag) true; :set order ($order,$id)
    }
    # Only matching unmarked flows reach this chain; its last rule fails closed.
    :local tag ("sdwan:v1:guard:" . $pn)
    /ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment=$tag]
    :local id [$ensure tag=$tag chain=$policyChain]
    /ip/firewall/mangle/set $id action=mark-routing connection-mark=no-mark new-routing-mark=($p->"table") passthrough=no
    /ip/firewall/mangle/enable $id
    :set ($wanted->$tag) true; :set order ($order,$id)
}
# Optional egress NAT/accept is a property of any WAN, with exact policy marks.
# Legacy VPN-wide flags remain readable but are not emitted by new configuration.
:local wanFlag do={
    :foreach key,value in=$wan do={ :if ($key = $flag) do={ :return $value } }
    :if (($wan->"kind") = "vpn") do={ :return ((($cfg->"vpn_egress")->$flag) = true) }
    :return false
}
/ip/firewall/nat/remove [/ip/firewall/nat/find where comment~"^sdwan:v1:egress:"]
/ip/firewall/filter/remove [/ip/firewall/filter/find where comment~"^sdwan:v1:egress:"]
:global sdwanForwardAnchor
:foreach p in=($cfg->"policies") do={
    :foreach wn in=($p->"wans") do={
        :foreach w in=($cfg->"wans") do={ :if (($w->"name") = $wn) do={
            :local mark ("sdwan-out-" . ($p->"name") . ":" . $wn)
            :local tag ("sdwan:v1:egress:" . ($p->"name") . ":" . $wn)
            :if ([$wanFlag cfg=$cfg wan=$w flag="masquerade"]) do={ /ip/firewall/nat/add chain=srcnat out-interface=($w->"interface") connection-mark=$mark action=masquerade comment=$tag }
            :if ([$wanFlag cfg=$cfg wan=$w flag="allow_selected_forward"]) do={
                :local before [$sdwanForwardAnchor]
                :if ([:len $before] = 0) do={ /ip/firewall/filter/add chain=forward out-interface=($w->"interface") connection-mark=$mark connection-state=new,established,related action=accept comment=$tag } else={ /ip/firewall/filter/add chain=forward out-interface=($w->"interface") connection-mark=$mark connection-state=new,established,related action=accept comment=$tag place-before=$before }
            }
        } }
    }
}
# Existing marked flows retain their WAN until explicitly removed during a policy transition.
:foreach p in=($cfg->"policies") do={
    :foreach wn in=($p->"wans") do={
        :local table ""
        :foreach w in=($cfg->"wans") do={ :if (($w->"name") = $wn) do={ :set table ($w->"probe_table") } }
        :foreach chain in={"sdwan-pre";"sdwan-output"} do={
            :local tag ("sdwan:v1:flow:" . $chain . ":" . ($p->"name") . ":" . $wn)
            :local id [$ensure tag=$tag chain=$chain]
            /ip/firewall/mangle/set $id action=mark-routing connection-mark=("sdwan-out-" . ($p->"name") . ":" . $wn) new-routing-mark=$table passthrough=no disabled=no
            :set ($wanted->$tag) true; :set order ($order,$id)
        }
    }
}
# Keep health probes out of router-session cleanup. Address lists also support
# DNS targets; DNS probes reserve the server, not the name being queried.
:foreach w in=($cfg->"wans") do={
    :local wn ($w->"name")
    :foreach previous in=[:toarray ("no-mark,sdwan-router-" . $wn)] do={
        :local tag ("sdwan:v1:probe-classify:" . $wn . ":" . $previous)
        :local id [$ensure tag=$tag chain=sdwan-output]
        /ip/firewall/mangle/set $id action=mark-connection src-address=(($w->"address") . "/32") dst-address-list=("sdwan-probes-" . $wn) connection-mark=$previous new-connection-mark=("sdwan-probe-" . $wn) passthrough=yes disabled=((($w->"kind") != "static") && (!($w->"ready")))
        :set ($wanted->$tag) true; :set order ($order,$id)
    }
    :local tag ("sdwan:v1:probe-route:" . $wn)
    :local id [$ensure tag=$tag chain=sdwan-output]
    /ip/firewall/mangle/set $id action=mark-routing connection-mark=("sdwan-probe-" . $wn) new-routing-mark=($w->"probe_table") passthrough=no disabled=no
    :set ($wanted->$tag) true; :set order ($order,$id)
}
# Router-originated probes and explicitly bound sockets retain their configured source WAN.
:foreach w in=($cfg->"wans") do={
    :local routerMark ("sdwan-router-" . ($w->"name"))
    :set ($marks->$routerMark) true
    :local tag ("sdwan:v1:router-reply:" . ($w->"name"))
    :local id [$ensure tag=$tag chain=sdwan-output]
    /ip/firewall/mangle/set $id action=mark-routing connection-mark=$routerMark new-routing-mark=($w->"probe_table") passthrough=no disabled=no
    :set ($wanted->$tag) true; :set order ($order,$id)
    :set tag ("sdwan:v1:source:" . ($w->"name"))
    :set id [$ensure tag=$tag chain=sdwan-output]
    /ip/firewall/mangle/set $id action=mark-routing src-address=(($w->"address") . "/32") new-routing-mark=($w->"probe_table") passthrough=no disabled=((($w->"kind") != "static") && (!($w->"ready")))
    :set ($wanted->$tag) true; :set order ($order,$id)
    # This runs before source NAT. Forwarded LAN packets are not src-address-type=local.
    :set tag ("sdwan:v1:router-origin:" . ($w->"name"))
    :set id [$ensure tag=$tag chain=sdwan-post]
    /ip/firewall/mangle/set $id action=mark-connection src-address-type=local out-interface=($w->"interface") connection-mark=no-mark new-connection-mark=$routerMark passthrough=yes disabled=no
    :set ($wanted->$tag) true; :set order ($order,$id)
}
:foreach chain in={"prerouting";"output";"postrouting"} do={
    :local target "sdwan-pre"
    :if ($chain = "output") do={ :set target "sdwan-output" }
    :if ($chain = "postrouting") do={ :set target "sdwan-post" }
    :local tag ("sdwan:v1:jump:" . $chain)
    :local id [$ensure tag=$tag chain=$chain]
    /ip/firewall/mangle/set $id action=jump jump-target=$target disabled=no
    :set ($wanted->$tag) true
}
# Reconcile stale rules before ordering the complete new chain.
:foreach id in=[/ip/firewall/mangle/find where comment~"^sdwan:v1:"] do={ :if ((!([/ip/firewall/mangle/get $id comment] ~ "^sdwan:v1:(overlay|vpn):")) && (($wanted->[/ip/firewall/mangle/get $id comment]) != true)) do={ /ip/firewall/mangle/remove $id } }
:local anchor [:pick [/ip/firewall/mangle/find where dynamic=no] 0]
:for i from=([:len $order] - 1) to=0 step=-1 do={
    :local id [:tostr ($order->$i)]
    :if ($id != [:tostr $anchor]) do={ /ip/firewall/mangle/move $id destination=$anchor }
    :set anchor $id
}
:local out [/ip/firewall/mangle/find where comment="sdwan:v1:jump:output"]
:local post [/ip/firewall/mangle/find where comment="sdwan:v1:jump:postrouting"]
/ip/firewall/mangle/move $post destination=$anchor
/ip/firewall/mangle/move $out destination=$post
/ip/firewall/mangle/move [/ip/firewall/mangle/find where comment="sdwan:v1:jump:prerouting"] destination=$out
# Retire only marks whose policy/WAN was removed from this configuration.
:local retired 0
:foreach id in=[/ip/firewall/connection/find where connection-mark~"^sdwan-"] do={
    :onerror expired in={ :if (($marks->[/ip/firewall/connection/get $id connection-mark]) != true) do={ /ip/firewall/connection/remove $id; :set retired ($retired + 1) } } do={
        :if ([:len [/ip/firewall/connection/find where .id=$id]] > 0) do={ :error $expired }
    }
}

# Selector/group/order edits reclassify managed client flows. Ingress, router
# sessions and probes are preserved; WAN failovers keep their scoped cleanup.
:if ($classificationChanged) do={
    :local count $retired
    :foreach policy in=($oldConfig->"policies") do={
        :foreach wn in=($policy->"wans") do={
            :local mark ("sdwan-out-" . ($policy->"name") . ":" . $wn)
            :foreach cid in=[/ip/firewall/connection/find where connection-mark=$mark] do={
                :onerror expired in={ /ip/firewall/connection/remove $cid; :set count ($count + 1) } do={ :if ([:len [/ip/firewall/connection/find where .id=$cid]] > 0) do={ :error $expired } }
            }
        }
    }
    :if ([:typeof $sdwanConntrackRemoved] != "num") do={ :set sdwanConntrackRemoved 0 }
    :set sdwanConntrackRemoved ($sdwanConntrackRemoved + $count)
    :local event [:toarray ""]
    :set ($event->"type") "reclassify"; :set ($event->"reason") "policy selectors/groups/order changed"; :set ($event->"removed") $count
    $sdwanRecordEvent event=$event revision=($cfg->"revision")
    :log warning ("SDWAN policy selectors changed; managed client connections removed=" . $count)
} else={
    :if ($retired > 0) do={
        :if ([:typeof $sdwanConntrackRemoved] != "num") do={ :set sdwanConntrackRemoved 0 }
        :set sdwanConntrackRemoved ($sdwanConntrackRemoved + $retired)
        :local event [:toarray ""]
        :set ($event->"type") "retire"; :set ($event->"reason") "policy/WAN removed"; :set ($event->"removed") $retired
        $sdwanRecordEvent event=$event revision=($cfg->"revision")
    }
}
