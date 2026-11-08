# Run only on an owned disposable guest, with the canonical admission module and
# native_balance_cases.json uploaded. This uses a private test admission comment.
:local dir ""
:if ([:len [/file/find where name="flash"]] > 0) do={ :set dir "flash/" }
/import file-name=($dir . "sdwan-admission.rsc")
:global sdwanBalanceSlots
:global sdwanAdmissionList
:global sdwanSetAdmission
:global sdwanBalanceSelfTestJSON
:local checks 0
:local tag "sdwan:v1:admission:nativebalancetest"
:local result [:toarray ""]
:onerror err in={
    :local cases [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name=($dir . "native_balance_cases.json")] contents]]
    :foreach sample in=($cases->"valid") do={
        :foreach group in=($sample->"groups") do={
            :local slots [$sdwanBalanceSlots policy=($sample->"policy") mask=($group->"mask")]
            :local expected ($group->"slots")
            :if ([:len $slots] != [:len $expected]) do={ :error "slot count differs from SDK golden case" }
            :local index 0
            :foreach wan in=$expected do={
                :if (($slots->$index) != $wan) do={ :error "slot identity differs from SDK golden case" }
                :set index ($index + 1)
            }
            :set checks ($checks + 1)
        }
    }
    :foreach policy in=($cases->"invalid") do={
        :local rejected false
        :onerror denied in={ :local ignored [$sdwanBalanceSlots policy=$policy mask=(1)] } do={ :set rejected true }
        :if (!$rejected) do={ :error "invalid balance policy was accepted" }
        :set checks ($checks + 1)
    }
    :local indexed [:toarray ""]
    $sdwanSetAdmission indexed=$indexed policyName="nativebalancetest" list="sdwan-a-nativebalancetest-0"
    :local rows [/ip/firewall/address-list/print as-value where comment=$tag]
    :if ([:len $rows] != 1) do={ :error "test admission not created" }
    :foreach row in=$rows do={
        :if (($row->"dynamic") != true) do={ :error "test admission is not RAM-only" }
        :set ($indexed->$tag) $row
    }
    $sdwanSetAdmission indexed=$indexed policyName="nativebalancetest" list="sdwan-b-nativebalancetest-3"
    :set rows [/ip/firewall/address-list/print as-value where comment=$tag]
    :foreach row in=$rows do={
        :if (($row->"list") != "sdwan-b-nativebalancetest-3") do={ :error "test admission did not move" }
        :set ($indexed->$tag) $row
    }
    $sdwanSetAdmission indexed=$indexed policyName="nativebalancetest" list=""
    :if ([:len [/ip/firewall/address-list/find where comment=$tag]] != 0) do={ :error "test admission did not close" }
    :set checks ($checks + 1)
    # A duplicate index must fail before attempting any address-list mutation.
    :set ($indexed->$tag) false
    :local rejected false
    :onerror denied in={ $sdwanSetAdmission indexed=$indexed policyName="nativebalancetest" list="sdwan-a-nativebalancetest-0" } do={ :set rejected true }
    :if ((!$rejected) || ([:len [/ip/firewall/address-list/find where comment=$tag]] != 0)) do={ :error "duplicate index did not fail closed" }
    :set checks ($checks + 1)
    # Existing static/disabled/wrong-address rows are rejected without mutation.
    :foreach row in={{".id"="*invalid";"dynamic"=false;"disabled"=false;"address"="0.0.0.0/0"};{".id"="*invalid";"dynamic"=true;"disabled"=true;"address"="0.0.0.0/0"};{".id"="*invalid";"dynamic"=true;"disabled"=false;"address"="192.0.2.1"}} do={
        :set ($indexed->$tag) $row
        :set rejected false
        :onerror denied in={ $sdwanSetAdmission indexed=$indexed policyName="nativebalancetest" list="sdwan-a-nativebalancetest-0" } do={ :set rejected true }
        :if (!$rejected) do={ :error "invalid indexed admission was accepted" }
        :set checks ($checks + 1)
    }
    :set ($result->"pass") true
} do={ :set ($result->"pass") false; :set ($result->"error") $err }
/ip/firewall/address-list/remove [/ip/firewall/address-list/find where comment=$tag]
:set ($result->"checks") $checks
:set sdwanBalanceSelfTestJSON [:serialize to=json value=$result options=json.no-string-conversion]
