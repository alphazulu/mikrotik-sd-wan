# Disposable guest only, before SD-WAN installation. Pure scope/flow vectors plus
# RAM retention checks and a temporary disabled Netwatch probe.
# No interfaces/routes/firewall are modified by this file.
:global sdwanConfigStateTestJSON "{\"pass\":false,\"status\":\"starting\"}"
:local checks 0
:local temporaryProbe ""
:local failures [:toarray ""]
:onerror fatal in={
    /import file-name=sdwan-links.rsc
    /import file-name=sdwan-config-state.rsc
    :global sdwanConfigScope; :global sdwanScopeHealth
    :global sdwanConfigIPRange; :global sdwanConfigPolicyShapes; :global sdwanConfigKeepFlow
    :local data [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="native_config_state_cases.json"] contents]]
    :local configs ($data->"configs")
    :foreach item in=($data->"scope_cases") do={
        :local actual [$sdwanConfigScope cfg=($configs->($item->"current")) previous=($configs->($item->"previous"))]
        :if ([:serialize to=json value=$actual options=json.no-string-conversion] != [:serialize to=json value=($item->"expected") options=json.no-string-conversion]) do={ :set ($failures->[:len $failures]) ("scope:" . ($item->"name") . ":" . [:serialize to=json value=$actual options=json.no-string-conversion]) }
        :set checks ($checks + 1)
        :global sdwanState [:toarray ""]; :global sdwanGood [:toarray ""]; :global sdwanBad [:toarray ""]; :global sdwanLastBad [:toarray ""]
        :global sdwanEpoch {"wan1"=20;"wan2"=21}; :global sdwanFresh {"wan1"=100;"wan2"=101}
        :global sdwanLinkFingerprints {"wan1"="saved1";"wan2"="saved2"}
        :global sdwanLinkPending [:toarray ""]; :global sdwanLinkWarming [:toarray ""]
        :global sdwanSelected {"p101"="wan1";"p102"="wan2";"default"="wan1"}
        :foreach wn in={"wan1";"wan2"} do={ :foreach pn in={"default";"voice"} do={ :local key ($pn . "/" . $wn); :set ($sdwanState->$key) "healthy"; :set ($sdwanGood->$key) 9; :set ($sdwanBad->$key) 0; :set ($sdwanLastBad->$key) 50 } }
        :local scope [$sdwanScopeHealth cfg=($configs->($item->"current")) previousRaw=[:serialize to=json value=($configs->($item->"previous")) options=json.no-string-conversion] now=(200)]
        :foreach wn in={"wan1";"wan2"} do={
            :foreach pn in={"default";"voice"} do={
                :local key ($pn . "/" . $wn)
                :local changed ((($scope->"health")->$wn) || (($scope->"profiles")->$pn))
                :local state "healthy"; :local good 9
                :if ($changed) do={ :set state "unknown"; :set good 0 }
                :if ((($sdwanState->$key) != $state) || (($sdwanGood->$key) != $good)) do={ :set ($failures->[:len $failures]) ("retention:" . ($item->"name") . ":" . $key) }
            }
            :if (!(($scope->"probe")->$wn)) do={ :if ([:typeof ($sdwanEpoch->$wn)] != "num") do={ :set ($failures->[:len $failures]) ("epoch:" . ($item->"name") . ":" . $wn) } }
            :if (!(($scope->"binding")->$wn)) do={ :if ([:typeof ($sdwanLinkFingerprints->$wn)] != "str") do={ :set ($failures->[:len $failures]) ("binding:" . ($item->"name") . ":" . $wn) } }
        }
        :set checks ($checks + 1)
    }
    :foreach item in=($data->"range_cases") do={
        :local actual [$sdwanConfigIPRange value=($item->"value")]
        :if ([:serialize to=json value=$actual options=json.no-string-conversion] != [:serialize to=json value=($item->"expected") options=json.no-string-conversion]) do={ :set ($failures->[:len $failures]) ("range:" . ($item->"value")) }
        :set checks ($checks + 1)
    }
    :foreach item in=($data->"flow_cases") do={
        :local previous [$sdwanConfigPolicyShapes cfg=($configs->($item->"previous"))]
        :local current [$sdwanConfigPolicyShapes cfg=($configs->($item->"current"))]
        :local actual [$sdwanConfigKeepFlow policyName=($item->"policy") previous=$previous current=$current flow=($item->"flow") lists=($item->"lists")]
        :if ($actual != ($item->"expected")) do={ :set ($failures->[:len $failures]) ("flow:" . ($item->"name")) }
        :set checks ($checks + 1)
    }
    :global sdwanStrictCommit; :global sdwanStrictSlots; :global sdwanStrictResults
    :global sdwanStrictGeneration; :global sdwanRuntimeWANs
    :local tag "config-state-test-probe"
    /tool/netwatch/add host=192.0.2.1 type=tcp-conn port=443 disabled=yes comment=$tag
    :set temporaryProbe [:tostr [/tool/netwatch/find where comment=$tag]]
    :local wan [:pick (($configs->"base")->"wans") 0]
    :set ($wan->"ready") true; :set ($wan->"route_gateway") "172.20.1.1%wan1"
    :local probe [:pick ($wan->"probes") 0]
    :foreach item in=($data->"strict_cases") do={
        :set sdwanStrictResults [:toarray ""]; :set sdwanStrictSlots [:toarray ""]; :set sdwanStrictGeneration 7;  :set sdwanRuntimeWANs [:toarray ""]; :set ($sdwanRuntimeWANs->0) $wan
        :local job {"token"=10;"generation"=7;"signature"="case-signature";"key"="wan1/a";"wan"="wan1";"source"="172.20.1.2";"gateway"="172.20.1.1%wan1";"probe_id"=$temporaryProbe;"tag"=$tag;"probe"=$probe}
        :local running [:deserialize from=json options=json.no-string-conversion value=[:serialize to=json value=$job options=json.no-string-conversion]]
        :local name ($item->"name")
        :if ($name = "stale-token") do={ :set ($job->"token") 9 }
        :if ($name = "stale-generation") do={ :set ($job->"generation") 6 }
        :if ($name = "changed-slot-signature") do={ :set ($running->"signature") "new-signature" }
        :if (($name = "missing-signature") || ($name = "verified-legacy")) do={ :set ($job->"signature") }
        :if ($name = "verified-legacy") do={ :set ($running->"legacy_signature_adopted") true }
        :if ($name = "wrong-probe-id") do={ :set ($job->"probe_id") "*DEADBEEF" }
        :if ($name = "source-mismatch") do={ :set ($job->"source") "172.20.1.99" }
        :if ($name = "gateway-mismatch") do={ :set ($job->"gateway") "172.20.1.99%wan1" }
        :if ($name = "missing-binding") do={ :set sdwanRuntimeWANs [:toarray ""] }
        :if ($name = "no-current-signature") do={ :set ($running->"signature") }
        :if ($name != "unknown-slot") do={ :set ($sdwanStrictSlots->0) $running }
        :local actual [$sdwanStrictCommit slot=(0) job=$job up=(true) reason="case"]
        :if (($actual != ($item->"expected")) || ((!$actual) && ([:len $sdwanStrictResults] != 0))) do={ :set ($failures->[:len $failures]) ("strict:" . $name) }
        :set checks ($checks + 1)
    }
    :global sdwanStrictAdoptLegacy; :global sdwanStrictEvidenceVersion
    :global sdwanConfigRaw; :global sdwanStrictSignature; :global sdwanHealthConfigSignature; :global sdwanHealthSignature
    :foreach stage in={"first";"late";"invalid"} do={
        :local allowed ($stage != "invalid")
        :set sdwanStrictEvidenceVersion
        :if ($stage = "late") do={ :set sdwanStrictEvidenceVersion 1 }
        :set sdwanConfigRaw [:serialize to=json value=($configs->"base") options=json.no-string-conversion]
        :set sdwanHealthConfigSignature [$sdwanHealthSignature cfg=($configs->"base")]
        :set sdwanStrictSignature $sdwanHealthConfigSignature
        :if (!$allowed) do={ :set sdwanStrictSignature "different-config" }
         :set sdwanRuntimeWANs [:toarray ""]; :set ($sdwanRuntimeWANs->0) $wan; :set sdwanStrictGeneration 7
        :local job {"token"=10;"generation"=7;"key"="wan1/a";"wan"="wan1";"source"="172.20.1.2";"gateway"="172.20.1.1%wan1";"probe_id"=$temporaryProbe;"tag"=$tag;"probe"=$probe}
        # Adoption resolves the real owned Netwatch tag for this key.
        /tool/netwatch/set $temporaryProbe comment="sdwan:v1:probe:wan1:a"
        :set ($job->"tag") "sdwan:v1:probe:wan1:a"
        :set sdwanStrictSlots [:toarray ""]; :set ($sdwanStrictSlots->0) $job
        :set sdwanStrictResults [:toarray ""]; :set ($sdwanStrictResults->"wan1/a") $job
        $sdwanStrictAdoptLegacy
        :local adopted (([:typeof (($sdwanStrictResults->"wan1/a")->"signature")] = "str") && ((($sdwanStrictSlots->0)->"legacy_signature_adopted") = true))
        :if ($adopted != $allowed) do={ :set ($failures->[:len $failures]) ("legacy:" . $allowed) }
        :set checks ($checks + 1)
    }
} do={ :set ($failures->[:len $failures]) ("fatal:" . $fatal) }
:local result [:toarray ""]
:set ($result->"pass") ([:len $failures] = 0); :set ($result->"checks") $checks; :set ($result->"failures") $failures
:set sdwanConfigStateTestJSON [:serialize to=json value=$result options=json.no-string-conversion]
# Clear injected test state before the real disposable-guest install.
:global sdwanState; :set sdwanState
:global sdwanGood; :set sdwanGood
:global sdwanBad; :set sdwanBad
:global sdwanLastBad; :set sdwanLastBad
:global sdwanEpoch; :set sdwanEpoch
:global sdwanFresh; :set sdwanFresh
:global sdwanLinkFingerprints; :set sdwanLinkFingerprints
:global sdwanLinkPending; :set sdwanLinkPending
:global sdwanLinkWarming; :set sdwanLinkWarming
:global sdwanSelected; :set sdwanSelected
:global sdwanConfigProbeReset; :set sdwanConfigProbeReset
 :if ($temporaryProbe != "") do={ /tool/netwatch/remove $temporaryProbe }
:global sdwanStrictSlots; :set sdwanStrictSlots
:global sdwanStrictResults; :set sdwanStrictResults
:global sdwanStrictGeneration; :set sdwanStrictGeneration
:global sdwanStrictEvidenceVersion; :set sdwanStrictEvidenceVersion
:global sdwanRuntimeWANs; :set sdwanRuntimeWANs
:global sdwanConfigRaw; :set sdwanConfigRaw
:global sdwanStrictSignature; :set sdwanStrictSignature
:global sdwanHealthConfigSignature; :set sdwanHealthConfigSignature
:if (!($result->"pass")) do={ :error $sdwanConfigStateTestJSON }
