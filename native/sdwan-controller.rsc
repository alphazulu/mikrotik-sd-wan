:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
# MikroTik RouterOS 7.24.5. Installed as system/script sdwan-controller.
# Runtime decisions are entirely local. Active config: sdwan-active.json (promoted by the installer).
:if ([/system/script/job/print count-only where script="sdwan-controller"] > 1) do={ :return "" }
:global sdwanStatusJSON
:global sdwanState
:global sdwanGood
:global sdwanBad
:global sdwanLastBad
:global sdwanEpoch
:global sdwanFresh
:global sdwanSelected
:global sdwanConfigRaw
:global sdwanLastError
:global sdwanWanDown
:global sdwanConntrackRemoved
:global sdwanLastCleanup
:global sdwanCleanupUntil
:global sdwanResolveWANs
:global sdwanReconcileWANs
:global sdwanLinksLoaded
:global sdwanLinkFingerprints
:global sdwanLinkPending
:global sdwanLinkWarming
:global sdwanEvents
:global sdwanRecordEvent
:global sdwanProbeAccepted
:global sdwanHealthSignature
:global sdwanHealthConfigSignature
:global sdwanRuntimeWANs
:global sdwanMaintenance
:global sdwanDrainingMarks
:global sdwanOverlayLoaded
:global sdwanVPNTick
:global sdwanOverlayTick
:global sdwanVPNTransport
:onerror err in={
    :local raw [/file/get [/file/find where name=($dir . "sdwan-active.json")] contents]
    :local cfg [:deserialize from=json options=json.no-string-conversion value=$raw]
    :if (($cfg->"schema_version") != 1) do={ :error "unsupported SDWAN schema" }
    :if (([:typeof $sdwanResolveWANs] != "array") || ($sdwanLinksLoaded != 7) || ($sdwanConfigRaw != $raw)) do={ /import file-name=($dir . "sdwan-links.rsc") }
    :if ((($cfg->"vpn_egress")->"enabled") = true) do={
        :global sdwanVPNLoaded
        :global sdwanVPNTick
        :if (($sdwanVPNLoaded != 1) || ($sdwanConfigRaw != $raw)) do={ /import file-name=($dir . "sdwan-vpn.rsc") }
    }
    :local health ($cfg->"health")
    :local now ([:tonsec [/system/resource/get uptime]] / 1000000000)
    :if ([:typeof $sdwanWanDown] != "array") do={ :set sdwanWanDown [:toarray ""] }
    :if ([:typeof $sdwanConntrackRemoved] != "num") do={ :set sdwanConntrackRemoved 0 }
    :if ([:typeof $sdwanLastCleanup] != "array") do={ :set sdwanLastCleanup [:toarray ""] }
    :if ([:typeof $sdwanCleanupUntil] != "array") do={ :set sdwanCleanupUntil [:toarray ""] }
    :local configChanged ($sdwanConfigRaw != $raw)
    :local signature $sdwanHealthConfigSignature
    :if ($configChanged || ([:typeof $signature] != "str")) do={ :set signature [$sdwanHealthSignature cfg=$cfg] }
    :local resetHealth (([:typeof $sdwanState] != "array") || ($configChanged && (([:typeof $sdwanHealthConfigSignature] != "str") || ($sdwanHealthConfigSignature != $signature))))
    :if ($resetHealth) do={
        :set sdwanLinkFingerprints [:toarray ""]
        :set sdwanLinkPending [:toarray ""]
        :set sdwanLinkWarming [:toarray ""]
        :set sdwanState [:toarray ""]
        :set sdwanGood [:toarray ""]
        :set sdwanBad [:toarray ""]
        :set sdwanLastBad [:toarray ""]
        :set sdwanEpoch [:toarray ""]
        :set sdwanFresh [:toarray ""]
        :if ([:typeof $sdwanSelected] != "array") do={ :set sdwanSelected [:toarray ""] }
        :local retained [:toarray ""]
        :foreach policy in=($cfg->"policies") do={ :local pn ($policy->"name"); :if ([:typeof ($sdwanSelected->$pn)] = "str") do={ :set ($retained->$pn) ($sdwanSelected->$pn) } }
        :set sdwanSelected $retained
        :set sdwanWanDown [:toarray ""]
        :set sdwanCleanupUntil [:toarray ""]
        :if ([:typeof $sdwanConntrackRemoved] != "num") do={ :set sdwanConntrackRemoved 0 }
        :if ([:typeof $sdwanLastCleanup] != "array") do={ :set sdwanLastCleanup [:toarray ""] }
        :log info "SDWAN local controller initialized"
    }
    :if ($configChanged && (!$resetHealth)) do={
        :local retained [:toarray ""]
        :foreach policy in=($cfg->"policies") do={ :local pn ($policy->"name"); :if ([:typeof ($sdwanSelected->$pn)] = "str") do={ :set ($retained->$pn) ($sdwanSelected->$pn) } }
        :set sdwanSelected $retained
        :log info "SDWAN configuration updated; SLA state preserved"
    }
    :set sdwanHealthConfigSignature $signature
    :set sdwanConfigRaw $raw
    :if ([:typeof $sdwanLinkWarming] != "array") do={ :set sdwanLinkWarming [:toarray ""] }
    :set ($cfg->"wans") [$sdwanResolveWANs wans=($cfg->"wans")]
    :if ((($cfg->"vpn_egress")->"enabled") = true) do={ :set ($cfg->"wans") [$sdwanVPNTick cfg=$cfg] }
    :local linkChanges [$sdwanReconcileWANs wans=($cfg->"wans") policies=($cfg->"policies") health=$health]
    :foreach wn,change in=$linkChanges do={
        :set sdwanConntrackRemoved ($sdwanConntrackRemoved + ($change->"removed"))
        :local cleanup [:toarray ""]
        :set ($cleanup->"removed") ($change->"removed")
        :set ($cleanup->"uptime_seconds") $now
        :set ($cleanup->"reason") "WAN address/session changed"
        :set ($sdwanLastCleanup->("link:" . $wn)) $cleanup
        :set ($sdwanEpoch->$wn) 0
        :set ($sdwanFresh->$wn) $now
        :foreach profile,threshold in=($cfg->"sla_profiles") do={
            :local key ($profile . "/" . $wn)
            :set ($sdwanState->$key) "unknown"
            :set ($sdwanGood->$key) 0
            :set ($sdwanBad->$key) 0
            :set ($sdwanLastBad->$key) $now
        }
        :set ($sdwanLinkWarming->$wn) false
        :if ($change->"ready") do={
            :local barrier [:toarray ""]
            :set ($barrier->"not_before") ($now + ($health->"interval_seconds") + ((($health->"timeout_ms") + 999) / 1000) + 1)
            :set ($barrier->"counters") ($change->"counters")
            :set ($sdwanLinkWarming->$wn) $barrier
        }
        :log warning ("SDWAN link " . $wn . " changed; fresh SLA required; conntrack removed=" . ($change->"removed"))
        :local event [:toarray ""]
        :set ($event->"type") "link"; :set ($event->"wan") $wn; :set ($event->"reason") "address/session changed; fresh SLA required"; :set ($event->"removed") ($change->"removed")
        $sdwanRecordEvent event=$event revision=($cfg->"revision")
    }
    :foreach index,wan in=($cfg->"wans") do={
        :if ([:typeof ($sdwanLinkPending->($wan->"name"))] = "array") do={
            :set ($wan->"ready") false
            :set ($wan->"link_reason") "VPN forwarding bindings pending"
            :set (($cfg->"wans")->$index) $wan
        }
    }
    :set sdwanRuntimeWANs ($cfg->"wans")
    :local maintenance [$sdwanMaintenance wans=($cfg->"wans") now=$now]
    :if ([:typeof $sdwanDrainingMarks] != "array") do={ :set sdwanDrainingMarks [:toarray ""] }
    :local retainedMarks [:toarray ""]
    # JSON fractions deserialize as strings on RouterOS; convert explicitly to scaled integers.
    :local scaled do={
        :local text [:tostr $value]
        :local dot [:find $text "."]
        :if ([:typeof $dot] = "nil") do={ :return ([:tonum $text] * $scale) }
        :local whole [:pick $text 0 $dot]
        :local fraction [:pick ($text . "000") ($dot + 1) ($dot + 1 + $digits)]
        :return (([:tonum $whole] * $scale) + [:tonum $fraction])
    }
    # Short-lived DNS/ICMP/TCP entries can expire between find and remove.
    # Ignore only an already vanished entry; preserve permission/other errors.
    :local purge do={
        :local removed 0
        :foreach id in=[/ip/firewall/connection/find where connection-mark=$mark] do={
            :onerror expired in={
                /ip/firewall/connection/remove $id
                :set removed ($removed + 1)
            } do={ :if ([:len [/ip/firewall/connection/find where .id=$id]] > 0) do={ :error $expired } }
        }
        :return $removed
    }
    :local report [:toarray ""]
    :local samples [:toarray ""]
    :local probeDetails [:toarray ""]
    :local policyReport [:toarray ""]
    :foreach wan in=($cfg->"wans") do={
        :local wn ($wan->"name")
        :local carrier [/interface/get [/interface/find where name=($wan->"interface")] running]
        :local running ($carrier && ($wan->"ready"))
        :local warming false
        :local barrier ($sdwanLinkWarming->$wn)
        :if ([:typeof $barrier] = "array") do={
            :local generated ($now >= ($barrier->"not_before"))
            :foreach pid,previous in=($barrier->"counters") do={
                :if ([:len [/tool/netwatch/find where .id=$pid]] != 1) do={ :set generated false } else={
                    :local done [/tool/netwatch/get $pid done-tests]
                    :if (([:typeof $done] != "num") || ($done = 0) || ($done = $previous)) do={ :set generated false }
                }
            }
            :if ($generated) do={ :set ($sdwanLinkWarming->$wn) false } else={ :set warming true }
        }
        :local epoch 2147483647
        :local up 0
        :local total 0
        :foreach probe in=($wan->"probes") do={
            :local tag ("sdwan:v1:probe:" . $wn . ":" . ($probe->"name"))
            :local id [/tool/netwatch/find where comment=$tag]
            :local done 0
            :if ([:len $id] > 0) do={
                :set done [/tool/netwatch/get $id done-tests]
                :local verified [$sdwanProbeAccepted pid=$id probe=$probe wan=$wan raw=$raw health=$health now=$now]
                :set ($probeDetails->($wn . "/" . ($probe->"name"))) $verified
                :if ($verified->"up") do={ :set up ($up + 1) }
            }
            :if ([:typeof $done] != "num") do={ :set done 0 }
            :if ($done < $epoch) do={ :set epoch $done }
            :set total ($total + 1)
        }
        :local icmp [/tool/netwatch/find where comment=("sdwan:v1:icmp:" . $wn)]
        :local rtt 2147483647
        :local jitter 2147483647
        :local loss 10000
        :if ([:len $icmp] > 0) do={
            :local done [/tool/netwatch/get $icmp done-tests]
            :if ([:typeof $done] != "num") do={ :set done 0 }
            :if ($done < $epoch) do={ :set epoch $done }
            :if ([/tool/netwatch/get $icmp response-count] > 0) do={
                :set rtt ([:tonsec [/tool/netwatch/get $icmp rtt-avg]] / 1000)
                :set jitter ([:tonsec [/tool/netwatch/get $icmp rtt-jitter]] / 1000)
            }
            :local sent [/tool/netwatch/get $icmp sent-count]
            :local responses [/tool/netwatch/get $icmp response-count]
            :if ($sent > 0) do={ :set loss ((($sent - $responses) * 10000) / $sent) }
        } else={ :set epoch 0 }
        :if ([:typeof ($sdwanFresh->$wn)] != "num") do={ :set ($sdwanFresh->$wn) $now }
        :local fresh false
        :if ((!$warming) && ($epoch > 0) && ($epoch != ($sdwanEpoch->$wn))) do={
            :set fresh true
            :set ($sdwanEpoch->$wn) $epoch
            :set ($sdwanFresh->$wn) $now
        }
        :local stale (($now - ($sdwanFresh->$wn)) > ($health->"stale_seconds"))
        :if ($stale && (($now % ($health->"interval_seconds")) = 0)) do={ :set fresh true }
        :if ($warming) do={ :set fresh false }
        :local sample [:toarray ""]
        :set ($sample->"interface") ($wan->"interface")
        :set ($sample->"apn_profile") [:tostr ($wan->"apn_profile")]
        :set ($sample->"sample_age_seconds") ($now - ($sdwanFresh->$wn))
        :set ($sample->"kind") ($wan->"kind")
        :set ($sample->"address") ($wan->"address")
        :set ($sample->"gateway") ($wan->"gateway")
        :set ($sample->"route_gateway") ($wan->"route_gateway")
        :set ($sample->"link_reason") ($wan->"link_reason")
        :set ($sample->"carrier") $carrier
        :set ($sample->"link_ready") ($wan->"ready")
        :set ($sample->"warming") $warming
        :set ($sample->"up") $up
        :set ($sample->"total") $total
        :set ($sample->"epoch") $epoch
        :set ($sample->"rtt_us") $rtt
        :set ($sample->"jitter_us") $jitter
        :set ($sample->"loss_basis_points") $loss
        :set ($sample->"running") $running
        :set ($sample->"stale") $stale
        :set ($samples->$wn) $sample
        :foreach profile,threshold in=($cfg->"sla_profiles") do={
            :local rttLimit [$scaled value=($threshold->"rtt_ms") scale=1000 digits=3]
            :local jitterLimit [$scaled value=($threshold->"jitter_ms") scale=1000 digits=3]
            :local lossLimit [$scaled value=($threshold->"loss_percent") scale=100 digits=2]
            :local key ($profile . "/" . $wn)
            :if ([:typeof ($sdwanState->$key)] != "str") do={
                :set ($sdwanState->$key) "unknown"
                :set ($sdwanGood->$key) 0
                :set ($sdwanBad->$key) 0
                :set ($sdwanLastBad->$key) ($now - ($health->"hold_down_seconds"))
            }
            :local old ($sdwanState->$key)
            :local verdict "healthy"
            :local reason "within SLA"
            :if ((!$running) || $warming || $stale || ($up < ($health->"quorum"))) do={
                :set verdict "down"
                :set reason "probe quorum unavailable"
                :if (!$running) do={ :set reason ($wan->"link_reason") }
                :if ($stale) do={ :set reason "stale probe telemetry" }
                :if ($warming) do={ :set reason "address/session changed: waiting for fresh probe generation" }
            } else={
                :if (($rtt > $rttLimit) || ($jitter > $jitterLimit) || ($loss > $lossLimit)) do={
                    :set verdict "degraded"
                    :set reason "SLA threshold exceeded"
                }
            }
            :if ($fresh || (!$running) || $warming) do={
                :if ($verdict = "healthy") do={
                    :set ($sdwanGood->$key) (($sdwanGood->$key) + 1)
                    :set ($sdwanBad->$key) 0
                    :if ($old != "healthy") do={
                        :set ($sdwanState->$key) "recovering"
                        :if ((($sdwanGood->$key) >= ($health->"recover_windows")) && (($now - ($sdwanLastBad->$key)) >= ($health->"hold_down_seconds"))) do={ :set ($sdwanState->$key) "healthy" }
                    }
                } else={
                    :set ($sdwanGood->$key) 0
                    :set ($sdwanBad->$key) (($sdwanBad->$key) + 1)
                    :set ($sdwanLastBad->$key) $now
                    :if ((!$running) || $warming || (($sdwanBad->$key) >= ($health->"fail_windows"))) do={ :set ($sdwanState->$key) $verdict }
                }
            }
            :if ($old != ($sdwanState->$key)) do={ :log warning ("SDWAN state " . $key . " " . $old . " -> " . ($sdwanState->$key) . ": " . $reason) }
            :if ($old != ($sdwanState->$key)) do={
                :local event [:toarray ""]
                :set ($event->"type") "state"; :set ($event->"policy") $key
                :set ($event->"from") $old; :set ($event->"to") ($sdwanState->$key); :set ($event->"reason") $reason
                $sdwanRecordEvent event=$event revision=($cfg->"revision")
            }
            :local detail [:toarray ""]
            :local hold (($health->"hold_down_seconds") - ($now - ($sdwanLastBad->$key)))
            :if (($hold < 0) || (($sdwanState->$key) = "healthy")) do={ :set hold 0 }
            :local remaining (($health->"recover_windows") - ($sdwanGood->$key))
            :if (($remaining < 0) || (($sdwanState->$key) = "healthy")) do={ :set remaining 0 }
            :set ($detail->"hold_remaining_seconds") $hold
            :set ($detail->"recover_windows_remaining") $remaining
            :set ($detail->"state") ($sdwanState->$key)
            :set ($detail->"verdict") $verdict
            :set ($detail->"reason") $reason
            :set ($detail->"good_windows") ($sdwanGood->$key)
            :set ($detail->"bad_windows") ($sdwanBad->$key)
            :set ($detail->"last_bad_seconds") ($sdwanLastBad->$key)
            :set ($report->$key) $detail
        }
        # A confirmed reachability failure retires ingress sessions on this WAN only.
        # SLA degradation of a single client class must not disconnect WAN management.
        :local down (!$running)
        :foreach profile,threshold in=($cfg->"sla_profiles") do={ :if (($sdwanState->($profile . "/" . $wn)) = "down") do={ :set down true } }
        :if ($down && (($sdwanWanDown->$wn) != true)) do={
            :local count 0
            :foreach prefix in={"sdwan-in-";"sdwan-router-"} do={
                :set count ($count + [$purge mark=($prefix . $wn)])
            }
            :set sdwanConntrackRemoved ($sdwanConntrackRemoved + $count)
            :log warning ("SDWAN conntrack ingress " . $wn . " removed=" . $count)
        }
        :set ($sdwanWanDown->$wn) $down
    }
    :local defaultAdmissionClosed false
    :foreach policy in=($cfg->"policies") do={
        :if (($policy->"source") = "") do={
            :set defaultAdmissionClosed true
            :foreach wn in=($policy->"wans") do={ :if ((($maintenance->$wn)->"admit") = true) do={ :set defaultAdmissionClosed false } }
        }
        :local pn ($policy->"name")
        :local selected "none"
        :foreach wn in=($policy->"wans") do={
            :if (($selected = "none") && ((($maintenance->$wn)->"admit") = true) && (($sdwanState->(($policy->"profile") . "/" . $wn)) = "healthy")) do={ :set selected $wn }
        }
        :if (($selected = "none") && ($policy->"allow_degraded")) do={
            :foreach wn in=($policy->"wans") do={
                :if (($selected = "none") && ((($maintenance->$wn)->"admit") = true) && (($sdwanState->(($policy->"profile") . "/" . $wn)) = "degraded")) do={ :set selected $wn }
            }
        }
        # Retain only previously selected/retained marks, while the draining
        # path still meets this policy's SLA and its optional deadline.
        :foreach wn in=($policy->"wans") do={
            :local mark ("sdwan-out-" . $pn . ":" . $wn)
            :local mode ($maintenance->$wn)
            :local state ($sdwanState->(($policy->"profile") . "/" . $wn))
            :local eligible (($state = "healthy") || (($state = "degraded") && ($policy->"allow_degraded")))
            :local retain ((($mode->"retain") = true) && $eligible && ((($sdwanSelected->$pn) = $wn) || (($sdwanDrainingMarks->$mark) = true)))
            :if ($retain) do={ :set ($retainedMarks->$mark) true } else={
                :if (((($sdwanDrainingMarks->$mark) = true) && ($wn != $selected)) || (($mode->"effective") = "down")) do={
                    :local count [$purge mark=$mark]
                    :if (($policy->"source") = "") do={ :set count ($count + [$purge mark=("sdwan-router-" . $wn)]) }
                    :set sdwanConntrackRemoved ($sdwanConntrackRemoved + $count)
                    :if ($count > 0) do={
                        :local cleanup [:toarray ""]; :set ($cleanup->"from") $wn; :set ($cleanup->"to") $selected
                        :set ($cleanup->"removed") $count; :set ($cleanup->"uptime_seconds") $now
                        :set ($cleanup->"reason") "drain ended, channel failed or emergency down"
                        :set ($sdwanLastCleanup->$pn) $cleanup
                        :local event [:toarray ""]; :set ($event->"type") "drain-end"; :set ($event->"policy") $pn
                        :set ($event->"wan") $wn; :set ($event->"removed") $count; :set ($event->"reason") ($cleanup->"reason")
                        $sdwanRecordEvent event=$event revision=($cfg->"revision")
                    }
                }
            }
        }
        :local decision [:toarray ""]
        :local why "first healthy WAN in policy order"
        :if ($selected = "none") do={ :set why "no eligible WAN within SLA; policy fails closed" } else={
            :if (($sdwanState->(($policy->"profile") . "/" . $selected)) = "degraded") do={ :set why "degraded fallback explicitly allowed" }
        }
        :set ($decision->"selected") $selected; :set ($decision->"reason") $why
        :set ($policyReport->$pn) $decision
        # Enable the chosen path before disabling the old path. Distances are distinct.
        :if ($selected != "none") do={
            :local rid [/ip/route/find where comment=("sdwan:v1:route:" . $pn . ":" . $selected)]
            :if ([:len $rid] != 1) do={ :error ("missing or duplicate route " . $pn . "/" . $selected) }
            :if ([/ip/route/get $rid disabled]) do={ /ip/route/enable $rid }
        }
        :foreach wn in=($policy->"wans") do={
            :if ($wn != $selected) do={
                :local rid [/ip/route/find where comment=("sdwan:v1:route:" . $pn . ":" . $wn)]
                :if ([:len $rid] != 1) do={ :error ("missing or duplicate route " . $pn . "/" . $wn) }
                :if (![/ip/route/get $rid disabled]) do={ /ip/route/disable $rid }
            }
        }
        # Disable old classifiers before activating the selected WAN. Per-policy
        # guards prevent an unselected strict/client policy falling into default.
        :foreach wn in=($policy->"wans") do={
            :local id [/ip/firewall/mangle/find where comment=("sdwan:v1:classify:" . $pn . ":" . $wn)]
            :if ([:len $id] != 1) do={ :error ("missing or duplicate classifier " . $pn . "/" . $wn) }
            :if (($wn != $selected) && (![/ip/firewall/mangle/get $id disabled])) do={ /ip/firewall/mangle/disable $id }
        }
        :if ($selected != "none") do={
            :local id [/ip/firewall/mangle/find where comment=("sdwan:v1:classify:" . $pn . ":" . $selected)]
            :if ([/ip/firewall/mangle/get $id disabled]) do={ /ip/firewall/mangle/enable $id }
        }
        :if (($sdwanSelected->$pn) != $selected) do={
            :set ($sdwanCleanupUntil->$pn) ($now + 3)
            :local previous ($sdwanSelected->$pn)
            :if (([:typeof $previous] = "str") && ($previous != "none") && (($retainedMarks->("sdwan-out-" . $pn . ":" . $previous)) != true)) do={
                :local killMarks [:toarray ("sdwan-out-" . $pn . ":" . $previous)]
                :if (($policy->"source") = "") do={ :set killMarks ($killMarks,("sdwan-router-" . $previous)) }
                :local count 0
                :foreach mark in=$killMarks do={
                    :set count ($count + [$purge mark=$mark])
                }
                :set sdwanConntrackRemoved ($sdwanConntrackRemoved + $count)
                :local cleanup [:toarray ""]
                :set ($cleanup->"from") $previous
                :set ($cleanup->"to") $selected
                :set ($cleanup->"removed") $count
                :set ($cleanup->"uptime_seconds") $now
                :set ($sdwanLastCleanup->$pn) $cleanup
                :log warning ("SDWAN conntrack " . $pn . " " . $previous . " -> " . $selected . " removed=" . $count)
            }
            :local event [:toarray ""]
            :set ($event->"type") "policy"; :set ($event->"policy") $pn
            :set ($event->"from") [:tostr ($sdwanSelected->$pn)]; :set ($event->"to") $selected; :set ($event->"reason") $why
            :set ($event->"removed") 0
            :local latest ($sdwanLastCleanup->$pn)
            :if (([:typeof $latest] = "array") && (($latest->"uptime_seconds") = $now)) do={ :set ($event->"removed") ($latest->"removed") }
            $sdwanRecordEvent event=$event revision=($cfg->"revision")
            :log warning ("SDWAN route " . $pn . " " . ($sdwanSelected->$pn) . " -> " . $selected)
            :set ($sdwanSelected->$pn) $selected
        }
        # Packets already in flight at cutover can create a late old-WAN entry.
        # Sweep exact non-selected policy marks for three scheduler seconds;
        # never touch the selected mark, another policy or health-probe marks.
        :if (([:typeof ($sdwanCleanupUntil->$pn)] = "num") && ($now <= ($sdwanCleanupUntil->$pn))) do={
            :local late 0
            :foreach wn in=($policy->"wans") do={
                :if (($wn != $selected) && (($retainedMarks->("sdwan-out-" . $pn . ":" . $wn)) != true)) do={
                    :set late ($late + [$purge mark=("sdwan-out-" . $pn . ":" . $wn)])
                }
            }
            :if ($late > 0) do={
                :set sdwanConntrackRemoved ($sdwanConntrackRemoved + $late)
                :local cleanup ($sdwanLastCleanup->$pn)
                :if ([:typeof $cleanup] != "array") do={ :set cleanup [:toarray ""]; :set ($cleanup->"from") "stale"; :set ($cleanup->"removed") 0 }
                :set ($cleanup->"to") $selected
                :set ($cleanup->"removed") (($cleanup->"removed") + $late)
                :set ($cleanup->"uptime_seconds") $now
                :set ($sdwanLastCleanup->$pn) $cleanup
                :log warning ("SDWAN conntrack late " . $pn . " removed=" . $late)
            }
        }
    }
    :set sdwanDrainingMarks $retainedMarks
    :local overlayReport [:toarray ""]
    :if ((($cfg->"overlay")->"enabled") = true) do={
        :if ($sdwanOverlayLoaded != 1) do={ /import file-name=($dir . "sdwan-overlay.rsc") }
        :set overlayReport [$sdwanOverlayTick cfg=$cfg now=$now]
    }
    :local output [:toarray ""]
    :set ($output->"revision") ($cfg->"revision")
    :set ($output->"uptime_seconds") $now
    :set ($output->"states") $report
    :set ($output->"policies") $policyReport
    :if ([:typeof $sdwanEvents] != "array") do={ :set sdwanEvents [:toarray ""] }
    :set ($output->"events") $sdwanEvents
    :set ($output->"samples") $samples
    :set ($output->"probe_details") $probeDetails
    :set ($output->"selected") $sdwanSelected
    :set ($output->"maintenance") $maintenance
    :set ($output->"overlay") $overlayReport
    :local vpnReport [:toarray ""]
    :if ((($cfg->"vpn_egress")->"enabled") = true) do={
        :foreach wn,row in=$sdwanVPNTransport do={ :set ($vpnReport->$wn) {"underlay"=($row->"underlay");"transport_ready"=($row->"ready")} }
    }
    :set ($output->"vpn_egress") $vpnReport
    :set ($output->"default_admission_closed") $defaultAdmissionClosed
    :set ($output->"draining_marks") $sdwanDrainingMarks
    :set ($output->"controller") "RouterOS local script + scheduler"
    :set ($output->"conntrack_removed") $sdwanConntrackRemoved
    :set ($output->"last_cleanup") $sdwanLastCleanup
    :set sdwanStatusJSON [:serialize to=json value=$output options=json.no-string-conversion]
    :set sdwanLastError ""
} do={
    :if ($sdwanLastError != $err) do={ :log error ("SDWAN controller error: " . $err) }
    :set sdwanLastError $err
    :local output [:toarray ""]
    :set ($output->"error") $err
    :set sdwanStatusJSON [:serialize to=json value=$output]
}
