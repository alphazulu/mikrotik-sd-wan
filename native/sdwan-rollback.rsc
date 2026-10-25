:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
# Restore takeover flags from first install; remove only managed SDWAN objects.
:local sched [/system/scheduler/find where name="sdwan-controller"]
:if ([:len $sched] > 0) do={ /system/scheduler/disable $sched }
:local n 0
:while (([/system/script/job/print count-only where script="sdwan-controller"] > 0) && ($n < 50)) do={ :delay 100ms; :set n ($n + 1) }
:if ([/system/script/job/print count-only where script="sdwan-controller"] > 0) do={ :error "controller still busy" }
:if ([:len [/routing/ospf/instance/find where comment="sdwan:v1:overlay:instance"]] > 0) do={
    :global sdwanOverlayInstall
    /import file-name=($dir . "sdwan-overlay.rsc")
    :local empty [:toarray ""]
    $sdwanOverlayInstall cfg=$empty
}
:global sdwanStrictCancel
/import file-name=($dir . "sdwan-links.rsc")
/system/scheduler/remove [/system/scheduler/find where name="sdwan-strict-dispatch" and comment="sdwan:v1:strict"]
$sdwanStrictCancel
/system/script/remove [/system/script/find where comment="sdwan:v1:strict"]
:local backup [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "sdwan-backup.json")] contents]]
:foreach tag,disabled in=($backup->"routes") do={ /ip/route/set [/ip/route/find where comment=$tag] disabled=$disabled }
:foreach id,disabled in=($backup->"rules") do={ :if ([:len [/routing/rule/find where .id=$id]] > 0) do={ /routing/rule/set $id disabled=$disabled } }
:if ([:typeof ($backup->"route_selectors")] = "array") do={
    :foreach id,item in=($backup->"route_selectors") do={
        :if ([:len [/ip/route/find where .id=$id]] = 1) do={
            :local actualTable [:tostr [/ip/route/get $id routing-table]]
            :if ($actualTable = "") do={ :set actualTable "main" }
            :if (([:tostr [/ip/route/get $id gateway]] = ($item->"gateway")) && ([:tostr [/ip/route/get $id dst-address]] = ($item->"dst-address")) && ($actualTable = ($item->"routing-table"))) do={ /ip/route/set $id disabled=($item->"disabled") } else={ :log warning "SDWAN rollback skipped a changed adopted route" }
        }
    }
}
:if ([:typeof ($backup->"fasttrack")] = "array") do={
    :foreach id,disabled in=($backup->"fasttrack") do={
        :if ([:len [/ip/firewall/filter/find where .id=$id]] = 1) do={ :if ([/ip/firewall/filter/get $id action] = "fasttrack-connection") do={ /ip/firewall/filter/set $id disabled=$disabled } }
    }
}
:if (([:typeof ($backup->"rp_filter")] = "str") && ([/ip/settings/get rp-filter] = "loose")) do={ /ip/settings/set rp-filter=($backup->"rp_filter") }
:if ([:typeof ($backup->"provider_clients")] = "array") do={
    :global sdwanRestoreProviderClients
    /import file-name=($dir . "sdwan-links.rsc")
    $sdwanRestoreProviderClients entries=($backup->"provider_clients")
}
 :if ([:typeof ($backup->"lte_apns")] = "array") do={
    :global sdwanLTEAPNRestore
    /import file-name=($dir . "sdwan-links.rsc")
    :foreach profileName,entry in=($backup->"lte_apns") do={
        :if (![$sdwanLTEAPNRestore entry=$entry]) do={ :log warning ("SDWAN baseline skipped changed or missing LTE APN " . $profileName) }
    }
}
/ip/firewall/mangle/remove [/ip/firewall/mangle/find where comment~"^sdwan:v1:"]
/ip/firewall/address-list/remove [/ip/firewall/address-list/find where dynamic=no and comment~"^sdwan:v1:"]
:foreach id in=[/ip/firewall/connection/find where connection-mark~"^sdwan-"] do={
    :onerror expired in={ /ip/firewall/connection/remove $id } do={ :if ([:len [/ip/firewall/connection/find where .id=$id]] > 0) do={ :error $expired } }
}
/routing/rule/remove [/routing/rule/find where comment~"^sdwan:v1:"]
/ip/route/remove [/ip/route/find where comment~"^sdwan:v1:"]
/tool/netwatch/remove [/tool/netwatch/find where comment~"^sdwan:v1:"]
/system/scheduler/remove [/system/scheduler/find where name="sdwan-controller"]
/system/script/remove [/system/script/find where name="sdwan-controller"]
:local cfg [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "sdwan-config.json")] contents]]
:foreach w in=($cfg->"wans") do={ /routing/table/remove [/routing/table/find where name=($w->"probe_table")] }
:foreach p in=($cfg->"policies") do={ :if (($p->"table") != "main") do={ /routing/table/remove [/routing/table/find where name=($p->"table")] } }
:global sdwanStatusJSON "{\"controller\":\"disabled and rolled back\"}"
:log warning "SDWAN rolled back to saved baseline"
