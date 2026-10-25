# Minimal native LTE inventory. Keep profile arrays intact; no PIN/auth reads.
# Some RouterOS enum getters return profile IDs, others return names.
# Resolve each element separately so arrays never become a flattened string.
:global sdwanLTENormalizeProfiles do={
    :local refs [:toarray ""]
    :if ([:typeof $values] = "array") do={ :set refs $values } else={
        :if ([:typeof $values] = "str") do={ :set refs [:toarray $values] } else={
            :if ([:typeof $values] != "nil") do={ :set ($refs->0) $values }
        }
    }
    :local names [:toarray ""]
    :foreach ref in=$refs do={
        :local profileName [:tostr $ref]
        :if ([:len [/interface/lte/apn/find where name=$profileName]] = 0) do={
            :onerror unknown in={ :set profileName [/interface/lte/apn/get $ref name] } do={}
        }
        :set ($names->[:len $names]) $profileName
    }
    :return $names
}
:global sdwanLTEInterfaces do={
    :global sdwanLTENormalizeProfiles
    :local result [:toarray ""]
    :foreach radio in=[/interface/lte/find] do={
        :local profiles ""
        :onerror modern in={ :set profiles [/interface/lte/get $radio apn-profiles] } do={ :set profiles [/interface/lte/get $radio apn-profile] }
        :set profiles [$sdwanLTENormalizeProfiles values=$profiles]
        :local item [:toarray ""]
        :set ($item->"id") [:tostr $radio]
        :set ($item->"name") [/interface/lte/get $radio name]
        :set ($item->"profiles") $profiles
        :set ($item->"disabled") [/interface/lte/get $radio disabled]
        :set ($item->"running") [/interface/lte/get $radio running]
        :set ($result->[:len $result]) $item
    }
    :return $result
}
:global sdwanLTEBinding do={
    :global sdwanLTEInterfaces
    :local found [:toarray ""]
    :local count 0
    :foreach radio in=[$sdwanLTEInterfaces] do={
        :if (($radio->"name") = $iface) do={ :set found $radio; :set count ($count + 1) }
    }
    :if ($count != 1) do={ :error "missing or ambiguous native LTE interface" }
    :local profiles ($found->"profiles")
    :if (([:len $profiles] != 1) || ([:tostr $profile] = "") || (($profiles->0) != $profile)) do={ :error "LTE APN profile changed or multiple APNs; rediscover" }
    :local profileName [:tostr $profile]
    :local pid [/interface/lte/apn/find where name=$profileName]
    :if ([:len $pid] != 1) do={ :error "missing or ambiguous LTE APN profile" }
    :local passthrough [:tostr [/interface/lte/apn/get $pid passthrough-interface]]
    :if (($passthrough != "") && ($passthrough != "none")) do={ :error "LTE passthrough is not a routed WAN" }
    :local ipType [:tostr [/interface/lte/apn/get $pid ip-type]]
    :if (($ipType != "auto") && ($ipType != "ipv4") && ($ipType != "ipv4-ipv6")) do={ :error "LTE APN does not provide IPv4" }
    :set ($found->"apn_id") [:tostr $pid]
    :set ($found->"apn_profile") $profileName
    :set ($found->"add_default_route") [/interface/lte/apn/get $pid add-default-route]
    :return $found
}
# Native LTE APN routing ownership; credentials never leave the existing APN.
# Capture is read-only: caller must persist the baseline BEFORE apply.
:global sdwanLTEAPNCapture do={
    :local profileName [:tostr $profile]
    :local pid [/interface/lte/apn/find where name=$profileName]
    :if ([:len $pid] != 1) do={ :error "missing or ambiguous LTE APN profile" }
    :local passthrough [:tostr [/interface/lte/apn/get $pid passthrough-interface]]
    :if (($passthrough != "") && ($passthrough != "none")) do={ :error "LTE passthrough is not a routed WAN" }
    :local ipType [:tostr [/interface/lte/apn/get $pid ip-type]]
    :if (($ipType != "auto") && ($ipType != "ipv4") && ($ipType != "ipv4-ipv6")) do={ :error "LTE APN does not provide IPv4" }
    # APN options are shared by every modem referencing the profile. Never
    # change a profile used by an unselected modem, including disabled ones.
    :global sdwanLTEInterfaces
    :local radios [$sdwanLTEInterfaces]
    :foreach radio in=$radios do={
        :local radioName ($radio->"name")
        :foreach ref in=($radio->"profiles") do={
            :if ($ref = $profileName) do={
                :local owned false
                :foreach iface in=$selected do={ :if ($iface = $radioName) do={ :set owned true } }
                :if (!$owned) do={ :error ("LTE APN shared with unselected modem " . $radioName) }
            }
        }
    }
    :local entry [:toarray ""]
    :set ($entry->"kind") "lte"
    :set ($entry->"apn_profile") $profileName
    :set ($entry->"id") [:tostr $pid]
    :set ($entry->"original_add") [/interface/lte/apn/get $pid add-default-route]
    :set ($entry->"managed_add") false
    :set ($entry->"interfaces") $selected
    # Distance is conditional and unavailable even through get when add=no.
    :if ($entry->"original_add") do={ :set ($entry->"original_distance") [/interface/lte/apn/get $pid default-route-distance] }
    :return $entry
}
:global sdwanLTEAPNApply do={
    :local profileName ($entry->"apn_profile")
    :local pid [/interface/lte/apn/find where name=$profileName]
    :if (([:len $pid] != 1) || ([:tostr $pid] != ($entry->"id"))) do={ :error "LTE APN identity changed" }
    :local current [/interface/lte/apn/get $pid add-default-route]
    :local expectedValue $expected
    :if ([:typeof $expectedValue] != "bool") do={ :set expectedValue ($entry->"original_add") }
    :if ($current != $expectedValue) do={ :error "LTE APN routing changed before adoption" }
    :if ($current) do={ /interface/lte/apn/set $pid add-default-route=no }
    :if ([/interface/lte/apn/get $pid add-default-route]) do={ :error "LTE APN default route was not disabled" }
}
:global sdwanLTEAPNRestore do={
    :local profileName ($entry->"apn_profile")
    :local pid [/interface/lte/apn/find where name=$profileName]
    :if (([:len $pid] != 1) || ([:tostr $pid] != ($entry->"id"))) do={ :return false }
    :if ([/interface/lte/apn/get $pid add-default-route] != ($entry->"managed_add")) do={ :return false }
    :global sdwanLTEInterfaces
    :foreach radio in=[$sdwanLTEInterfaces] do={
        :foreach ref in=($radio->"profiles") do={
            :if ($ref = $profileName) do={
                :local owned false
                :foreach iface in=($entry->"interfaces") do={ :if ($iface = ($radio->"name")) do={ :set owned true } }
                :if (!$owned) do={ :return false }
            }
        }
    }
    # Only the option we changed is restored. Distance, authentication, DNS,
    # APN string, SIM and operator settings are never written by this helper.
    :if (($entry->"managed_add") != ($entry->"original_add")) do={ /interface/lte/apn/set $pid add-default-route=($entry->"original_add") }
    :return true
}

