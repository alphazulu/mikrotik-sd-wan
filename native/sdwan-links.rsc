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

# Create probes with a valid source BEFORE their first enable. New objects
# make the fresh-generation barrier unambiguous after address/session changes.
# The normal 3s start delay also lets RouterOS publish its new forwarding state.
:global sdwanCreateWANProbes do={
    :local wn ($wan->"name")
    /tool/netwatch/remove [/tool/netwatch/find where comment=("sdwan:v1:icmp:" . $wn) or comment~("^sdwan:v1:probe:" . $wn . ":")]
    :local tag ("sdwan:v1:icmp:" . $wn)
    /tool/netwatch/add comment=$tag type=icmp host=($wan->"icmp_target") src-address=($wan->"address") interval=(($health->"interval_seconds") . "s") timeout=(($health->"timeout_ms") . "ms") packet-count=($health->"packet_count") packet-interval=(($health->"packet_interval_ms") . "ms") thr-avg=5s thr-max=5s thr-stdev=5s thr-jitter=5s thr-loss-percent=100% start-delay=3s startup-delay=0s disabled=yes
    :local created [/tool/netwatch/find where comment=$tag]
    :foreach probe in=($wan->"probes") do={
        :set tag ("sdwan:v1:probe:" . $wn . ":" . ($probe->"name"))
        /tool/netwatch/add comment=$tag type=($probe->"type") host=($probe->"host") src-address=($wan->"address") interval=(($health->"interval_seconds") . "s") timeout=(($health->"timeout_ms") . "ms") start-delay=3s startup-delay=0s disabled=yes
        :local pid [/tool/netwatch/find where comment=$tag]
        :if (($probe->"type") = "dns") do={ /tool/netwatch/set $pid dns-server=($probe->"dns_server") record-type=A } else={
            /tool/netwatch/set $pid port=($probe->"port")
            :if ((($probe->"type") = "http-get") || (($probe->"type") = "https-get")) do={ /tool/netwatch/set $pid http-codes=200-299 thr-http-time=5s }
            :if (($probe->"type") = "https-get") do={ /tool/netwatch/set $pid check-certificate=yes }
            :if (($probe->"type") = "tcp-conn") do={ /tool/netwatch/set $pid thr-tcp-conn-time=5s }
        }
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
:global sdwanLinksLoaded 6
