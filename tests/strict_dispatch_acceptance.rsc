# CHR-only contract. The driver must import sdwan-links.rsc and
# sdwan-config-state.rsc first, in the same admin scheduler context.
# Controlled named jobs isolate slot ownership from network timing.
{
:global sdwanStrictDispatchContractJSON
:global sdwanStrictContractRows [:toarray ""]
:global sdwanStrictContractCheck do={
    :global sdwanStrictContractRows
    :global sdwanStrictSequence
    :local row {"case"=$name;"pass"=$ok;"sequence"=$sdwanStrictSequence}
    :set ($sdwanStrictContractRows->[:len $sdwanStrictContractRows]) $row
}
:global sdwanStrictAdoptLegacy do={ :return true }
:global sdwanStrictCancel
:global sdwanStrictDispatch
:global sdwanStrictCommit
:global sdwanStrictStopJob
:global sdwanStrictSlots
:global sdwanStrictResults
:global sdwanStrictDue
:global sdwanStrictGeneration 1
:global sdwanStrictCursor 0
:global sdwanStrictSequence 0
:global sdwanStrictRaw ""
:global sdwanConfigRaw "{\"health\":{\"strict_probe_interval_seconds\":10,\"strict_probe_timeout_ms\":2000}}"
:global sdwanRuntimeWANs [:deserialize from=json options=json.no-string-conversion value="[{\"name\":\"wan1\",\"ready\":true,\"address\":\"198.18.210.1\",\"route_gateway\":\"198.18.210.254\",\"probes\":[{\"name\":\"a\",\"type\":\"http-get\",\"host\":\"198.19.210.10\",\"port\":28081,\"http_expected_body\":\"healthy\\n\"},{\"name\":\"b\",\"type\":\"http-get\",\"host\":\"198.19.210.10\",\"port\":28082,\"http_expected_body\":\"healthy\\n\"},{\"name\":\"c\",\"type\":\"http-get\",\"host\":\"198.19.210.10\",\"port\":28083,\"http_expected_body\":\"healthy\\n\"},{\"name\":\"d\",\"type\":\"http-get\",\"host\":\"198.19.210.10\",\"port\":28081,\"http_expected_body\":\"healthy\\n\"}]}]" ]
$sdwanStrictCancel
:set sdwanStrictResults [:toarray ""]
:set sdwanStrictDue [:toarray ""]
:foreach probe in=((($sdwanRuntimeWANs->0)->"probes")) do={
    /tool/netwatch/add type=tcp-conn host=198.19.210.10 port=28081 disabled=yes comment=("sdwan:v1:probe:wan1:" . ($probe->"name"))
}
:foreach prefix in={"sdwan-strict-worker-";"sdwan-strict-timeout-"} do={
    :foreach slot in={0;1} do={ /system/script/add name=($prefix . $slot) source=":delay 10s" policy=read,write,policy,test,sensitive }
}
$sdwanStrictDispatch
:delay 100ms
$sdwanStrictContractCheck name="two distinct slots" ok=(([:len $sdwanStrictSlots] = 2) && ((($sdwanStrictSlots->0)->"key") != (($sdwanStrictSlots->1)->"key")))
:local original ($sdwanStrictSlots->0)
:local other ($sdwanStrictSlots->1)
$sdwanStrictDispatch
$sdwanStrictContractCheck name="unfinished slots retained before deadline" ok=(($sdwanStrictSequence = 2) && ((($sdwanStrictSlots->0)->"token") = ($original->"token")))

# A similarly prefixed foreign job must not be canceled with our exact name.
/system/script/add name=sdwan-strict-worker-0-extra source=":delay 10s" policy=read,write,policy,test,sensitive
:execute script="/system/script/run sdwan-strict-worker-0-extra"
# This timer captures the old token, but deliberately has a different name so
# normal slot recycling cannot stop it. Its callback must fence itself.
/system/script/add name=strict-contract-old-timer source=":global sdwanStrictTimeout; \$sdwanStrictTimeout slot=(0)" policy=read,write,policy,test,sensitive
:execute script="/system/script/run strict-contract-old-timer"
:delay 100ms
:local committed [$sdwanStrictCommit slot=(0) job=$original up=(true) reason="verified"]
$sdwanStrictContractCheck name="current result committed" ok=$committed
$sdwanStrictDispatch
:local replacement ($sdwanStrictSlots->0)
$sdwanStrictContractCheck name="finished slot recycled before timeout" ok=((($replacement->"token") != ($original->"token")) && ($sdwanStrictSequence = 3))
:if (($replacement->"token") = ($original->"token")) do={
    $sdwanStrictCancel
    :set sdwanStrictDispatchContractJSON [:serialize to=json value=$sdwanStrictContractRows options=json.no-string-conversion]
 } else={
$sdwanStrictContractCheck name="completed evidence retained" ok=((($sdwanStrictResults->($original->"key"))->"up") = true)
$sdwanStrictContractCheck name="other unfinished slot retained" ok=((($sdwanStrictSlots->1)->"token") = ($other->"token"))
:local stale [$sdwanStrictCommit slot=(0) job=$original up=(false) reason="late"]
$sdwanStrictContractCheck name="old token rejected" ok=(!$stale)
$sdwanStrictContractCheck name="foreign prefixed job survives" ok=([:len [/system/script/job/find where trace~"/script:sdwan-strict-worker-0-extra(/|\$)"]] > 0)
:delay 2100ms
$sdwanStrictContractCheck name="old timeout cannot clear replacement" ok=((($sdwanStrictSlots->0)->"token") = ($replacement->"token"))
$sdwanStrictContractCheck name="old timeout cannot overwrite success" ok=((($sdwanStrictResults->($original->"key"))->"up") = true)

:foreach field in={"token";"generation";"signature";"source";"gateway";"probe_id"} do={
    :local changed [:deserialize from=json options=json.no-string-conversion value=[:serialize to=json value=$replacement options=json.no-string-conversion]]
    :if (($field = "token") || ($field = "generation")) do={ :set ($changed->$field) (($changed->$field) + 1) } else={ :set ($changed->$field) "changed" }
    :local accepted [$sdwanStrictCommit slot=(0) job=$changed up=(true) reason="invalid"]
    $sdwanStrictContractCheck name=("late result fenced by " . $field) ok=(!$accepted)
}
:local wan ($sdwanRuntimeWANs->0)
:set ($wan->"ready") false
:set ($sdwanRuntimeWANs->0) $wan
:local accepted [$sdwanStrictCommit slot=(0) job=$replacement up=(true) reason="invalid"]
$sdwanStrictContractCheck name="not-ready binding rejected" ok=(!$accepted)
:set ($wan->"ready") true
:set ($sdwanRuntimeWANs->0) $wan

# An overdue unfinished request must become DOWN, never a synthetic success.
:local overdue ($sdwanStrictSlots->0)
:set ($overdue->"started_ns") ([:tonsec [/system/resource/get uptime]] - 6000000000)
:set ($sdwanStrictSlots->0) $overdue
$sdwanStrictDispatch
$sdwanStrictContractCheck name="overdue request records failure" ok=(((($sdwanStrictResults->($overdue->"key"))->"up") = false) && ((($sdwanStrictResults->($overdue->"key"))->"reason") = "strict-timeout"))
:local late [$sdwanStrictCommit slot=(0) job=$overdue up=(true) reason="late"]
$sdwanStrictContractCheck name="overdue worker cannot overwrite failure" ok=(!$late)

# Replacing the Netwatch object invalidates even an otherwise identical job.
:local current ($sdwanStrictSlots->1)
/tool/netwatch/remove [/tool/netwatch/find where comment=($current->"tag")]
/tool/netwatch/add type=tcp-conn host=198.19.210.10 port=28081 disabled=yes comment=($current->"tag")
:local accepted [$sdwanStrictCommit slot=(1) job=$current up=(true) reason="invalid"]
$sdwanStrictContractCheck name="recreated Netwatch ID rejected" ok=(!$accepted)
$sdwanStrictDispatch
$sdwanStrictContractCheck name="obsolete Netwatch slot canceled" ok=((($sdwanStrictSlots->1)->"token") != ($current->"token"))
$sdwanStrictContractCheck name="slot count remains bounded" ok=([:len $sdwanStrictSlots] <= 2)
$sdwanStrictCancel
:set sdwanStrictResults [:toarray ""]
:set sdwanStrictDue [:toarray ""]
:global sdwanStrictConcurrency [:toarray ""]
/system/script/add name=sdwan-strict-dispatch source=":delay 500ms; :global sdwanStrictDispatch; :global sdwanStrictConcurrency; :local result [\$sdwanStrictDispatch]; :set (\$sdwanStrictConcurrency->[:len \$sdwanStrictConcurrency]) \$result" policy=read,write,policy,test,sensitive
:execute script="/system/script/run sdwan-strict-dispatch"
:execute script="/system/script/run sdwan-strict-dispatch"
:delay 1200ms
:local skipped 0
:local dispatched 0
:foreach result in=$sdwanStrictConcurrency do={ :if ($result = true) do={ :set dispatched ($dispatched + 1) } else={ :set skipped ($skipped + 1) } }
$sdwanStrictContractCheck name="overlapping dispatcher admits at most one copy" ok=(($skipped >= 1) && ($dispatched <= 1) && (($skipped + $dispatched) = 2))
:local nextTick [$sdwanStrictDispatch]
$sdwanStrictContractCheck name="dispatcher resumes on next tick" ok=($nextTick && ([:len $sdwanStrictSlots] = 2))
$sdwanStrictCancel
# Exercise the actual controller entry guard, copied verbatim by the driver.
:global sdwanContractControllerRuns 0
/system/script/add name=sdwan-controller source=[/file/get [/file/find where name="contract-controller.rsc"] contents] policy=read,write,policy,test,sensitive
:execute script="/system/script/run sdwan-controller"
:local attempts 0
:while (($sdwanContractControllerRuns = 0) && ($attempts < 100)) do={ :delay 20ms; :set attempts ($attempts + 1) }
:execute script="/system/script/run sdwan-controller"
:delay 1000ms
$sdwanStrictContractCheck name="overlapping native controller skips second copy" ok=($sdwanContractControllerRuns = 1)
:global sdwanStrictContractRows; :set (($sdwanStrictContractRows->([:len $sdwanStrictContractRows] - 1))->"controller_runs") $sdwanContractControllerRuns
# Force a yield AFTER a timeout commits failure and BEFORE it clears its slot.
# The dispatcher can legitimately recycle that finished slot during this gap.
# A callback that checked its token before commit must check again before clear.
$sdwanStrictCancel
:set sdwanStrictResults [:toarray ""]
:set sdwanStrictDue [:toarray ""]
$sdwanStrictDispatch
:global sdwanStrictCommitReal $sdwanStrictCommit
:global sdwanStrictCommitPaused false
:global sdwanStrictCommit do={
    :global sdwanStrictCommitReal
    :global sdwanStrictCommitPaused
    :local accepted [$sdwanStrictCommitReal slot=$slot job=$job up=$up reason=$reason]
    :if ($reason = "strict-timeout") do={ :set sdwanStrictCommitPaused true; :delay 500ms }
    :return $accepted
}
:local timingJob ($sdwanStrictSlots->0)
:set ($timingJob->"timeout_ms") 100
:set ($sdwanStrictSlots->0) $timingJob
/system/script/add name=strict-contract-postcommit-timeout source=":global sdwanStrictTimeout; \$sdwanStrictTimeout slot=(0)" policy=read,write,policy,test,sensitive
:execute script="/system/script/run strict-contract-postcommit-timeout"
:set attempts 0
:while ((!$sdwanStrictCommitPaused) && ($attempts < 100)) do={ :delay 20ms; :set attempts ($attempts + 1) }
$sdwanStrictDispatch
:local afterCommit ($sdwanStrictSlots->0)
:delay 600ms
$sdwanStrictContractCheck name="post-commit timeout cannot clear recycled slot" ok=($sdwanStrictCommitPaused && (($afterCommit->"token") != ($timingJob->"token")) && ((($sdwanStrictSlots->0)->"token") = ($afterCommit->"token")))
:set sdwanStrictCommit $sdwanStrictCommitReal
$sdwanStrictCancel
:set sdwanStrictDispatchContractJSON [:serialize to=json value=$sdwanStrictContractRows options=json.no-string-conversion]
}
}