# Read-only WAN discovery. No address, credential or route mutations here.
# Loaded by the installer/controller; static JSON remains backward compatible.
:global sdwanResolveWANs do={
    :global sdwanLTEBinding
    :local result [:toarray ""]
    :local counts [:toarray ""]
    :foreach spec in=$wans do={
        :local item [:deserialize from=json options=json.no-string-conversion value=[:serialize to=json value=$spec options=json.no-string-conversion]]
        :local mode [:tostr ($spec->"kind")]
        :if ($mode = "") do={ :set mode "static" }
        :local iface [:tostr ($spec->"interface")]
        :local iid [/interface/find where name=$iface]
        :local ready false
        :local reason "interface unavailable"
        :local address ""
        :local gateway ""
        :local nextHop ""
        :if ($mode = "static") do={
            :set address [:tostr ($spec->"address")]
            :set gateway [:tostr ($spec->"gateway")]
            :set nextHop ($gateway . "%" . $iface . "@main")
        }
        :if (([:len $iid] = 1) && [/interface/get $iid running] && (![/interface/get $iid disabled])) do={
            :if ($mode = "static") do={
                :set address [:tostr ($spec->"address")]
                :set gateway [:tostr ($spec->"gateway")]
                :set nextHop ($gateway . "%" . $iface . "@main")
                :set reason "configured address missing"
            }
            :if ($mode = "dhcp") do={
                :local cid [/ip/dhcp-client/find where interface=$iface and disabled=no]
                :set reason "DHCP client missing or ambiguous"
                :if ([:len $cid] = 1) do={
                    :local status [:tostr [/ip/dhcp-client/get $cid status]]
                    :set reason ("DHCP " . $status)
                    :if (($status = "bound") || ($status = "renewing...") || ($status = "rebinding...")) do={
                        :local full [:tostr [/ip/dhcp-client/get $cid address]]
                        :set address [:pick $full 0 [:find $full "/"]]
                        :set gateway [:tostr [/ip/dhcp-client/get $cid gateway]]
                        # Once adopted, DHCP owns routes only in its reserved
                        # probe table. This preserves option 121 semantics and
                        # avoids inventing an option-3 default that was ignored.
                        :local tableName [:tostr ($spec->"probe_table")]
                        :local declared [:tostr [/ip/dhcp-client/get $cid default-route-tables]]
                        :local routeMode [:tostr [/ip/dhcp-client/get $cid add-default-route]]
                        :if (($tableName != "") && ($routeMode != "no") && (($declared = $tableName) || ([:pick $declared 0 ([:len $tableName] + 1)] = ($tableName . ":")))) do={
                            :local defaults [/ip/route/find where routing-table=$tableName and dst-address=0.0.0.0/0 and dynamic=yes]
                            :set gateway ""
                            :set reason "DHCP lease has no unique default route"
                            :if ([:len $defaults] = 1) do={
                                :local rawGateway [:tostr [/ip/route/get $defaults gateway]]
                                :local cut [:find $rawGateway "%"]
                                :if ([:typeof $cut] = "nil") do={ :set cut [:find $rawGateway "@"] }
                                :if ([:typeof $cut] != "nil") do={ :set rawGateway [:pick $rawGateway 0 $cut] }
                                :set gateway $rawGateway
                            }
                        }
                        :set nextHop ($gateway . "%" . $iface . "@main")
                    }
                }
            }
            :if ($mode = "pppoe") do={
                :local cid [/interface/pppoe-client/find where name=$iface and disabled=no]
                :set reason "PPPoE client missing or disabled"
                :if ([:len $cid] = 1) do={
                    # On 7.24.5 monitor once as-value returns nil in scripts
                    # (native API monitor does return fields). The dynamic /32
                    # address has the peer in network, so use the actual IPCP
                    # address assignment and the point-to-point interface route.
                    :local aid [/ip/address/find where interface=$iface and dynamic=yes and disabled=no and invalid=no]
                    :set reason "PPPoE IPv4 negotiation incomplete"
                    :if ([:len $aid] = 1) do={
                        :local full [:tostr [/ip/address/get $aid address]]
                        :set address [:pick $full 0 [:find $full "/"]]
                        :set gateway [:tostr [/ip/address/get $aid network]]
                        :set nextHop $iface
                    }
                }
            }
            :if ($mode = "lte") do={
                :onerror lteError in={
                    :local binding [$sdwanLTEBinding iface=$iface profile=($spec->"apn_profile")]
                    :set reason "LTE APN automatic default is not adopted"
                    :if (!($binding->"add_default_route")) do={
                        :set reason "LTE IPv4 data session unavailable or ambiguous"
                        :local aid [/ip/address/find where interface=$iface and dynamic=yes and disabled=no and invalid=no]
                        :if ([:len $aid] = 1) do={
                            :local full [:tostr [/ip/address/get $aid address]]
                            :set address [:pick $full 0 [:find $full "/"]]
                            :set gateway $iface
                            :set nextHop $iface
                        }
                    }
                } do={ :set reason ("LTE " . $lteError) }
            }
            :local validGateway ([:typeof [:toip $gateway]] = "ip")
            :if (($mode = "lte") && ($gateway = $iface) && ($nextHop = $iface)) do={ :set validGateway true }
            :if ((([:typeof [:toip $address]] = "ip") && $validGateway) && ($address != "0.0.0.0") && ($gateway != "0.0.0.0")) do={
                :foreach aid in=[/ip/address/find where interface=$iface and disabled=no and invalid=no] do={
                    :local full [:tostr [/ip/address/get $aid address]]
                    :if ([:pick $full 0 [:find $full "/"]] = $address) do={ :set ready true; :set reason "ready" }
                }
            }
        }
        :if ($ready) do={
            :local count ($counts->$address)
            :if ([:typeof $count] != "num") do={ :set count 0 }
            :set ($counts->$address) ($count + 1)
        }
        :set ($item->"kind") $mode
        :set ($item->"address") $address
        :set ($item->"gateway") $gateway
        :set ($item->"route_gateway") $nextHop
        :set ($item->"ready") $ready
        :set ($item->"link_reason") $reason
        :set ($result->[:len $result]) $item
    }
    # Identical local addresses cannot be separated by source-address pin rules.
    # Reject both rather than letting probes escape through the other provider.
    :foreach index,item in=$result do={
        :if (($item->"ready") && (($counts->[:tostr ($item->"address")]) > 1)) do={
            :set ($item->"ready") false
            :set ($item->"link_reason") "duplicate WAN address requires VRF isolation"
            :set ($result->$index) $item
        }
    }
    :return $result
}

