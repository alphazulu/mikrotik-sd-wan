:if ([/system/script/job/print count-only where script="sdwan-deploy-watchdog"] > 1) do={ :return }
:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
:local link [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "sdwan-deploy-current.json")] contents]]
:local path ($link->"path")
:local s [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=$path] contents]]
:local now ([:tonsec [/system/resource/get uptime]] / 1000000000)
:global sdwanDeployHeartbeatJSON
:local heartbeat [:toarray ""]
:set ($heartbeat->"token") ($s->"token")
:set ($heartbeat->"uptime_seconds") $now
:set sdwanDeployHeartbeatJSON [:serialize to=json value=$heartbeat options=json.no-string-conversion]
:local save do={ /file/set [/file/find where name=$path] contents=[:serialize to=json value=$value options=json.no-string-conversion] }
:local restore do={
    :foreach objectName,archive in=$previous do={
        :local id [/file/find where name=$objectName]
        :if ($archive = "") do={ :if ([:len $id] > 0) do={ /file/remove $id } } else={
            :local text [/file/get [/file/find where name=$archive] contents]
            :if ([:len $id] = 0) do={ /file/add name=$objectName type=file contents=$text } else={ /file/set $id contents=$text }
        }
    }
}
:local phase ($s->"phase")
:if (($phase = "committed") || ($phase = "rolled-back") || ($phase = "preparation-failed") || ($phase = "recovery-failed")) do={
    /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
    :return
}
:if ($phase = "restore-reboot") do={
    :if ([:tonsec [/system/resource/get uptime]] < ($s->"restore_ticks")) do={
        $restore previous=($s->"previous")
        :set ($s->"phase") "rolled-back"
        :set ($s->"restored_at") $now
        $save path=$path value=$s
        /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
        :log warning "SDWAN deploy full configuration and package restored"
    }
    :return
}
:local reason ""
:if ([:tonsec [/system/resource/get uptime]] < ($s->"started_ticks")) do={ :set reason "router restarted before deployment confirmation" }
:if ($phase = "failed") do={ :set reason ($s->"error") }
:if ($now > ($s->"deadline")) do={ :set reason "deployment confirmation deadline exceeded" }
:local abort [/file/find where name=($dir . "sdwan-deploy-abort.json")]
:if ([:len $abort] > 0) do={ :local a [:deserialize from=json options=json.no-string-conversion value=[/file/get $abort contents]]; :if (($a->"token") = ($s->"token")) do={ :set reason "deployment aborted by configuration client" } }
:local ready false
:local selected "none"
:if (($phase = "checking") || ($phase = "await-confirm")) do={
    :if (($s->"operation") = "rollback") do={ :set ready ([:len [/system/scheduler/find where name="sdwan-controller"]] = 0) } else={
        :global sdwanStatusJSON
        :if ([:typeof $sdwanStatusJSON] = "str") do={
            :local status [:deserialize from=json options=json.no-string-conversion value=$sdwanStatusJSON]
            :if ([:typeof ($status->"error")] = "str") do={ :set reason ("controller error: " . ($status->"error")) }
            :if ((($status->"revision") = ($s->"revision")) && ([:typeof ($status->"states")] = "array") && ([:typeof ($status->"uptime_seconds")] = "num") && (($now - ($status->"uptime_seconds")) <= 5)) do={
                :set ready true
                :set selected (($status->"selected")->($s->"default_policy"))
            }
        }
    }
}
:if ($reason != "") do={
    :set ($s->"phase") "restoring"
    :set ($s->"error") $reason
    $save path=$path value=$s
    /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-controller"]
    :foreach objectName in={"sdwan-deploy-worker";"sdwan-controller"} do={ :foreach id in=[/system/script/job/find where script=$objectName] do={ :onerror gone in={ /system/script/job/remove $id } do={ :if ([:len [/system/script/job/find where .id=$id]] > 0) do={ :error $gone } } } }
    :onerror failure in={
        :if (($s->"backup_ready") != true) do={ :error "encrypted recovery backup is not ready" }
        $restore previous=($s->"previous")
        :set ($s->"phase") "restore-reboot"
        :set ($s->"restore_ticks") [:tonsec [/system/resource/get uptime]]
        $save path=$path value=$s
        :log warning "SDWAN deploy restoring encrypted backup and rebooting"
        /system/backup/load name=($s->"backup_name") password=($s->"password")
    } do={
        :set ($s->"phase") "recovery-failed"
        :set ($s->"error") ("native recovery failed: " . $failure)
        $save path=$path value=$s
        /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-watchdog"]
        :log error "SDWAN deploy native recovery failed; inspect recovery journal"
    }
    :return
}
:if ($phase = "prepared") do={
    :local id [/file/find where name=($dir . "sdwan-deploy-arm.json")]
    :if (([:len $id] > 0) && (($s->"backup_ready") = true)) do={
        :local arm [:deserialize from=json options=json.no-string-conversion value=[/file/get $id contents]]
        :if (($arm->"token") = ($s->"token")) do={
            :set ($s->"phase") "armed"
            $save path=$path value=$s
            /system/scheduler/enable [/system/scheduler/find where name="sdwan-deploy-worker"]
        }
    }
    :return
}
:if ($ready) do={
    :if ($phase = "checking") do={ :set ($s->"phase") "await-confirm"; $save path=$path value=$s }
    :local ack [/file/find where name=($dir . "sdwan-deploy-ack.json")]
    :if ([:len $ack] > 0) do={
        :local a [:deserialize from=json options=json.no-string-conversion value=[/file/get $ack contents]]
        :if ((($a->"token") = ($s->"token")) && ((($s->"operation") = "rollback") || (([:typeof $selected] = "str") && ($selected != "none")))) do={
            :set ($s->"phase") "committed"
            :set ($s->"committed_at") $now
            $save path=$path value=$s
            /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
            :log info "SDWAN deploy committed after fresh management connection confirmation"
        }
    }
}
