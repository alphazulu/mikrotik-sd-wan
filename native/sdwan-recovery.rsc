# Confirmed configuration only. The inert script record is data, never executed.
# Two file slots preserve the previous committed payload while writing a new one.
# MD5 detects accidental corruption; it is not an authentication mechanism.
:global sdwanRecoveryRecord do={
    :local ids [/system/script/find where name="sdwan-confirmed-record"]
    :if ([:len $ids] = 0) do={ :return [:toarray ""] }
    :if (([:len $ids] != 1) || ([/system/script/get $ids comment] != "sdwan:v1:confirmed-data")) do={ :error "confirmed record name collision" }
    :local text [/system/script/get $ids source]
    :if ([:pick $text 0 1] != "#") do={ :error "invalid confirmed record encoding" }
    :local record [:deserialize from=json options=json.no-string-conversion value=[:pick $text 1 [:len $text]]]
    :if ((($record->"format") != 1) || (($record->"identity") != [/system/identity/get name]) || ([:len ($record->"token")] != 24) || ([:len ($record->"digest")] != 32) || ([:typeof ($record->"bytes")] != "num") || (($record->"bytes") < 2) || (($record->"bytes") > 60000)) do={ :error "invalid confirmed record" }
    :if ((($record->"slot") != "sdwan-confirmed-a.json") && (($record->"slot") != "sdwan-confirmed-b.json")) do={ :error "invalid confirmed slot" }
    :return $record
}
:global sdwanRecoveryLoad do={
    :local ids [/file/find where name=($dir . ($record->"slot"))]
    :if ([:len $ids] != 1) do={ :error "confirmed configuration copy missing" }
    :local raw [/file/get $ids contents]
    :if (([:len $raw] != ($record->"bytes")) || ([:convert $raw from=raw transform=md5 to=hex] != ($record->"digest"))) do={ :error "confirmed configuration copy corrupt" }
    :local cfg [:deserialize from=json options=json.no-string-conversion value=$raw]
    :if ((($cfg->"schema_version") != 1) || (($cfg->"revision") != ($record->"revision"))) do={ :error "confirmed configuration copy has wrong revision" }
    :return $raw
}
:global sdwanRecoveryPrepare do={
    :global sdwanRecoveryRecord
    :global sdwanRecoveryLoad
    :global sdwanRecoveryPending
    :local cfg [:deserialize from=json options=json.no-string-conversion value=$raw]
    :if ((($cfg->"schema_version") != 1) || (($cfg->"revision") != $revision) || ([:len $raw] > 60000)) do={ :error "cannot confirm a different configuration" }
    :local old [$sdwanRecoveryRecord]
    :local digest [:convert $raw from=raw transform=md5 to=hex]
    :if (($old->"token") = $token) do={
        :if ((($old->"digest") != $digest) || ([$sdwanRecoveryLoad dir=$dir record=$old] != $raw)) do={ :error "confirmed token content changed" }
        :return true
    }
    :local now ([:tonsec [/system/resource/get uptime]] / 1000000000)
    :if (($sdwanRecoveryPending->"token") != $token) do={
        :local slot "sdwan-confirmed-a.json"
        :if (($old->"slot") = $slot) do={ :set slot "sdwan-confirmed-b.json" }
        :local id [/file/find where name=($dir . $slot)]
        :if ([:len $id] = 0) do={ /file/add name=($dir . $slot) type=file; :set id [/file/find where name=($dir . $slot)] }
        /file/set $id contents=$raw
        :if ([/file/get $id contents] != $raw) do={ :error "confirmed slot write verification failed" }
        # RAM only: a restart before this settling period cannot confirm it.
        :set sdwanRecoveryPending {"format"=1;"token"=$token;"slot"=$slot;"digest"=$digest;"bytes"=[:len $raw];"revision"=$revision;"identity"=[/system/identity/get name];"started"=$now}
        :return false
    }
    :if ((($sdwanRecoveryPending->"digest") != $digest) || (($sdwanRecoveryPending->"revision") != $revision)) do={ :error "configuration changed while checkpoint was settling" }
    # RouterOS documents up to 40 seconds of file write-back caching on NAND.
    # This is an infrequent deployment barrier, never a per-tick flash write.
    :if (($now - ($sdwanRecoveryPending->"started")) < 45) do={ :return false }
    :if ([$sdwanRecoveryLoad dir=$dir record=$sdwanRecoveryPending] != $raw) do={ :error "settled checkpoint differs from active configuration" }
    :return true
}
:global sdwanRecoveryCommit do={
    :global sdwanRecoveryRecord
    :global sdwanRecoveryPrepare
    :global sdwanRecoveryLoad
    :global sdwanRecoveryPending
    :local old [$sdwanRecoveryRecord]
    :if (($old->"token") = $token) do={
        :if ([$sdwanRecoveryLoad dir=$dir record=$old] != $raw) do={ :error "confirmed token content changed" }
        :return ""
    }
    :if (![$sdwanRecoveryPrepare dir=$dir token=$token raw=$raw revision=$revision]) do={ :error "checkpoint is still settling" }
    :local record $sdwanRecoveryPending
    :set ($record->"started")
    :local text ("#" . [:serialize to=json value=$record options=json.no-string-conversion])
    :local id [/system/script/find where name="sdwan-confirmed-record"]
    :if ([:len $id] = 0) do={ /system/script/add name=sdwan-confirmed-record source=$text policy=read comment="sdwan:v1:confirmed-data" } else={ /system/script/set $id source=$text policy=read }
    :if ([$sdwanRecoveryLoad dir=$dir record=[$sdwanRecoveryRecord]] != $raw) do={ :error "confirmed record verification failed" }
}
:global sdwanRecoveryGuard do={
    :global sdwanRecoveryRecord
    :global sdwanRecoveryLoad
    :local record [$sdwanRecoveryRecord]
    :local pointer [/file/find where name=($dir . "sdwan-deploy-current.json")]
    :local phase "legacy"
    :local state [:toarray ""]
    :if ([:len $pointer] > 0) do={
        :local link [:deserialize from=json value=[/file/get $pointer contents]]
        :set state [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($link->"path")] contents]]
        :set phase ($state->"phase")
        :if (($phase != "committed") && ($phase != "rolled-back") && ($phase != "preparation-failed")) do={
            :if ([:len [/ip/firewall/address-list/find where list="sdwan-deployment-boot" and dynamic=yes and comment=("sdwan:v1:deployment:" . ($state->"token"))]] = 1) do={ :return false }
            :error "unconfirmed deployment awaits router-local recovery"
        }
    }
    # Legacy manual installations have no confirmed checkpoint. Never seed it
    # from staging: the next protected apply creates it after fresh API ACK.
    :if ([:len $record] = 0) do={ :return true }
    :if (($phase = "committed") && (($state->"token") != ($record->"token"))) do={ :error "deployment and confirmed record disagree" }
    :local id [/file/find where name=($dir . "sdwan-active.json")]
    :local raw ""
    :if ([:len $id] = 1) do={ :set raw [/file/get $id contents] }
    :if (([:len $raw] != ($record->"bytes")) || ([:convert $raw from=raw transform=md5 to=hex] != ($record->"digest"))) do={
        :set raw [$sdwanRecoveryLoad dir=$dir record=$record]
        :if ([:len $id] = 0) do={ /file/add name=($dir . "sdwan-active.json") type=file; :set id [/file/find where name=($dir . "sdwan-active.json")] }
        /file/set $id contents=$raw
        :if ([/file/get $id contents] != $raw) do={ :error "active recovery write verification failed" }
        :log warning "SDWAN restored the confirmed configuration; SLA probes must warm up"
    }
    :return true
}
:global sdwanRecoveryLoaded 1