# Maintenance admits new flows only on enabled WANs. Drain timing is RAM-only.
:global sdwanMaintenance do={
    :global sdwanDrainStarted
    :if ([:typeof $sdwanDrainStarted] != "array") do={ :set sdwanDrainStarted [:toarray ""] }
    :local next [:toarray ""]
    :local report [:toarray ""]
    :foreach wan in=$wans do={
        :local wn ($wan->"name")
        :local mode [:tostr ($wan->"admin_state")]
        :if ($mode = "") do={ :set mode "enabled" }
        :if (($mode != "enabled") && ($mode != "drain") && ($mode != "down")) do={ :error "invalid WAN administrative state" }
        :local timeout ($wan->"drain_timeout_seconds")
        :if (([:typeof $timeout] = "nil") || ([:typeof $timeout] = "nothing")) do={ :set timeout 300 }
        :if (([:typeof $timeout] != "num") || ($timeout < 0) || ($timeout > 86400)) do={ :error "invalid WAN drain deadline" }
        :local row [:toarray ""]
        :set ($row->"configured") $mode
        :set ($row->"admit") ($mode = "enabled")
        :set ($row->"retain") false
        :if ($mode = "drain") do={
            :local started ($sdwanDrainStarted->$wn)
            :if ([:typeof $started] != "num") do={ :set started $now }
            :set ($next->$wn) $started
            :local age ($now - $started)
            :set ($row->"elapsed_seconds") $age
            :set ($row->"timeout_seconds") $timeout
            :set ($row->"retain") (($timeout = 0) || ($age < $timeout))
            :if (($timeout > 0) && ($age >= $timeout)) do={ :set mode "down" }
        }
        :set ($row->"effective") $mode
        :set ($report->$wn) $row
    }
    :set sdwanDrainStarted $next
    :return $report
}
# Administrative-only edits keep fresh SLA and established flow bindings.
:global sdwanHealthSignature do={
    :local signature [:toarray ""]
    :set ($signature->"health") ($cfg->"health")
    :set ($signature->"profiles") ($cfg->"sla_profiles")
    :local rows [:toarray ""]
    :foreach spec in=($cfg->"wans") do={
        :local row [:toarray ""]
        :foreach field in={"name";"interface";"kind";"address";"gateway";"probe_table";"icmp_target";"apn_profile";"probes"} do={ :set ($row->$field) ($spec->$field) }
        :set ($rows->[:len $rows]) $row
    }
    :set ($signature->"wans") $rows
    :return [:serialize to=json value=$signature options=json.no-string-conversion]
}
# Strict expectations never execute blocking HTTP in the control cycle.
:global sdwanProbeNativeType do={
    :local kind ($probe->"type")
    :local path [:tostr ($probe->"http_path")]
    :if (([:typeof ($probe->"http_expected_body")] = "str") || (($path != "") && ($path != "/"))) do={ :return "tcp-conn" }
    :return $kind
}
:global sdwanConfigureProbe do={
    :global sdwanProbeNativeType
    :local kind [$sdwanProbeNativeType probe=$probe]
    :if ($kind = "dns") do={ /tool/netwatch/set $pid dns-server=($probe->"dns_server") record-type=A } else={
        /tool/netwatch/set $pid port=($probe->"port")
        :if (($kind = "http-get") || ($kind = "https-get")) do={
            :local codes "200-299"
            :if ([:typeof ($probe->"http_codes")] = "array") do={
                :set codes ""
                :foreach code in=($probe->"http_codes") do={ :if ([:len $codes] > 0) do={ :set codes ($codes . ",") }; :set codes ($codes . [:tostr $code]) }
            }
            /tool/netwatch/set $pid http-codes=$codes thr-http-time=5s
        }
        :if ($kind = "https-get") do={ /tool/netwatch/set $pid check-certificate=yes }
        :if ($kind = "tcp-conn") do={ /tool/netwatch/set $pid thr-tcp-conn-time=5s }
    }
}
:global sdwanProbeAccepted do={
    :global sdwanStrictResults
    :global sdwanStrictRaw
    :global sdwanStrictSignature
    :global sdwanHealthConfigSignature
    :global sdwanStrictGeneration
    :global sdwanProbeNativeType
    :local result [:toarray ""]
    :set ($result->"up") false; :set ($result->"reason") "transport-down"
    :if (([:len $pid] != 1) || ([/tool/netwatch/get $pid status] != "up")) do={ :return $result }
    :if ((($probe->"type") = "dns") && ([:typeof ($probe->"dns_expected_ips")] = "array")) do={
        # On 7.24.5 this dynamic field is exposed by print, while get ip
        # returns nil even for a successful DNS probe. Read the actual row.
        :local answer ""
        :local probeID [:tostr $pid]
        :foreach row in=[/tool/netwatch/print as-value stats where .id=$probeID] do={ :set answer [:tostr ($row->"ip")] }
        :if ($answer = "") do={ :set ($result->"reason") "dns-answer-unavailable"; :return $result }
        :local matches false
        :foreach expected in=($probe->"dns_expected_ips") do={ :if ([:tostr $expected] = $answer) do={ :set matches true } }
        :if (!$matches) do={ :set ($result->"reason") "dns-mismatch"; :return $result }
    }
    :if ([$sdwanProbeNativeType probe=$probe] != ($probe->"type")) do={
        :set ($result->"reason") "strict-warming"
        :local key (($wan->"name") . "/" . ($probe->"name"))
        :local evidence ($sdwanStrictResults->$key)
        :if (($sdwanStrictSignature != $sdwanHealthConfigSignature) || ([:typeof $evidence] != "array")) do={ :return $result }
        :if ((($evidence->"generation") != $sdwanStrictGeneration) || (($evidence->"probe_id") != [:tostr $pid]) || (($evidence->"source") != ($wan->"address")) || (($evidence->"gateway") != ($wan->"route_gateway"))) do={ :return $result }
        :local interval ($health->"strict_probe_interval_seconds")
        :if ([:typeof $interval] != "num") do={ :set interval 10 }
        :local age ($now - ($evidence->"uptime_seconds"))
        :set ($result->"age_seconds") $age
        :if (($age < 0) || ($age > (($interval * 2) + 3))) do={ :set ($result->"reason") "strict-stale"; :return $result }
        :set ($result->"reason") ($evidence->"reason")
        :if (($evidence->"up") != true) do={ :return $result }
    }
    :set ($result->"up") true; :set ($result->"reason") "verified"
    :return $result
}

