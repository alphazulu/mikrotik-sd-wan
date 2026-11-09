# Configuration scopes are computed from declarative JSON, never runtime leases.
# Names identify independent WAN/profile state; order and admin-only edits do not.
:global sdwanConfigWANSignature do={
    :local value [:toarray ""]
    :foreach field in={"interface";"kind";"address";"gateway";"probe_table";"apn_profile";"vpn_type";"vpn_endpoint";"vpn_peer_public_key";"vpn_listen_port";"underlays"} do={ :set ($value->$field) ($wan->$field) }
    :if ([:len [:tostr ($value->"kind")]] = 0) do={ :set ($value->"kind") "static" }
    :if ($scope != "binding") do={
        :set ($value->"icmp_target") ($wan->"icmp_target")
        :local probes [:toarray ""]
        :foreach probe in=($wan->"probes") do={ :set ($probes->($probe->"name")) $probe }
        :set ($value->"probes") $probes
        :local timing [:toarray ""]
        :foreach field in={"interval_seconds";"timeout_ms";"packet_count";"packet_interval_ms";"strict_probe_interval_seconds";"strict_probe_timeout_ms"} do={ :set ($timing->$field) (($cfg->"health")->$field) }
        :if ([:typeof ($timing->"strict_probe_interval_seconds")] != "num") do={ :set ($timing->"strict_probe_interval_seconds") 10 }
        :if ([:typeof ($timing->"strict_probe_timeout_ms")] != "num") do={ :set ($timing->"strict_probe_timeout_ms") 2000 }
        :if ($scope = "health") do={ :foreach field in={"quorum";"fail_windows";"recover_windows";"hold_down_seconds";"stale_seconds"} do={ :set ($timing->$field) (($cfg->"health")->$field) } }
        :set ($value->"timing") $timing
    }
    :return [:serialize to=json value=$value options=json.no-string-conversion]
}
# Match the controller's actual integer SLA comparisons: microseconds for
# RTT/jitter and hundredths of a percent for loss. 150 and 150.0 are one limit.
:global sdwanConfigProfileSignature do={
    :local scaled do={
        :local text [:tostr $value]
        :local dot [:find $text "."]
        :if ([:typeof $dot] != "num") do={ :return ([:tonum $text] * $scale) }
        :return (([:tonum [:pick $text 0 $dot]] * $scale) + [:tonum [:pick ($text . "000") ($dot + 1) ($dot + 1 + $digits)]])
    }
    :local value [:toarray ""]
    :set ($value->"rtt") [$scaled value=($threshold->"rtt_ms") scale=(1000) digits=(3)]
    :set ($value->"jitter") [$scaled value=($threshold->"jitter_ms") scale=(1000) digits=(3)]
    :set ($value->"loss") [$scaled value=($threshold->"loss_percent") scale=(100) digits=(2)]
    :return [:serialize to=json value=$value options=json.no-string-conversion]
}
:global sdwanConfigScope do={
    :global sdwanConfigProfileSignature
    :global sdwanConfigWANSignature
    :local before [:toarray ""]
    :if ([:typeof $previous] = "array") do={ :foreach wan in=($previous->"wans") do={ :set ($before->($wan->"name")) $wan } }
    :local result {"health"=[:toarray ""];"probe"=[:toarray ""];"binding"=[:toarray ""];"profiles"=[:toarray ""]}
    :foreach wan in=($cfg->"wans") do={
        :local wn ($wan->"name")
        :foreach scope in={"health";"probe";"binding"} do={
            :local changed true
            :if ([:typeof ($before->$wn)] = "array") do={ :set changed ([$sdwanConfigWANSignature cfg=$cfg wan=$wan scope=$scope] != [$sdwanConfigWANSignature cfg=$previous wan=($before->$wn) scope=$scope]) }
            :set (($result->$scope)->$wn) $changed
        }
    }
    :foreach profile,threshold in=($cfg->"sla_profiles") do={
        :local old (($previous->"sla_profiles")->$profile)
        :local changed true
        :if ([:typeof $old] = "array") do={ :set changed ([$sdwanConfigProfileSignature threshold=$old] != [$sdwanConfigProfileSignature threshold=$threshold]) }
        :set (($result->"profiles")->$profile) $changed
    }
    :return $result
}
:global sdwanScopeHealth do={
    :global sdwanConfigScope
    :global sdwanState; :global sdwanGood; :global sdwanBad; :global sdwanLastBad
    :global sdwanEpoch; :global sdwanFresh; :global sdwanLinkFingerprints; :global sdwanLinkPending; :global sdwanLinkWarming
    :global sdwanWanDown; :global sdwanCleanupUntil; :global sdwanLastCleanup; :global sdwanSelected
    :global sdwanConfigProbeReset
    :local previous [:toarray ""]
    :if ([:typeof $previousRaw] = "str") do={ :if ([:len $previousRaw] > 0) do={ :set previous [:deserialize from=json options=json.no-string-conversion value=$previousRaw] } }
    :local scope [$sdwanConfigScope cfg=$cfg previous=$previous]
    :local cold ([:typeof $sdwanState] != "array")
    :local states [:toarray ""]; :local good [:toarray ""]; :local bad [:toarray ""]; :local lastBad [:toarray ""]
    :foreach wan in=($cfg->"wans") do={
        :local wn ($wan->"name")
        :foreach profile,threshold in=($cfg->"sla_profiles") do={
            :local key ($profile . "/" . $wn)
            :local keep ((!$cold) && (!(($scope->"health")->$wn)) && (!(($scope->"profiles")->$profile)))
            :if (([:typeof ($sdwanState->$key)] != "str") || ([:typeof ($sdwanGood->$key)] != "num") || ([:typeof ($sdwanBad->$key)] != "num") || ([:typeof ($sdwanLastBad->$key)] != "num")) do={ :set keep false }
            :if ($keep) do={
                :set ($states->$key) ($sdwanState->$key); :set ($good->$key) ($sdwanGood->$key); :set ($bad->$key) ($sdwanBad->$key); :set ($lastBad->$key) ($sdwanLastBad->$key)
            } else={ :set ($states->$key) "unknown"; :set ($good->$key) 0; :set ($bad->$key) 0; :set ($lastBad->$key) $now }
        }
    }
    :set sdwanState $states; :set sdwanGood $good; :set sdwanBad $bad; :set sdwanLastBad $lastBad
    :local keepNames [:toarray ""]; :local keepBindings [:toarray ""]
    :local resets [:toarray ""]
    :foreach wan in=($cfg->"wans") do={
        :local wn ($wan->"name")
        :if ((!$cold) && (!(($scope->"probe")->$wn))) do={ :set ($keepNames->$wn) true }
        :if ((!$cold) && (!(($scope->"binding")->$wn))) do={ :set ($keepBindings->$wn) true }
        # Initial install creates probes itself. Existing affected WANs require
        # a new forwarding/probe generation, including static WAN edits.
        :local existed false
        :foreach old in=($previous->"wans") do={ :if (($old->"name") = $wn) do={ :set existed true } }
        :if ($existed && (($scope->"probe")->$wn)) do={ :set ($resets->$wn) true }
    }
    :local retain do={
        :local result [:toarray ""]
        :foreach key,allowed in=$names do={ :if ($allowed) do={ :set ($result->$key) ($input->$key) } }
        :return $result
    }
    :set sdwanEpoch [$retain input=$sdwanEpoch names=$keepNames]; :set sdwanFresh [$retain input=$sdwanFresh names=$keepNames]
    :set sdwanLinkWarming [$retain input=$sdwanLinkWarming names=$keepNames]
    :set sdwanLinkFingerprints [$retain input=$sdwanLinkFingerprints names=$keepBindings]
    :set sdwanLinkPending [$retain input=$sdwanLinkPending names=$keepBindings]
    :set sdwanWanDown [$retain input=$sdwanWanDown names=$keepNames]
    :local policies [:toarray ""]
    :foreach policy in=($cfg->"policies") do={ :set ($policies->($policy->"name")) true }
    :set sdwanSelected [$retain input=$sdwanSelected names=$policies]
    :set sdwanCleanupUntil [$retain input=$sdwanCleanupUntil names=$policies]
    :set sdwanConfigProbeReset $resets
    :return $scope
}
# Exact asynchronous evidence identity. No stale response from an edited probe,
# new lease/source or different HTTP expectation may qualify another generation.
:global sdwanStrictProbeSignature do={
    :local value [:toarray ""]
    :foreach field in={"name";"interface";"kind";"address";"route_gateway";"probe_table"} do={ :set ($value->$field) ($wan->$field) }
    :set ($value->"probe") $probe
    :local timeout ($health->"strict_probe_timeout_ms")
    :if ([:typeof $timeout] != "num") do={ :set timeout 2000 }
    :local interval ($health->"strict_probe_interval_seconds")
    :if ([:typeof $interval] != "num") do={ :set interval 10 }
    :set ($value->"timeout") $timeout; :set ($value->"interval") $interval
    :return [:serialize to=json value=$value options=json.no-string-conversion]
}
# Administrative-only edits keep fresh SLA and established flow bindings.
:global sdwanHealthSignature do={
    :local signature [:toarray ""]
    :set ($signature->"health") ($cfg->"health")
    :set ($signature->"profiles") ($cfg->"sla_profiles")
    :local rows [:toarray ""]
    :foreach spec in=($cfg->"wans") do={
        :local row [:toarray ""]
        :foreach field in={"name";"interface";"kind";"address";"gateway";"probe_table";"icmp_target";"apn_profile";"probes";"vpn_type";"vpn_endpoint";"vpn_peer_public_key";"vpn_listen_port";"underlays"} do={ :set ($row->$field) ($spec->$field) }
        :set ($rows->[:len $rows]) $row
    }
    :set ($signature->"wans") $rows
    :return [:serialize to=json value=$signature options=json.no-string-conversion]
}
# IPv4 interval parsing also covers address-list ranges. Never execute input.
:global sdwanConfigIPRange do={
    :global sdwanConfigIPRange
    :local text [:tostr $value]
    :if ($text = "") do={ :set text "0.0.0.0/0" }
    :local dash [:find $text "-"]
    :if ([:typeof $dash] = "num") do={
        :local left [$sdwanConfigIPRange value=[:pick $text 0 $dash]]
        :local right [$sdwanConfigIPRange value=[:pick $text ($dash + 1) [:len $text]]]
        :if (([:typeof $left] != "array") || ([:typeof $right] != "array") || (($left->"first") > ($right->"last"))) do={ :return false }
        :return {"first"=($left->"first");"last"=($right->"last")}
    }
    :local slash [:find $text "/"]
    :local bits 32
    :if ([:typeof $slash] = "num") do={ :set bits [:tonum [:pick $text ($slash + 1) [:len $text]]]; :set text [:pick $text 0 $slash] }
    :if (([:typeof $bits] != "num") || ($bits < 0) || ($bits > 32)) do={ :return false }
    :local address 0
    :local start 0
    :for index from=0 to=3 do={
        :local end [:find $text "." $start]
        :if ($index = 3) do={ :if ([:typeof $end] = "num") do={ :return false }; :set end [:len $text] } else={ :if ([:typeof $end] != "num") do={ :return false } }
        :local octet [:tonum [:pick $text $start $end]]
        :if (([:typeof $octet] != "num") || ($octet < 0) || ($octet > 255)) do={ :return false }
        :set address (($address * 256) + $octet); :set start ($end + 1)
    }
    :local size 1
    :if ($bits < 32) do={ :for index from=$bits to=31 do={ :set size ($size * 2) } }
    :local first (($address / $size) * $size)
    :return {"first"=$first;"last"=($first + $size - 1)}
}
:global sdwanConfigPolicyShapes do={
    :global sdwanOrderPolicies
    :local result [:toarray ""]
    :foreach policy in=[$sdwanOrderPolicies policies=($cfg->"policies")] do={
        :local shape [:toarray ""]
        :foreach field in={"source";"source_group";"source_list";"destination";"destination_group";"destination_list";"in_interface";"protocol";"src_ports";"dst_ports"} do={ :set ($shape->$field) [:tostr ($policy->$field)] }
        :if (($shape->"protocol") = "") do={ :set ($shape->"protocol") "any" }
        :foreach side in={"source";"destination"} do={
            :local group ($shape->($side . "_group"))
            :if ($group != "") do={ :set ($shape->($side . "_members")) (($cfg->"groups")->$group) }
        }
        :local item [:toarray ""]
        :set ($item->"name") ($policy->"name"); :set ($item->"shape") $shape
        :set ($item->"signature") [:serialize to=json value=$shape options=json.no-string-conversion]
        :set ($result->[:len $result]) $item
    }
    :return $result
}
# A tri-state predicate: unknown interface provenance cannot prove preservation.
:global sdwanConfigPolicyMatch do={
    :global sdwanConfigIPRange
    :local unknown false
    :local proto ($shape->"protocol")
    :if (($proto != "any") && ($proto != ($flow->"protocol"))) do={ :return "no" }
    :foreach side in={"source";"destination"} do={
        :local ip [$sdwanConfigIPRange value=($flow->$side)]
        :if ([:typeof $ip] != "array") do={ :return "unknown" }
        :local address ($ip->"first")
        :local bounds [$sdwanConfigIPRange value=($shape->$side)]
        :if ([:typeof $bounds] != "array") do={ :return "unknown" }
        :if (($address < ($bounds->"first")) || ($address > ($bounds->"last"))) do={ :return "no" }
        :foreach field in={"_group";"_list"} do={
            :local name ($shape->($side . $field))
            :if ($name != "") do={
                :local members ($shape->($side . "_members"))
                :if ($field = "_list") do={ :set members ($lists->$name) }
                :local matched false
                :foreach member in=$members do={
                    :local range [$sdwanConfigIPRange value=$member]
                    # DNS parents are not address matches; resolved children are.
                    :if ([:typeof $range] = "array") do={ :if (($address >= ($range->"first")) && ($address <= ($range->"last"))) do={ :set matched true } }
                }
                :if (!$matched) do={ :return "no" }
            }
        }
    }
    :foreach side in={"src";"dst"} do={
        :local ports ($shape->($side . "_ports"))
        :if ($ports != "") do={
            :local port ($flow->($side . "_port"))
            :if (([:typeof $port] != "num") || ($port = 0)) do={ :set unknown true } else={
                :local matched false
                :foreach span in=[:toarray $ports] do={
                    :local dash [:find $span "-"]
                    :local lo [:tonum $span]; :local hi $lo
                    :if ([:typeof $dash] = "num") do={ :set lo [:tonum [:pick $span 0 $dash]]; :set hi [:tonum [:pick $span ($dash + 1) [:len $span]]] }
                    :if (($port >= $lo) && ($port <= $hi)) do={ :set matched true }
                }
                :if (!$matched) do={ :return "no" }
            }
        }
    }
    :local iface ($shape->"in_interface")
    :if (($iface != "") && ($iface != ($proven->"in_interface"))) do={ :set unknown true }
    :if ($unknown) do={ :return "unknown" }
    :return "yes"
}
# Existing marks prove which unchanged earlier predicates did not match when
# the flow was admitted. Live Address List changes alone do not reclassify it.
:global sdwanConfigKeepFlow do={
    :global sdwanConfigPolicyMatch
    :local earlier [:toarray ""]
    :local owner false
    :foreach item in=$previous do={
        :if (($item->"name") = $policyName) do={ :set owner $item } else={ :if ([:typeof $owner] != "array") do={ :set ($earlier->($item->"name")) ($item->"signature") } }
    }
    :if ([:typeof $owner] != "array") do={ :return false }
    :foreach item in=$current do={
        :local name ($item->"name")
        :if ($name = $policyName) do={
            :if (($item->"signature") = ($owner->"signature")) do={ :return true }
            :return ([$sdwanConfigPolicyMatch shape=($item->"shape") flow=$flow lists=$lists proven=($owner->"shape")] = "yes")
        }
        :if (($earlier->$name) != ($item->"signature")) do={
            :if ([$sdwanConfigPolicyMatch shape=($item->"shape") flow=$flow lists=$lists proven=[:toarray ""]] != "no") do={ :return false }
        }
    }
    :return false
}

