:if ([/system/script/job/print count-only where script="sdwan-deploy-watchdog"] > 1) do={ :return "" }
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
            :if ([:len $id] = 0) do={ /file/add name=$objectName type=file; :set id [/file/find where name=$objectName] }
            /file/set $id contents=$text
        }
    }
}
:local phase ($s->"phase")
:local sameBoot ([:len [/ip/firewall/address-list/find where list="sdwan-deployment-boot" and dynamic=yes and comment=("sdwan:v1:deployment:" . ($s->"token"))]] = 1)
:if (($phase = "committed") || ($phase = "rolled-back") || ($phase = "preparation-failed") || ($phase = "recovery-failed")) do={
    /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
    :return ""
}
:if ($phase = "restore-reboot") do={
    :if ((!$sameBoot) || ([:tonsec [/system/resource/get uptime]] < ($s->"restore_ticks"))) do={
        :global sdwanRestorePending
        :if (($sdwanRestorePending->"token") != ($s->"token")) do={
            $restore previous=($s->"previous")
            :set sdwanRestorePending {"token"=($s->"token");"started"=$now}
            :return ""
        }
        :if (($now - ($sdwanRestorePending->"started")) < 45) do={ :return "" }
        :set ($s->"phase") "rolled-back"
        :set ($s->"restored_at") $now
        $save path=$path value=$s
        /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
        :log warning "SDWAN deploy full configuration and package restored"
    }
    :return ""
}
/import file-name=($dir . "sdwan-recovery.rsc")
:global sdwanRecoveryRecord
:global sdwanRecoveryLoad
:global sdwanRecoveryCommit
:global sdwanRecoveryPrepare
:local confirmed [$sdwanRecoveryRecord]
# The inert record is written only after fresh API ACK. It is the commit point
# if power was lost before the subsequent journal update reached storage.
:if ((($s->"operation") = "apply") && (($confirmed->"token") = ($s->"token"))) do={
    :local verified [$sdwanRecoveryLoad dir=$dir record=$confirmed]
    :if ($phase != "committed") do={
        :set phase "committed"; :set ($s->"phase") $phase
        $save path=$path value=$s
    }
    /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
    :return ""
}
:local reason ""
:if ((!$sameBoot) || ([:tonsec [/system/resource/get uptime]] < ($s->"started_ticks"))) do={ :set reason "router restarted before deployment confirmation" }
:if ($phase = "failed") do={ :set reason ($s->"error") }
:if ($now > ($s->"deadline")) do={ :set reason "deployment confirmation deadline exceeded" }
:local abort [/file/find where name=($dir . "sdwan-deploy-abort.json")]
:if ([:len $abort] > 0) do={ :local a [:deserialize from=json options=json.no-string-conversion value=[/file/get $abort contents]]; :if (($a->"token") = ($s->"token")) do={ :set reason "deployment aborted by configuration client" } }
:local ready false
:local selected "none"
:local explicitlyClosed false
:if (($phase = "checking") || ($phase = "await-confirm")) do={
    :if (($s->"operation") = "rollback") do={ :set ready ([:len [/system/scheduler/find where name="sdwan-controller"]] = 0) } else={
        :global sdwanStatusJSON
        :if ([:typeof $sdwanStatusJSON] = "str") do={
            :local status [:deserialize from=json options=json.no-string-conversion value=$sdwanStatusJSON]
            :if ([:typeof ($status->"error")] = "str") do={ :set reason ("controller error: " . ($status->"error")) }
            :if ((($status->"revision") = ($s->"revision")) && ([:typeof ($status->"states")] = "array") && ([:typeof ($status->"uptime_seconds")] = "num") && (($now - ($status->"uptime_seconds")) <= 5)) do={
                :set ready true
                :set selected (($status->"selected")->($s->"default_policy"))
                :if ((($s->"allow_no_default") = true) && (($status->"default_admission_closed") = true)) do={ :set explicitlyClosed true }
            }
        }
    }
}
:if ($reason != "") do={
    # Before arm there are no forwarding mutations. A failed/incomplete backup
    # needs only package restoration, not loading a backup that does not exist.
    :if (($phase = "prepared") && (($s->"backup_ready") != true)) do={
        $restore previous=($s->"previous")
        :set ($s->"phase") "preparation-failed"; :set ($s->"error") $reason
        $save path=$path value=$s
        /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
        :return ""
    }
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
    :return ""
}
:if ($phase = "prepared") do={
    :if (($s->"backup_ready") != true) do={
        :if (([:typeof ($s->"backup_written_at")] != "num") || (($now - ($s->"backup_written_at")) < 45)) do={ :return "" }
        :local backup [/file/find where name=(($s->"backup_name") . ".backup")]
        :if (([:len $backup] != 1) || (($s->"backup_bytes") < 128) || ([/file/get $backup size] != ($s->"backup_bytes"))) do={ :error "encrypted recovery backup size changed while settling" }
        :set ($s->"backup_ready") true
        $save path=$path value=$s
    }
    # The client seals the full framework archive map before replacing payload
    # files. Keep that map on storage before any package can become partial.
    :if (([:typeof ($s->"manifest_written_at")] = "num") && (($s->"manifest_ready") != true)) do={
        :if (($now - ($s->"manifest_written_at")) < 45) do={ :return "" }
        :set ($s->"manifest_ready") true
        $save path=$path value=$s
    }
    :if (($s->"manifest_ready") != true) do={ :return "" }
    :local id [/file/find where name=($dir . "sdwan-deploy-arm.json")]
    :if (([:len $id] > 0) && (($s->"backup_ready") = true)) do={
        :local arm [:deserialize from=json options=json.no-string-conversion value=[/file/get $id contents]]
        :if (($arm->"token") = ($s->"token")) do={
            :set ($s->"phase") "armed"
            $save path=$path value=$s
            /system/scheduler/enable [/system/scheduler/find where name="sdwan-deploy-worker"]
        }
    }
    :return ""
}
# Do not request the API confirmation until the inactive payload has settled.
:if ($ready && ($phase = "checking") && (($s->"operation") = "apply")) do={
    :set ready [$sdwanRecoveryPrepare dir=$dir token=($s->"token") revision=($s->"revision") raw=[/file/get [/file/find where name=($dir . "sdwan-active.json")] contents]]
}
:if ($ready) do={
    :if ($phase = "checking") do={ :set ($s->"phase") "await-confirm"; $save path=$path value=$s }
    :local ack [/file/find where name=($dir . "sdwan-deploy-ack.json")]
    :if ([:len $ack] > 0) do={
        :local a [:deserialize from=json options=json.no-string-conversion value=[/file/get $ack contents]]
        :if ((($a->"token") = ($s->"token")) && ((($s->"operation") = "rollback") || (([:typeof $selected] = "str") && ($selected != "none")) || $explicitlyClosed)) do={
            :if (($s->"operation") = "apply") do={
                $sdwanRecoveryCommit dir=$dir token=($s->"token") revision=($s->"revision") raw=[/file/get [/file/find where name=($dir . "sdwan-active.json")] contents]
            }
            :set ($s->"phase") "committed"
            :set ($s->"committed_at") $now
            $save path=$path value=$s
            /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker" or name="sdwan-deploy-watchdog"]
            :log info "SDWAN deploy committed after fresh management connection confirmation"
        }
    }
}