# Two bounded asynchronous HTTP workers. Only RAM evidence is retained.
# RouterOS 7.24.5 jobs expose trace paths, including execute + script frames.
# Match complete owned names; removing a parent may already remove its child.
:global sdwanStrictStopJob do={
    :local pattern ("/script:" . $ownedName . "(/|\$)")
    :foreach jid in=[/system/script/job/find where trace~$pattern] do={
        :onerror expired in={ /system/script/job/remove $jid } do={ :if ([:len [/system/script/job/find where .id=$jid]] > 0) do={ :error $expired } }
    }
}
:global sdwanStrictCancel do={
    :global sdwanStrictStopJob
    :foreach slot in={0;1} do={
        :foreach prefix in={"sdwan-strict-worker-";"sdwan-strict-timeout-"} do={
            :local ownedName ($prefix . $slot)
            $sdwanStrictStopJob ownedName=$ownedName
        }
    }
    :global sdwanStrictSlots
    :set sdwanStrictSlots [:toarray ""]
}
:global sdwanValidateStrict do={
    :global sdwanProbeNativeType
    :local count 0
    :foreach wan in=($cfg->"wans") do={
        :if ([:len ($wan->"probes")] > 16) do={ :error "too many WAN probes" }
        :foreach probe in=($wan->"probes") do={
            :local declared [:toarray ""]
            :foreach field,value in=$probe do={ :set ($declared->$field) true }
            :local kind ($probe->"type")
            :local http (($kind = "http-get") || ($kind = "https-get"))
            :foreach field in={"http_codes";"http_path";"http_expected_body"} do={
                :if ((($declared->$field) = true) && (!$http)) do={ :error "HTTP expectation requires HTTP probe" }
            }
            :if (($declared->"http_codes") = true) do={
                :local codes ($probe->"http_codes")
                :if (([:typeof $codes] != "array") || ([:len $codes] < 1) || ([:len $codes] > 16)) do={ :error "invalid HTTP code list" }
                :local seen [:toarray ""]
                :foreach code in=$codes do={
                    :if (([:typeof $code] != "num") || ($code < 100) || ($code > 599) || (($seen->[:tostr $code]) = true)) do={ :error "invalid HTTP code" }
                    :set ($seen->[:tostr $code]) true
                }
            }
            :if (($declared->"http_path") = true) do={
                :local path ($probe->"http_path")
                :if (([:typeof $path] != "str") || ([:len $path] < 1) || ([:len $path] > 256) || ([:pick $path 0 1] != "/") || ([:pick $path 0 2] = "//") || ($path ~ "[^A-Za-z0-9._~!\$&'()*+,;=:@/?%\\-]")) do={ :error "invalid HTTP origin path" }
                :for offset from=0 to=([:len $path] - 1) do={
                    :if ([:pick $path $offset ($offset + 1)] = "%") do={
                        :local hex [:pick $path ($offset + 1) ($offset + 3)]
                        :if (([:len $hex] != 2) || (!($hex ~ "^[0-9a-fA-F][0-9a-fA-F]\$")) || ($hex ~ "^(0.|1.|7[fF])\$")) do={ :error "invalid HTTP path escaping" }
                    }
                }
            }
            :if (($declared->"http_expected_body") = true) do={
                :local body ($probe->"http_expected_body")
                :if (([:typeof $body] != "str") || ([:len $body] > 1024) || ([:typeof [:find $body "\00"]] != "nil")) do={ :error "invalid expected HTTP body" }
            }
            :if (($declared->"dns_expected_ips") = true) do={
                :local answers ($probe->"dns_expected_ips")
                :if (($kind != "dns") || ([:typeof $answers] != "array") || ([:len $answers] < 1) || ([:len $answers] > 16)) do={ :error "invalid DNS expectations" }
                :local seen [:toarray ""]
                :foreach answer in=$answers do={
                    :local ip [:toip $answer]
                    :if (([:typeof $answer] != "str") || ([:typeof $ip] != "ip") || ([:tostr $ip] != $answer) || ($answer = "0.0.0.0") || ($answer = "255.255.255.255") || (($ip >= 224.0.0.0) && ($ip <= 239.255.255.255)) || (($seen->$answer) = true)) do={ :error "invalid expected DNS IP" }
                    :set ($seen->$answer) true
                }
            }
            :if ([$sdwanProbeNativeType probe=$probe] != $kind) do={
                :foreach code in=($probe->"http_codes") do={ :if (($code < 200) || ($code > 299)) do={ :error "HTTP body/path checks require 2xx status codes" } }
                :set count ($count + 1)
            }
        }
    }
    :if ($count > 16) do={ :error "too many strict HTTP probes" }
    :local interval (($cfg->"health")->"strict_probe_interval_seconds")
    :if (([:typeof $interval] = "nil") || ([:typeof $interval] = "nothing")) do={ :set interval 10 }
    :local timeout (($cfg->"health")->"strict_probe_timeout_ms")
    :if (([:typeof $timeout] = "nil") || ([:typeof $timeout] = "nothing")) do={ :set timeout 2000 }
    :if (([:typeof $interval] != "num") || ($interval < 5) || ($interval > 300) || ([:typeof $timeout] != "num") || ($timeout < 100) || ($timeout > 2000)) do={ :error "invalid strict HTTP timing" }
    :if (((($count + 1) / 2) * ((($timeout + 999) / 1000) + 1)) > ($interval * 2)) do={ :error "strict HTTP freshness budget exceeded" }
    :return $count
}
:global sdwanStrictCommit do={
    :global sdwanStrictSlots
    :global sdwanStrictResults
    :global sdwanStrictGeneration
    :global sdwanRuntimeWANs
    :local current ($sdwanStrictSlots->$slot)
    :if ((($current->"token") != ($job->"token")) || (($job->"generation") != $sdwanStrictGeneration)) do={ :return false }
    :local binding false
    :foreach wan in=$sdwanRuntimeWANs do={
        :if ((($wan->"name") = ($job->"wan")) && ($wan->"ready") && (($wan->"address") = ($job->"source")) && (($wan->"route_gateway") = ($job->"gateway"))) do={ :set binding true }
    }
    :local pid [/tool/netwatch/find where comment=($job->"tag")]
    :if ((!$binding) || ([:tostr $pid] != ($job->"probe_id"))) do={ :return false }
    :local evidence [:toarray ""]
    :foreach field in={"generation";"source";"gateway";"probe_id"} do={ :set ($evidence->$field) ($job->$field) }
    :set ($evidence->"up") $up
    :set ($evidence->"reason") $reason
    :set ($evidence->"uptime_seconds") ([:tonsec [/system/resource/get uptime]] / 1000000000)
    :set ($sdwanStrictResults->($job->"key")) $evidence
    :set ($current->"finished") true
    :set ($sdwanStrictSlots->$slot) $current
    :return true
}
:global sdwanStrictWorker do={
    :global sdwanStrictSlots
    :global sdwanStrictCommit
    :local job ($sdwanStrictSlots->$slot)
    :if ([:typeof $job] != "array") do={ :return false }
    :local probe ($job->"probe")
    :local path [:tostr ($probe->"http_path")]
    :if ($path = "") do={ :set path "/" }
    :local scheme "http"
    :if (($probe->"type") = "https-get") do={ :set scheme "https" }
    :local url ($scheme . "://" . ($probe->"host") . ":" . ($probe->"port") . $path)
    :local good false
    :local reason "http-error"
    :local elapsedNS 0
    :onerror requestError in={
        :local response [:toarray ""]
        :local elapsed [:time {
            :if ($scheme = "https") do={
                :set response [/tool/fetch url=$url src-address=($job->"source") output=user as-value http-max-redirect-count=0 check-certificate=yes idle-timeout=1s]
            } else={
                :set response [/tool/fetch url=$url src-address=($job->"source") output=user as-value http-max-redirect-count=0 idle-timeout=1s]
            }
        }]
        :set elapsedNS [:tonsec $elapsed]
        :if (($response->"status") = "finished") do={
            :local code ($response->"code")
            :local allowed (($code >= 200) && ($code <= 299))
            :if ([:typeof ($probe->"http_codes")] = "array") do={
                :set allowed false
                :foreach expected in=($probe->"http_codes") do={ :if ($code = $expected) do={ :set allowed true } }
            }
            :set reason "http-code"
            :if ($allowed) do={
                :local body ($response->"data")
                :set reason "http-oversize"
                :if (([:typeof $body] = "str") && ([:len $body] <= 1024)) do={
                    :set reason "http-body"
                    :if (([:typeof ($probe->"http_expected_body")] != "str") || ($body = ($probe->"http_expected_body"))) do={ :set good true; :set reason "verified" }
                }
            }
        }
    } do={}
    :if ($elapsedNS > (($job->"timeout_ms") * 1000000)) do={ :set good false; :set reason "strict-timeout" }
    :return [$sdwanStrictCommit slot=$slot job=$job up=$good reason=$reason]
}
:global sdwanStrictTimeout do={
    :global sdwanStrictStopJob
    :global sdwanStrictSlots
    :global sdwanStrictCommit
    :local job ($sdwanStrictSlots->$slot)
    :if ([:typeof $job] != "array") do={ :return false }
    :delay (($job->"timeout_ms") . "ms")
    :local current ($sdwanStrictSlots->$slot)
    :if (($current->"token") != ($job->"token")) do={ :return false }
    :if (($current->"finished") != true) do={
        :local ownedName ("sdwan-strict-worker-" . $slot)
        $sdwanStrictStopJob ownedName=$ownedName
        $sdwanStrictCommit slot=$slot job=$job up=(false) reason="strict-timeout"
    }
    :set ($sdwanStrictSlots->$slot)
    :return true
}
:global sdwanStrictDispatch do={
    :global sdwanStrictStopJob
    :global sdwanStrictCommit
    :global sdwanConfigRaw
    :global sdwanStrictRaw
    :global sdwanStrictConfig
    :global sdwanStrictSignature
    :global sdwanHealthConfigSignature
    :global sdwanStrictGeneration
    :global sdwanStrictResults
    :global sdwanStrictSlots
    :global sdwanStrictDue
    :global sdwanStrictCursor
    :global sdwanStrictSequence
    :global sdwanRuntimeWANs
    :global sdwanStrictCancel
    :global sdwanProbeNativeType
    :if ([:typeof $sdwanConfigRaw] != "str") do={ :return false }
    :if ($sdwanStrictRaw != $sdwanConfigRaw) do={
        :set sdwanStrictConfig [:deserialize from=json options=json.no-string-conversion value=$sdwanConfigRaw]
        :set sdwanStrictRaw $sdwanConfigRaw
    }
    :if ($sdwanStrictSignature != $sdwanHealthConfigSignature) do={
        $sdwanStrictCancel
        :if ([:typeof $sdwanStrictGeneration] != "num") do={ :set sdwanStrictGeneration 0 }
        :set sdwanStrictGeneration ($sdwanStrictGeneration + 1)
        :set sdwanStrictSignature $sdwanHealthConfigSignature
        :set sdwanStrictResults [:toarray ""]
        :set sdwanStrictDue [:toarray ""]
        :set sdwanStrictCursor 0
    }
    :if ([:typeof $sdwanStrictSlots] != "array") do={ :set sdwanStrictSlots [:toarray ""] }
    :if ([:typeof $sdwanStrictDue] != "array") do={ :set sdwanStrictDue [:toarray ""] }
    :if ([:typeof $sdwanStrictCursor] != "num") do={ :set sdwanStrictCursor 0 }
    :if ([:typeof $sdwanStrictSequence] != "num") do={ :set sdwanStrictSequence 0 }
    :local nowNS [:tonsec [/system/resource/get uptime]]
    :local now ($nowNS / 1000000000)
    :local queue [:toarray ""]
    :foreach wan in=$sdwanRuntimeWANs do={
        :if ($wan->"ready") do={
            :foreach probe in=($wan->"probes") do={
                :if ([$sdwanProbeNativeType probe=$probe] != ($probe->"type")) do={
                    :local item [:toarray ""]
                    :set ($item->"wan") ($wan->"name"); :set ($item->"probe") $probe
                    :set ($item->"source") ($wan->"address"); :set ($item->"gateway") ($wan->"route_gateway")
                    :set ($item->"key") (($wan->"name") . "/" . ($probe->"name"))
                    :set ($item->"tag") ("sdwan:v1:probe:" . ($wan->"name") . ":" . ($probe->"name"))
                    :set ($queue->[:len $queue]) $item
                }
            }
        }
    }
    :local interval (($sdwanStrictConfig->"health")->"strict_probe_interval_seconds")
    :if ([:typeof $interval] != "num") do={ :set interval 10 }
    :local timeout (($sdwanStrictConfig->"health")->"strict_probe_timeout_ms")
    :if ([:typeof $timeout] != "num") do={ :set timeout 2000 }
    :foreach slot in={0;1} do={
        :local running ($sdwanStrictSlots->$slot)
        :if (([:typeof $running] = "array") && (($nowNS - ($running->"started_ns")) > (($timeout + 3000) * 1000000))) do={
            :foreach prefix in={"sdwan-strict-worker-";"sdwan-strict-timeout-"} do={ :local ownedName ($prefix . $slot); $sdwanStrictStopJob ownedName=$ownedName }
            $sdwanStrictCommit slot=$slot job=$running up=(false) reason="strict-timeout"
            :set ($sdwanStrictSlots->$slot)
            :set running
        }
        :if (([:typeof $running] != "array") && ([:len $queue] > 0)) do={
            :local chosen false
            :local tries 0
            :while ((!$chosen) && ($tries < [:len $queue])) do={
                :local index ($sdwanStrictCursor % [:len $queue])
                :set sdwanStrictCursor ($index + 1)
                :set tries ($tries + 1)
                :local item ($queue->$index)
                :local key ($item->"key")
                :local due ($sdwanStrictDue->$key)
                :local busy false
                :foreach other in=$sdwanStrictSlots do={ :if (($other->"key") = $key) do={ :set busy true } }
                :local pid [/tool/netwatch/find where comment=($item->"tag")]
                :local previous ($sdwanStrictResults->$key)
                :if (([:typeof $previous] != "array") || (($previous->"probe_id") != [:tostr $pid]) || (($previous->"source") != ($item->"source")) || (($previous->"gateway") != ($item->"gateway"))) do={ :set due 0 }
                :if ((!$busy) && (([:typeof $due] != "num") || ($now >= $due)) && ([:len $pid] = 1)) do={
                    :set chosen true
                    :set sdwanStrictSequence ($sdwanStrictSequence + 1)
                    :set ($item->"token") $sdwanStrictSequence; :set ($item->"generation") $sdwanStrictGeneration
                    :set ($item->"probe_id") [:tostr $pid]; :set ($item->"started_ns") $nowNS
                    :set ($item->"timeout_ms") $timeout; :set ($item->"finished") false
                    :set ($sdwanStrictSlots->$slot) $item; :set ($sdwanStrictDue->$key) ($now + $interval)
                    :execute script=("/system/script/run sdwan-strict-worker-" . $slot)
                    :execute script=("/system/script/run sdwan-strict-timeout-" . $slot)
                }
            }
        }
    }
    :return true
}
:global sdwanStrictConfigure do={
    :global sdwanValidateStrict
    :global sdwanStrictCancel
    :local count [$sdwanValidateStrict cfg=$cfg]
    :local scheduler [/system/scheduler/find where name="sdwan-strict-dispatch"]
    :if ([:len $scheduler] = 1) do={ /system/scheduler/disable $scheduler }
    $sdwanStrictCancel
    :foreach ownedName in={"sdwan-strict-worker-0";"sdwan-strict-worker-1";"sdwan-strict-timeout-0";"sdwan-strict-timeout-1";"sdwan-strict-dispatch"} do={
        :local id [/system/script/find where name=$ownedName]
        :if ($count = 0) do={ /system/script/remove $id } else={
            :local source ":global sdwanStrictDispatch; \$sdwanStrictDispatch"
            :if ($ownedName ~ "worker") do={ :set source (":global sdwanStrictWorker; \$sdwanStrictWorker slot=(" . [:pick $ownedName ([:len $ownedName] - 1) [:len $ownedName]] . ")") }
            :if ($ownedName ~ "timeout") do={ :set source (":global sdwanStrictTimeout; \$sdwanStrictTimeout slot=(" . [:pick $ownedName ([:len $ownedName] - 1) [:len $ownedName]] . ")") }
            :if ([:len $id] = 0) do={ /system/script/add name=$ownedName source=$source policy=read,write,policy,test,sensitive comment="sdwan:v1:strict" } else={ /system/script/set $id source=$source policy=read,write,policy,test,sensitive }
        }
    }
    :if ($count = 0) do={
        /system/scheduler/remove $scheduler
        :global sdwanStrictResults; :global sdwanStrictDue; :global sdwanStrictConfig; :global sdwanStrictRaw; :global sdwanStrictSignature; :global sdwanStrictGeneration
        :set sdwanStrictResults [:toarray ""]; :set sdwanStrictDue [:toarray ""]; :set sdwanStrictConfig [:toarray ""]
        :set sdwanStrictRaw ""; :set sdwanStrictSignature ""
        :if ([:typeof $sdwanStrictGeneration] != "num") do={ :set sdwanStrictGeneration 0 }
        :set sdwanStrictGeneration ($sdwanStrictGeneration + 1)
    } else={
        :if ([:len $scheduler] = 0) do={ /system/scheduler/add name=sdwan-strict-dispatch interval=1s start-time=startup on-event="/system/script/run sdwan-strict-dispatch" policy=read,write,policy,test,sensitive comment="sdwan:v1:strict" } else={ /system/scheduler/set $scheduler disabled=no }
    }
}