# One-time upgrade from evidence created by the previous controller. Adopt
# only when its full legacy config signature and all original fences agree.
:global sdwanStrictAdoptLegacy do={
    :global sdwanStrictEvidenceVersion
    :global sdwanStrictSignature; :global sdwanHealthConfigSignature
    :global sdwanStrictGeneration; :global sdwanStrictResults; :global sdwanStrictSlots
    :global sdwanConfigRaw; :global sdwanRuntimeWANs
    :global sdwanHealthSignature; :global sdwanStrictProbeSignature
    :if ($sdwanStrictEvidenceVersion = 1) do={
        # An old worker may finish between library imports. Revisit only
        # unsigned legacy data, under the same full-context proof below.
        :local unsigned false
        :foreach evidence in=$sdwanStrictResults do={ :if (([:typeof $evidence] = "array") && ([:typeof ($evidence->"signature")] != "str")) do={ :set unsigned true } }
        :foreach job in=$sdwanStrictSlots do={ :if (([:typeof $job] = "array") && ([:typeof ($job->"signature")] != "str")) do={ :set unsigned true } }
        :if (!$unsigned) do={ :return false }
    }
    :if (([:typeof $sdwanConfigRaw] = "str") && ([:len $sdwanConfigRaw] > 0)) do={
        :local previous [:deserialize from=json options=json.no-string-conversion value=$sdwanConfigRaw]
        :local expected [$sdwanHealthSignature cfg=$previous]
        :if (($sdwanStrictSignature = $expected) && ($sdwanHealthConfigSignature = $expected)) do={
            :foreach wan in=$sdwanRuntimeWANs do={
                :foreach probe in=($wan->"probes") do={
                    :local key (($wan->"name") . "/" . ($probe->"name"))
                    :local tag ("sdwan:v1:probe:" . ($wan->"name") . ":" . ($probe->"name"))
                    :local pid [:tostr [/tool/netwatch/find where comment=$tag]]
                    :local signature [$sdwanStrictProbeSignature wan=$wan probe=$probe health=($previous->"health")]
                    :local evidence ($sdwanStrictResults->$key)
                    :if (([:typeof $evidence] = "array") && ([:typeof ($evidence->"signature")] != "str") && (($evidence->"generation") = $sdwanStrictGeneration) && (($evidence->"source") = ($wan->"address")) && (($evidence->"gateway") = ($wan->"route_gateway")) && (($evidence->"probe_id") = $pid) && ($pid != "")) do={ :set ($evidence->"signature") $signature; :set ($sdwanStrictResults->$key) $evidence }
                    :foreach slot in={0;1} do={
                        :local job ($sdwanStrictSlots->$slot)
                        :if (([:typeof $job] = "array") && (($job->"key") = $key) && ([:typeof ($job->"signature")] != "str") && (($job->"generation") = $sdwanStrictGeneration) && (($job->"source") = ($wan->"address")) && (($job->"gateway") = ($wan->"route_gateway")) && (($job->"probe_id") = $pid) && ($pid != "") && ([:serialize to=json value=($job->"probe") options=json.no-string-conversion] = [:serialize to=json value=$probe options=json.no-string-conversion])) do={ :set ($job->"signature") $signature; :set ($job->"legacy_signature_adopted") true; :set ($sdwanStrictSlots->$slot) $job }
                    }
                }
            }
        }
    }
    :set sdwanStrictEvidenceVersion 1
    :return true
}
:global sdwanPolicySignature do={
    :global sdwanOrderPolicies
    :local value [:toarray ""]
    :local groups ($cfg->"groups")
    :if ([:typeof $groups] != "array") do={ :set groups [:toarray ""] }
    :set ($value->"groups") $groups
    :local rows [:toarray ""]
    :foreach item in=[$sdwanOrderPolicies policies=($cfg->"policies")] do={
        :local row [:toarray ""]
        :foreach field in={"name";"source";"source_group";"source_list";"destination";"destination_group";"destination_list";"in_interface";"protocol";"src_ports";"dst_ports";"priority"} do={
            :local v [:tostr ($item->$field)]
            :if (($field = "protocol") && ($v = "")) do={ :set v "any" }
            :set ($row->$field) $v
        }
        :set ($rows->[:len $rows]) $row
    }
    :set ($value->"policies") $rows
    :return [:serialize to=json value=$value options=json.no-string-conversion]
}
:global sdwanConfigStateLoaded 1
