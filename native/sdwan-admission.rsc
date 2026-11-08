# The same static classifier serves prefer and weighted policies. Only a
# dynamic all-addresses membership changes at runtime; no persistent IDs.
:global sdwanAdmissionList do={
    :local index 0
    :foreach name in=($policy->"wans") do={
        :if ($name = $wan) do={ :return ("sdwan-a-" . ($policy->"name") . "-" . $index) }
        :set index ($index + 1)
    }
    :error "admission WAN is outside the policy"
}
:global sdwanSetAdmission do={
    :local tag ("sdwan:v1:admission:" . $policyName)
    :local row ($indexed->$tag)
    :local kind [:typeof $row]
    :if (($kind != "array") && ($kind != "nothing")) do={ :error ("duplicate admission " . $policyName) }
    :if ($kind = "array") do={
        :if (((($row->"dynamic") != true) || (($row->"disabled") != false)) || ([:tostr ($row->"address")] != "0.0.0.0/0")) do={ :error ("invalid RAM admission " . $policyName) }
        :if ($list = "") do={ /ip/firewall/address-list/remove ($row->".id") } else={
            :if (($row->"list") != $list) do={ /ip/firewall/address-list/set ($row->".id") list=$list }
        }
    } else={
        :if ($list != "") do={ /ip/firewall/address-list/add list=$list address=0.0.0.0/0 dynamic=yes comment=$tag }
    }
}
# A small bounded set of precompiled PCC layouts covers every nonempty subset
# of at most four weighted WANs. Zero-weight WANs are priority-only reserves.
:global sdwanBalanceSlots do={
    :local balance ($policy->"balance")
    :if ([:typeof $balance] != "array") do={ :return [:toarray ""] }
    :if (($policy->"mode") != "prefer") do={ :error "balance requires prefer" }
    :local positive [:toarray ""]
    :local reserve false
    :local total 0
    :local allGCD 0
    :local gcd do={ :local x $a; :local y $b; :while ($y != 0) do={ :local r ($x % $y); :set x $y; :set y $r }; :return $x }
    :foreach wan in=($policy->"wans") do={
        :local weight (($balance->"weights")->$wan)
        :if (([:typeof $weight] != "num") || ($weight < 0) || ($weight > 100)) do={ :error "invalid balance weight" }
        :if ($weight = 0) do={ :set reserve true } else={
            :if ($reserve) do={ :error "balance reserves must follow weighted WANs" }
            :set positive ($positive,$wan); :set total ($total + $weight)
            :set allGCD [$gcd a=$allGCD b=$weight]
        }
    }
    :if (([:len $positive] < 2) || ([:len $positive] > 4)) do={ :error "balance requires two to four weighted WANs" }
    :if (($total / $allGCD) > 32) do={ :error "balance slot budget exceeded" }
    :local limit 1
    :foreach wan in=$positive do={ :set limit ($limit * 2) }
    :if (([:typeof $mask] != "num") || ($mask < 1) || ($mask >= $limit)) do={ :return [:toarray ""] }
    :local selected [:toarray ""]
    :local bit 1
    :local divisor 0
    :foreach wan in=$positive do={
        :if ((($mask / $bit) % 2) = 1) do={
            :set selected ($selected,$wan)
            :set divisor [$gcd a=$divisor b=(($balance->"weights")->$wan)]
        }
        :set bit ($bit * 2)
    }
    :local slots [:toarray ""]
    :foreach wan in=$selected do={
        :local count ((($balance->"weights")->$wan) / $divisor)
        :for index from=1 to=$count do={ :set slots ($slots,$wan) }
    }
    :return $slots
}
:global sdwanAdmissionLoaded 1