# Create probes with a valid source BEFORE their first enable. New objects
# make the fresh-generation barrier unambiguous after address/session changes.
# The normal 3s start delay also lets RouterOS publish its new forwarding state.
:global sdwanCreateWANProbes do={
    :global sdwanProbeNativeType
    :global sdwanConfigureProbe
    :local wn ($wan->"name")
    /tool/netwatch/remove [/tool/netwatch/find where comment=("sdwan:v1:icmp:" . $wn) or comment~("^sdwan:v1:probe:" . $wn . ":")]
    :local tag ("sdwan:v1:icmp:" . $wn)
    /tool/netwatch/add comment=$tag type=icmp host=($wan->"icmp_target") src-address=($wan->"address") interval=(($health->"interval_seconds") . "s") timeout=(($health->"timeout_ms") . "ms") packet-count=($health->"packet_count") packet-interval=(($health->"packet_interval_ms") . "ms") thr-avg=5s thr-max=5s thr-stdev=5s thr-jitter=5s thr-loss-percent=100% start-delay=3s startup-delay=0s disabled=yes
    :local created [/tool/netwatch/find where comment=$tag]
    :foreach probe in=($wan->"probes") do={
        :set tag ("sdwan:v1:probe:" . $wn . ":" . ($probe->"name"))
        /tool/netwatch/add comment=$tag type=[$sdwanProbeNativeType probe=$probe] host=($probe->"host") src-address=($wan->"address") interval=(($health->"interval_seconds") . "s") timeout=(($health->"timeout_ms") . "ms") start-delay=3s startup-delay=0s disabled=yes
        :local pid [/tool/netwatch/find where comment=$tag]
        $sdwanConfigureProbe pid=$pid probe=$probe
        :set created ($created,$pid)
    }
    :local counters [:toarray ""]
    :foreach pid in=$created do={ :set ($counters->[:tostr $pid]) 0 }
    /tool/netwatch/enable $created
    :return $counters
}

