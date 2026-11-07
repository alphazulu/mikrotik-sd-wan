# LAB ONLY. Import sdwan-links.rsc in this script's environment first.
# Synthetic callbacks exercise native RouterOS error/scoping semantics.
:global sdwanConntrackFind
:global sdwanRetryTestCalls 0
:global sdwanRetryTestResult
:if ([:typeof $sdwanConntrackFind] != "array") do={ :error "load retry helper first" }
:local transient do={
    :global sdwanRetryTestCalls
    :set sdwanRetryTestCalls ($sdwanRetryTestCalls + 1)
    :if ($sdwanRetryTestCalls < 3) do={ :error "no such item (4)" }
    :if (($mark != "expected") || ($localPort != 1234) || ($remoteIP != 198.18.0.1) || ($remotePort != 4321)) do={ :error "callback selectors changed" }
    :return {"first";"second"}
}
:local ids [$sdwanConntrackFind query=$transient mark="expected" localPort=1234 remoteIP=198.18.0.1 remotePort=4321]
:if (([:len $ids] != 2) || ([:pick $ids 0] != "first") || ([:pick $ids 1] != "second") || ($sdwanRetryTestCalls != 3)) do={ :error "transient retry/result mismatch" }
:local empty do={ :return [:toarray ""] }
:if ([:len [$sdwanConntrackFind query=$empty]] != 0) do={ :error "empty result changed" }
:set sdwanRetryTestCalls 0
:local denied do={ :global sdwanRetryTestCalls; :set sdwanRetryTestCalls ($sdwanRetryTestCalls + 1); :error "not enough permissions (9)" }
:local propagated false
:onerror denial in={ :local ignored [$sdwanConntrackFind query=$denied] } do={ :set propagated ([:pick $denial 0 22] = "not enough permissions") }
:if ((!$propagated) || ($sdwanRetryTestCalls != 1)) do={ :error "permission error was retried or hidden" }
:set sdwanRetryTestCalls 0
:local expires do={ :global sdwanRetryTestCalls; :set sdwanRetryTestCalls ($sdwanRetryTestCalls + 1); :error "no such item (4)" }
:set propagated false
:onerror exhausted in={ :local ignored [$sdwanConntrackFind query=$expires] } do={ :set propagated ([:pick $exhausted 0 12] = "no such item") }
:if ((!$propagated) || ($sdwanRetryTestCalls != 5)) do={ :error "retry bound was not enforced" }
:set sdwanRetryTestResult "passed: selectors, transient recovery, empty result, permission propagation, retry bound"
