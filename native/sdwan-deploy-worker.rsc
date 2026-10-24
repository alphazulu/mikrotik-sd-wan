:if ([/system/script/job/print count-only where script="sdwan-deploy-worker"] > 1) do={ :return }
/system/scheduler/disable [/system/scheduler/find where name="sdwan-deploy-worker"]
:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
:local link [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "sdwan-deploy-current.json")] contents]]
:local path ($link->"path")
:local s [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=$path] contents]]
:if (($s->"phase") != "armed") do={ :return }
:local save do={ /file/set [/file/find where name=$path] contents=[:serialize to=json value=$value options=json.no-string-conversion] }
:set ($s->"phase") "applying"
$save path=$path value=$s
:onerror installError in={
    # Migrate previously persistent baseline metadata before changing the package.
    :if ($dir != "") do={
        :foreach objectName in={"sdwan-backup.json";"sdwan-active.json"} do={
            :if (([:len [/file/find where name=($dir . $objectName)]] = 0) && ([:len [/file/find where name=$objectName]] > 0)) do={
                /file/add name=($dir . $objectName) type=file contents=[/file/get [/file/find where name=$objectName] contents]
            }
        }
    }
    :if (($s->"operation") = "apply") do={ /import file-name=($dir . "sdwan-install.rsc") } else={
        :if ([:len [/file/find where name=($dir . "sdwan-active.json")]] > 0) do={ /file/set [/file/find where name=($dir . "sdwan-config.json")] contents=[/file/get [/file/find where name=($dir . "sdwan-active.json")] contents] }
        /import file-name=($dir . "sdwan-rollback.rsc")
    }
    # The watchdog may have claimed a timed-out transaction while import ran.
    :set s [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=$path] contents]]
    :if (($s->"phase") = "applying") do={ :set ($s->"phase") "checking"; $save path=$path value=$s }
} do={
    :set s [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=$path] contents]]
    :if (($s->"phase") = "applying") do={ :set ($s->"phase") "failed"; :set ($s->"error") $installError; $save path=$path value=$s }
}