# Reconcile only runtime-dependent fields of already installed objects.
# The caller owns SLA/selection and enables policy routes AFTER fresh probes.
:global sdwanReconcileWANs do={
    :global sdwanCreateWANProbes
    :global sdwanLinkFingerprints
    :if ([:typeof $sdwanLinkFingerprints] != "array") do={ :set sdwanLinkFingerprints [:toarray ""] }
    :local changes [:toarray ""]
    :local purge do={
        :local removed 0
        :foreach cid in=[/ip/firewall/connection/find where connection-mark=$mark] do={
            :onerror expired in={ /ip/firewall/connection/remove $cid; :set removed ($removed + 1) } do={ :if ([:len [/ip/firewall/connection/find where .id=$cid]] > 0) do={ :error $expired } }
        }
        :return $removed
    }
    :foreach wan in=$wans do={
        :local wn ($wan->"name")
        :local mode ($wan->"kind")
        :if ($mode != "static") do={
            :local signature ([:tostr ($wan->"ready")] . ":" . ($wan->"address") . ":" . ($wan->"route_gateway") . ":" . ($wan->"interface"))
            :if (($sdwanLinkFingerprints->$wn) != $signature) do={
                :local wasKnown ([:typeof ($sdwanLinkFingerprints->$wn)] = "str")
                :local pin [/ip/route/find where comment=("sdwan:v1:pinroute:" . $wn)]
                :if ([:len $pin] != 1) do={ :error ("missing or duplicate runtime pin route " . $wn) }
                /ip/route/disable $pin
                :local removed 0
                :foreach policy in=$policies do={
                    :local pn ($policy->"name")
                    :foreach allowed in=($policy->"wans") do={
                        :if ($allowed = $wn) do={
                            /ip/route/disable [/ip/route/find where comment=("sdwan:v1:route:" . $pn . ":" . $wn)]
                            /ip/firewall/mangle/disable [/ip/firewall/mangle/find where comment=("sdwan:v1:classify:" . $pn . ":" . $wn)]
                            :set removed ($removed + [$purge mark=("sdwan-out-" . $pn . ":" . $wn)])
                        }
                    }
                }
                # Probe tuples are not user sessions; let old-source probe
                # tuples expire while the new source pins take over.
                :foreach prefix in={"sdwan-in-";"sdwan-router-"} do={ :set removed ($removed + [$purge mark=($prefix . $wn)]) }
                :local probes [/tool/netwatch/find where comment=("sdwan:v1:icmp:" . $wn) or comment~("^sdwan:v1:probe:" . $wn . ":")]
                /tool/netwatch/disable $probes
                :local counters [:toarray ""]
                :foreach pid in=$probes do={ :set ($counters->[:tostr $pid]) [/tool/netwatch/get $pid done-tests] }
                :local pinRule [/routing/rule/find where comment=("sdwan:v1:pinrule:" . $wn)]
                :if ([:len $pinRule] > 0) do={ /routing/rule/remove $pinRule }
                :local bindings [/ip/firewall/mangle/find where comment=("sdwan:v1:source:" . $wn) or comment~("^sdwan:v1:probe-classify:" . $wn . ":")]
                /ip/firewall/mangle/disable $bindings
                :if ($wan->"ready") do={
                    :local source (($wan->"address") . "/32")
                    :local before ""
                    :foreach rid in=[/routing/rule/find] do={
                        :if (($before = "") && (!([/routing/rule/get $rid comment] ~ "^sdwan:v1:local:"))) do={ :set before $rid }
                    }
                    :local table ($wan->"probe_table")
                    :local tag ("sdwan:v1:pinrule:" . $wn)
                    :if ([:len $before] = 0) do={ /routing/rule/add src-address=$source table=$table action=lookup-only-in-table comment=$tag } else={ /routing/rule/add src-address=$source table=$table action=lookup-only-in-table comment=$tag place-before=$before }
                    /ip/route/set $pin gateway=($wan->"route_gateway") disabled=no
                    :foreach policy in=$policies do={
                        :local id [/ip/route/find where comment=("sdwan:v1:route:" . ($policy->"name") . ":" . $wn)]
                        :if ([:len $id] > 0) do={ /ip/route/set $id gateway=($wan->"route_gateway") check-gateway=none }
                    }
                    :foreach bid in=$bindings do={ /ip/firewall/mangle/set $bid src-address=$source disabled=no }
                    # Route/mangle updates reach the forwarding plane asynchronously.
                    # Do not start a persistent ICMP tuple against the old main WAN.
                    :local usable false
                    :local attempt 0
                    :while ((!$usable) && ($attempt < 20)) do={
                        :set attempt ($attempt + 1)
                        :set usable ([:len [/ip/route/find where .id=$pin and active=yes and disabled=no]] = 1)
                        :foreach bid in=$bindings do={
                            :if ([:len [/ip/firewall/mangle/find where .id=$bid and invalid=no and disabled=no]] != 1) do={ :set usable false }
                        }
                        :if (!$usable) do={ :delay 50ms }
                    }
                    :if (!$usable) do={ :error ("runtime WAN bindings not ready " . $wn) }
                    :set counters [$sdwanCreateWANProbes wan=$wan health=$health]
                }
                :local change [:toarray ""]
                :set ($change->"ready") ($wan->"ready")
                :set ($change->"was_known") $wasKnown
                :set ($change->"removed") $removed
                :set ($change->"counters") $counters
                :set ($changes->$wn) $change
                # Publish only after EVERY mutation succeeded; failed operations
                # will be retried next scheduler run with routes still closed.
                :set ($sdwanLinkFingerprints->$wn) $signature
            }
        }
    }
    :return $changes
}

