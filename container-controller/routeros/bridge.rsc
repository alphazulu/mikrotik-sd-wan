# Experimental protocol helper, not installed in the default native package.
# The generated controller will be the sole route writer; this helper only
# validates/caches intent and publishes public configuration in RAM.
:global sdwanContainerBridge do={
    :global sdwanContainerBoot
    :global sdwanContainerGeneration
    :global sdwanContainerRaw
    :global sdwanContainerOwner
    :global sdwanContainerSeq
    :global sdwanContainerNonce
    :global sdwanContainerPlan
    :global sdwanContainerSeen
    :global sdwanContainerConfigJSON
    :global sdwanContainerBridgeVersion
    :global sdwanContainerRejects
    :global sdwanContainerLastReject
    :if (([:typeof $sdwanContainerBoot] != "str") || ($sdwanContainerBridgeVersion != 1)) do={
        :set sdwanContainerBridgeVersion 1
        :set sdwanContainerBoot [:rndstr from="0123456789abcdef" length=32]
        :set sdwanContainerGeneration 0
        :set sdwanContainerRaw ""
    }
    :if ([:typeof $sdwanContainerRejects] != "num") do={ :set sdwanContainerRejects 0 }
    :if ([:typeof $sdwanContainerLastReject] != "str") do={ :set sdwanContainerLastReject "" }
    :if ([:tostr $sdwanContainerRaw] != [:tostr $raw]) do={
        :set sdwanContainerRaw $raw
        :set sdwanContainerGeneration ($sdwanContainerGeneration + 1)
        :set sdwanContainerOwner ""
        :set sdwanContainerSeq 0
        :set sdwanContainerNonce ""
        :set sdwanContainerPlan [:toarray ""]
        :set sdwanContainerSeen ""
        :set sdwanContainerRejects 0
        :set sdwanContainerLastReject ""
        :local public [:toarray ""]
        :set ($public->"schema_version") 1
        :set ($public->"revision") ($cfg->"revision")
        :local policies [:toarray ""]
        :foreach policy in=($cfg->"policies") do={
            :local item [:toarray ""]
            :foreach field in={"name";"profile";"mode";"wans";"allow_degraded"} do={ :set ($item->$field) ($policy->$field) }
            :set ($policies->[:len $policies]) $item
        }
        :set ($public->"policies") $policies
        :set sdwanContainerConfigJSON [:serialize to=json options=json.no-string-conversion value=$public]
    }
    :local alive ([:len [/ip/firewall/address-list/find where list="sdwan-container-live" and address="172.31.255.2" and dynamic=yes]] = 1)
    :if (!$alive) do={
        :set sdwanContainerOwner ""
        :set sdwanContainerPlan [:toarray ""]
    }
    :local rejection ""
    :local path ($dir . "sdwan-container-intent.json")
    :local files [/file/find where name=$path]
    :if ([:len $files] = 1) do={
        :local text [:tostr [/file/get $files contents]]
        :if ($text != [:tostr $sdwanContainerSeen]) do={
            :set sdwanContainerSeen $text
            :onerror invalid in={
                :if (([:len $text] = 0) || ([:len $text] > 32768)) do={ :error "intent length" }
                :local intent [:deserialize from=json options=json.no-string-conversion value=$text]
                :if ([:typeof $intent] != "array") do={ :error "intent object" }
                :if ([:typeof ($intent->"protocol")] != "num") do={ :error "intent protocol" }
                :if (($intent->"protocol") != 1) do={ :error "intent protocol" }
                :if ([:typeof ($intent->"boot_id")] != "str") do={ :error "intent boot fence" }
                :if (($intent->"boot_id") != $sdwanContainerBoot) do={ :error "intent boot fence" }
                :if ([:typeof ($intent->"generation")] != "num") do={ :error "intent configuration fence" }
                :if (($intent->"generation") != $sdwanContainerGeneration) do={ :error "intent configuration fence" }
                :if ([:typeof ($intent->"revision")] != "str") do={ :error "intent revision" }
                :if (($intent->"revision") != ($cfg->"revision")) do={ :error "intent revision" }
                :local observed ($intent->"observed_uptime")
                :if ([:typeof $observed] != "num") do={ :error "intent observation type" }
                :if (($observed > $now) || (($now - $observed) > 6)) do={ :error "intent observation age" }
                :local owner ($intent->"instance")
                :if (([:typeof $owner] != "str") || ([:len $owner] != 32)) do={ :error "intent owner" }
                :if (([:len [:tostr $sdwanContainerOwner]] > 0) && ($sdwanContainerOwner != $owner)) do={ :error "intent live foreign owner" }
                :local sequence ($intent->"seq")
                :if ([:typeof $sequence] != "num") do={ :error "intent sequence type" }
                :if ($sequence <= 0) do={ :error "intent sequence" }
                :if (($sdwanContainerNonce = $owner) && ($sequence <= $sdwanContainerSeq)) do={ :error "intent replay" }
                :if ([:typeof ($intent->"release")] != "bool") do={ :error "intent release type" }
                :if ($intent->"release") do={
                    :if ($sdwanContainerOwner != $owner) do={ :error "release foreign owner" }
                    :set sdwanContainerOwner ""
                    :set sdwanContainerPlan [:toarray ""]
                } else={
                    :local plan ($intent->"selected")
                    :if ([:typeof $plan] != "array") do={ :error "intent plan type" }
                    :if ([:len $plan] != [:len ($cfg->"policies")]) do={ :error "intent policy count" }
                    :foreach policy in=($cfg->"policies") do={
                        :local target ($plan->($policy->"name"))
                        :if ([:typeof $target] != "str") do={ :error "intent policy missing" }
                        :local allowed ($target = "none")
                        :foreach wan in=($policy->"wans") do={ :if ($wan = $target) do={ :set allowed true } }
                        :if (!$allowed) do={ :error "intent WAN not allowed" }
                    }
                    # A claim can be prepared before the first heartbeat. It
                    # cannot actuate until the address-list lease is live.
                    :set sdwanContainerOwner $owner
                    :set sdwanContainerPlan $plan
                }
                :set sdwanContainerSeq $sequence
                :set sdwanContainerNonce $owner
            } do={
                :set rejection [:tostr $invalid]
                :local suffix [:find $rejection " (:error"]
                :if ([:typeof $suffix] = "num") do={ :set rejection [:pick $rejection 0 $suffix] }
                :if ((!($rejection ~ "^intent ")) && (!($rejection ~ "^release "))) do={ :set rejection "intent validation" }
                :set sdwanContainerRejects ($sdwanContainerRejects + 1)
                :set sdwanContainerLastReject $rejection
            }
        }
    }
    :local result [:toarray ""]
    :set ($result->"protocol") 1
    :set ($result->"boot_id") $sdwanContainerBoot
    :set ($result->"generation") $sdwanContainerGeneration
    :set ($result->"intent_file") $path
    :set ($result->"owner_instance") $sdwanContainerOwner
    :set ($result->"lease_remaining_seconds") 0
    :if ($alive) do={ :set ($result->"lease_remaining_seconds") 6 }
    :set ($result->"rejection") $rejection
    :set ($result->"rejections") $sdwanContainerRejects
    :set ($result->"last_rejection") $sdwanContainerLastReject
    :set ($result->"active") ($alive && ([:len [:tostr $sdwanContainerOwner]] > 0))
    :set ($result->"selected") $sdwanContainerPlan
    :return $result
}
