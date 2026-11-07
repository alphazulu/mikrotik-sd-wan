# RAM-only cases. Prepend actual helper definitions with labtools/native_policy_snapshot.py.
# Run the generated source in a one-shot lab scheduler; read sdwanSnapshotSelfTestJSON.
:local rows [:toarray ""]
:local indexed [$indexManaged rows=$rows]
:local rejected false
:onerror missing in={ :local ignored [$requireManaged indexed=$indexed tag="absent" label="route test"] } do={ :set rejected ($missing ~ "missing or duplicate") }
:if (!$rejected) do={ :error "empty index accepted a missing object" }
:set ($checks->[:len $checks]) "empty index rejects absent keys, including nothing type"

:local first {"comment"="one";".id"="*1";"disabled"=false}
:set ($rows->0) $first
:set indexed [$indexManaged rows=$rows]
:local found [$requireManaged indexed=$indexed tag="one" label="route test"]
:if ((($found->".id") != "*1") || (($found->"disabled") != false)) do={ :error "single enabled object changed" }
:set ($checks->[:len $checks]) "single enabled object accepted"
:set ($first->"disabled") true
:set ($rows->0) $first
:set indexed [$indexManaged rows=$rows]
:set found [$requireManaged indexed=$indexed tag="one" label="route test"]
:if (($found->"disabled") != true) do={ :error "single disabled object changed" }
:set ($checks->[:len $checks]) "single disabled object accepted"

:foreach copies in={2;3} do={
    :set rows [:toarray ""]
    :for i from=1 to=$copies do={ :set ($rows->[:len $rows]) $first }
    :set indexed [$indexManaged rows=$rows]
    :set rejected false
    :onerror duplicate in={ :local ignored [$requireManaged indexed=$indexed tag="one" label="route test"] } do={ :set rejected ($duplicate ~ "missing or duplicate") }
    :if (!$rejected) do={ :error "duplicate object accepted" }
}
:set ($checks->[:len $checks]) "two and three duplicates stay rejected"

:local other {"comment"="two";".id"="*2";"disabled"=false}
:set ($rows->[:len $rows]) $other
:set indexed [$indexManaged rows=$rows]
:set found [$requireManaged indexed=$indexed tag="two" label="classifier test"]
:if (($found->".id") != "*2") do={ :error "duplicate poisoned another key" }
:set ($checks->[:len $checks]) "duplicates do not poison another object"

:foreach flag in={"false";"true";0;1} do={
    :local bad {"comment"="bad";".id"="*3";"disabled"=$flag}
    :set rows [:toarray ""]; :set ($rows->0) $bad
    :set indexed [$indexManaged rows=$rows]; :set rejected false
    :onerror unknown in={ :local ignored [$requireManaged indexed=$indexed tag="bad" label="route test"] } do={ :set rejected ($unknown ~ "runtime state unavailable") }
    :if (!$rejected) do={ :error "non-boolean disabled flag accepted" }
}
:set ($checks->[:len $checks]) "unknown flag types never become enabled"

:local bad {"comment"="bad";"disabled"=false}
:set rows [:toarray ""]; :set ($rows->0) $bad
:set indexed [$indexManaged rows=$rows]; :set rejected false
:onerror unknown in={ :local ignored [$requireManaged indexed=$indexed tag="bad" label="route test"] } do={ :set rejected ($unknown ~ "runtime state unavailable") }
:if (!$rejected) do={ :error "missing object ID accepted" }
:set ($checks->[:len $checks]) "missing object ID rejected"

:set rows [:toarray ""]; :set ($rows->0) $first
:local original [$indexManaged rows=$rows]
:set ($first->".id") "*4"; :set ($rows->0) $first
:set indexed [$indexManaged rows=$rows]
:set found [$requireManaged indexed=$indexed tag="one" label="route test"]
:if ((($found->".id") != "*4") || ((($original->"one")->".id") != "*1")) do={ :error "fresh snapshot retained an obsolete ID or mutated original" }
:set ($checks->[:len $checks]) "fresh snapshot observes replacement ID"