# Baseline rollback changes routing options only, never credentials or hooks.
:global sdwanRestoreProviderClients do={
    :foreach key,item in=$entries do={
        :local iface ($item->"interface")
        :local mode ($item->"kind")
        :local id ""
        :if ($mode = "dhcp") do={ :set id [/ip/dhcp-client/find where interface=$iface] } else={ :set id [/interface/pppoe-client/find where name=$iface] }
        :local owned false
        :if (([:len $id] = 1) && ([:tostr $id] = ($item->"id"))) do={
            :if ($mode = "dhcp") do={
                :set owned (([:tostr [/ip/dhcp-client/get $id add-default-route]] = [:tostr ($item->"managed_add")]) && ([:tostr [/ip/dhcp-client/get $id default-route-tables]] = [:tostr ($item->"managed_tables")]))
                :if ($owned) do={
                    /ip/dhcp-client/set $id add-default-route=no
                    /ip/dhcp-client/set $id default-route-tables=($item->"original_tables")
                    /ip/dhcp-client/set $id add-default-route=($item->"original_add")
                }
            } else={
                :set owned ([:tostr [/interface/pppoe-client/get $id add-default-route]] = [:tostr ($item->"managed_add")])
                :if ($owned) do={ /interface/pppoe-client/set $id add-default-route=($item->"original_add") }
            }
        }
        :if (!$owned) do={ :log warning ("SDWAN baseline skipped changed or missing provider client " . $iface) }
    }
}
# Policy helpers share the existing package; no external decision process.
:global sdwanPolicyExtended do={
    :foreach field in={"source_group";"destination";"destination_group";"in_interface";"src_ports";"dst_ports"} do={ :if ([:len [:tostr ($policy->$field)]] > 0) do={ :return true } }
    :local proto [:tostr ($policy->"protocol")]
    :return (($proto != "") && ($proto != "any"))
}
:global sdwanOrderPolicies do={
    :local result [:toarray ""]
    :local used [:toarray ""]
    :for pass from=1 to=[:len $policies] do={
        :local best 2147483647
        :local selected -1
        :foreach index,item in=$policies do={
            :if ((($item->"source") != "") && (($used->[:tostr $index]) != true)) do={
                :local rank ($item->"priority")
                :if ([:typeof $rank] != "num") do={ :set rank (1000000 + $index) }
                :if ($rank < $best) do={ :set best $rank; :set selected $index }
            }
        }
        :if ($selected >= 0) do={ :set ($result->[:len $result]) ($policies->$selected); :set ($used->[:tostr $selected]) true }
    }
    :foreach item in=$policies do={ :if (($item->"source") = "") do={ :set ($result->[:len $result]) $item } }
    :return $result
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
        :foreach field in={"name";"source";"source_group";"destination";"destination_group";"in_interface";"protocol";"src_ports";"dst_ports";"priority"} do={
            :local v [:tostr ($item->$field)]
            :if (($field = "protocol") && ($v = "")) do={ :set v "any" }
            :set ($row->$field) $v
        }
        :set ($rows->[:len $rows]) $row
    }
    :set ($value->"policies") $rows
    :return [:serialize to=json value=$value options=json.no-string-conversion]
}
:global sdwanApplyPolicyMatch do={
    :local source [:tostr ($policy->"source")]
    :if ($source = "") do={ :set source "0.0.0.0/0" }
    /ip/firewall/mangle/set $rule src-address=$source
    :if ([:len [:tostr ($policy->"source_group")]] > 0) do={ /ip/firewall/mangle/set $rule src-address-list=("sdwan-group-" . ($policy->"source_group")) }
    :if ([:len [:tostr ($policy->"destination")]] > 0) do={ /ip/firewall/mangle/set $rule dst-address=($policy->"destination") }
    :if ([:len [:tostr ($policy->"destination_group")]] > 0) do={ /ip/firewall/mangle/set $rule dst-address-list=("sdwan-group-" . ($policy->"destination_group")) }
    :if ([:len [:tostr ($policy->"in_interface")]] > 0) do={ /ip/firewall/mangle/set $rule in-interface=($policy->"in_interface") }
    :local proto [:tostr ($policy->"protocol")]
    :if (($proto != "") && ($proto != "any")) do={ /ip/firewall/mangle/set $rule protocol=$proto }
    :if ([:len [:tostr ($policy->"src_ports")]] > 0) do={ /ip/firewall/mangle/set $rule src-port=($policy->"src_ports") }
    :if ([:len [:tostr ($policy->"dst_ports")]] > 0) do={ /ip/firewall/mangle/set $rule dst-port=($policy->"dst_ports") }
}

# Bounded RAM history, reset naturally on reboot. No periodic flash writes.
:global sdwanRecordEvent do={
    :global sdwanEvents
    :global sdwanEventSequence
    :if ([:typeof $sdwanEvents] != "array") do={ :set sdwanEvents [:toarray ""] }
    :if ([:typeof $sdwanEventSequence] != "num") do={ :set sdwanEventSequence 0 }
    :set sdwanEventSequence ($sdwanEventSequence + 1)
    :local row $event
    :set ($row->"seq") $sdwanEventSequence
    :set ($row->"uptime_seconds") ([:tonsec [/system/resource/get uptime]] / 1000000000)
    :set ($row->"revision") $revision
    :if ([:len $sdwanEvents] >= 100) do={ :set sdwanEvents [:pick $sdwanEvents ([:len $sdwanEvents] - 99) [:len $sdwanEvents]] }
    :set ($sdwanEvents->[:len $sdwanEvents]) $row
}
:global sdwanLinksLoaded 7
