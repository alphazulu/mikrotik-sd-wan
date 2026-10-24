# Prepare only: no routing/firewall changes. API may import this bootstrap.
# Payload files are uploaded AFTER this script archives the previous package.
:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
:local request [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "sdwan-deploy-request.json")] contents]]
:local token [:tostr ($request->"token")]
:if (([:len $token] != 24) || (!($token ~ "^[0-9a-f]+\$"))) do={ :error "invalid deployment token" }
:if (($request->"identity") != [/system/identity/get name]) do={ :error "deployment identity mismatch" }
:if (((($request->"operation") != "apply") && (($request->"operation") != "rollback")) || (($request->"timeout_seconds") < 30) || (($request->"timeout_seconds") > 600) || ([:len ($request->"password")] < 32)) do={ :error "invalid deployment request" }
:local pointer ($dir . "sdwan-deploy-current.json")
:if ([:len [/file/find where name=$pointer]] > 0) do={
    :local oldPointer [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=$pointer] contents]]
    :local oldPath ($oldPointer->"path")
    :if ([:len [/file/find where name=$oldPath]] > 0) do={
        :local old [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=$oldPath] contents]]
        :local phase ($old->"phase")
        :if (($phase != "committed") && ($phase != "rolled-back") && ($phase != "preparation-failed") && ($phase != "recovery-failed")) do={ :error "another native deployment is pending" }
    }
}
:local write do={
    :local id [/file/find where name=$path]
    :if ([:len $id] = 0) do={ /file/add name=$path type=file; :set id [/file/find where name=$path] }
    /file/set $id contents=$text
}
:local state $request
:local path ($dir . "sdwan-txn-" . $token . ".json")
:local previous [:toarray ""]
:local index 0
:foreach base in={"sdwan-config.json";"sdwan-active.json";"sdwan-backup.json";"sdwan-controller.rsc";"sdwan-install.rsc";"sdwan-rollback.rsc";"sdwan-dataplane.rsc";"sdwan-links.rsc"} do={
    :local objectNames [:toarray ($dir . $base)]
    :if ($dir != "") do={ :set objectNames ($objectNames,$base) }
    :foreach objectName in=$objectNames do={
        :local archive ""
        :local id [/file/find where name=$objectName]
        :if ([:len $id] > 0) do={
            :set archive ($dir . "sdwan-prev-" . $token . "-" . $index)
            $write path=$archive text=[/file/get $id contents]
            :set index ($index + 1)
        }
        :set ($previous->[:tostr $objectName]) $archive
    }
}
:if ([:len $previous] < 8) do={ :error "previous package manifest is incomplete" }
:set ($state->"previous") $previous
:set ($state->"phase") "prepared"
:set ($state->"started_ticks") [:tonsec [/system/resource/get uptime]]
:set ($state->"deadline") (([:tonsec [/system/resource/get uptime]] / 1000000000) + ($state->"timeout_seconds"))
:set ($state->"backup_name") ($dir . "sdwan-before-" . $token)
:set ($state->"backup_ready") false
$write path=$path text=[:serialize to=json value=$state options=json.no-string-conversion]
:local link [:toarray ""]
:set ($link->"token") $token
:set ($link->"path") $path
$write path=$pointer text=[:serialize to=json value=$link options=json.no-string-conversion]

:local workerSource [/file/get [/file/find where name=($dir . "sdwan-deploy-worker.rsc")] contents]

:local watchdogSource [/file/get [/file/find where name=($dir . "sdwan-deploy-watchdog.rsc")] contents]

:foreach objectName in={"sdwan-deploy-worker";"sdwan-deploy-watchdog"} do={
    :local jobSource $workerSource
    :if ($objectName = "sdwan-deploy-watchdog") do={ :set jobSource $watchdogSource }
    :local id [/system/script/find where name=$objectName]
    :if ([:len $id] = 0) do={ /system/script/add name=$objectName source=$jobSource policy=read,write,policy,test,sensitive,reboot } else={ /system/script/set $id source=$jobSource policy=read,write,policy,test,sensitive,reboot dont-require-permissions=no }
    :set id [/system/scheduler/find where name=$objectName]
    :if ([:len $id] = 0) do={ /system/scheduler/add name=$objectName interval=1s start-time=startup on-event=("/system/script/run " . $objectName) policy=read,write,policy,test,sensitive,reboot disabled=yes } else={ /system/scheduler/set $id interval=1s start-time=startup on-event=("/system/script/run " . $objectName) policy=read,write,policy,test,sensitive,reboot disabled=yes }
}
/system/scheduler/enable [/system/scheduler/find where name="sdwan-deploy-watchdog"]
:onerror backupError in={
    /system/backup/save name=($state->"backup_name") password=($state->"password") encryption=aes-sha256 dont-encrypt=no
    :if ([:len [/file/find where name=(($state->"backup_name") . ".backup")]] != 1) do={ :error "encrypted backup was not created" }
    :set ($state->"backup_ready") true
    $write path=$path text=[:serialize to=json value=$state options=json.no-string-conversion]
} do={
    :set ($state->"phase") "preparation-failed"
    :set ($state->"error") $backupError
    $write path=$path text=[:serialize to=json value=$state options=json.no-string-conversion]
    /system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-watchdog"]
    :error $backupError
}
:log info "SDWAN deploy encrypted backup prepared; waiting for payload and arm token"
