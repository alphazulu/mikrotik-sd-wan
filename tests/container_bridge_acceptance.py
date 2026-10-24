#!/usr/bin/env python3
"""Native protocol component tests on isolated CHR. Never writes routes."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
import container_lab
from sdwan.router import Router

COMPONENT=r'''
:global sdwanContainerBridge
:global sdwanContainerRaw
:set sdwanContainerRaw ""
:global sdwanContainerBridgeTestJSON
:local cfg [:toarray ""]
:set ($cfg->"revision") "component"
:local p [:toarray ""]
:set ($p->"name") "default"; :set ($p->"profile") "default"
:set ($p->"mode") "prefer"; :set ($p->"wans") {"wan1";"wan2"}; :set ($p->"allow_degraded") false
:set ($cfg->"policies") {$p}
:local first [$sdwanContainerBridge cfg=$cfg raw="component-a" now=100 dir=""]
:local plan [:toarray ""]; :set ($plan->"default") "wan1"
:local intent [:toarray ""]
:set ($intent->"protocol") 1; :set ($intent->"boot_id") ($first->"boot_id")
:set ($intent->"generation") ($first->"generation"); :set ($intent->"revision") "component"
:set ($intent->"observed_uptime") 100; :set ($intent->"instance") "11111111111111111111111111111111"
:set ($intent->"seq") 1; :set ($intent->"selected") $plan; :set ($intent->"release") false
:local save do={ /file/set [/file/find where name="sdwan-container-intent.json"] contents=[:serialize to=json options=json.no-string-conversion value=$intent] }
$save intent=$intent
:local claim [$sdwanContainerBridge cfg=$cfg raw="component-a" now=100 dir=""]
:if (($claim->"rejection") != "") do={ :error "valid claim rejected" }
:if ($claim->"active") do={ :error "claim activated without heartbeat" }
/ip/firewall/address-list/add list=sdwan-container-live address=172.31.255.2 timeout=1m comment=sdwan-test-container-bridge
:set ($intent->"seq") 2; $save intent=$intent
:local active [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:set sdwanContainerBridgeTestJSON [:serialize to=json options=json.no-string-conversion value=$active]
:if ((!($active->"active")) || ((($active->"selected")->"default") != "wan1")) do={ :error ([:serialize to=json options=json.no-string-conversion value=$active] . " FILE=" . [/file/get [/file/find where name="sdwan-container-intent.json"] contents]) }
:set ($intent->"instance") "22222222222222222222222222222222"; :set ($intent->"seq") 3; $save intent=$intent
:local foreign [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($foreign->"rejection") != "intent live foreign owner") do={ :error [:serialize to=json options=json.no-string-conversion value=$foreign] }
:set ($intent->"instance") "11111111111111111111111111111111"; :set ($intent->"seq") 3
:set ($plan->"default") "wan9"; :set ($intent->"selected") $plan; $save intent=$intent
:local bad [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($bad->"rejection") != "intent WAN not allowed") do={ :error "invalid WAN accepted" }
:if ((($bad->"selected")->"default") != "wan1") do={ :error "invalid intent replaced good cache" }
:set ($plan->"default") "wan2"; :set ($intent->"selected") $plan; :set ($intent->"seq") 1; $save intent=$intent
:local replay [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($replay->"rejection") != "intent replay") do={ :error "old sequence accepted" }
:set ($intent->"seq") 4; :set ($intent->"observed_uptime") 90; $save intent=$intent
:local stale [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($stale->"rejection") != "intent observation age") do={ :error "stale observation accepted" }

:set ($intent->"seq") 4; :set ($intent->"observed_uptime") 101; :set ($intent->"release") true; $save intent=$intent
:local released [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if ($released->"active") do={ :error "release did not relinquish ownership" }
:set ($intent->"seq") 2; :set ($intent->"release") false; $save intent=$intent
:local releasedReplay [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($releasedReplay->"rejection") != "intent replay") do={ :error "release allowed old sequence replay" }
:set ($intent->"seq") 5; :set ($intent->"boot_id") "00000000000000000000000000000000"; $save intent=$intent
:local oldBoot [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($oldBoot->"rejection") != "intent boot fence") do={ :error "old boot accepted" }
:set ($intent->"boot_id") ($first->"boot_id")
:local missing [:toarray ""]; :set ($missing->"other") "wan1"; :set ($intent->"selected") $missing; $save intent=$intent
:local missingPolicy [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($missingPolicy->"rejection") != "intent policy missing") do={ :error "missing policy accepted" }
:set ($intent->"selected") $plan; :set ($intent->"observed_uptime") 1000; $save intent=$intent
:local future [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($future->"rejection") != "intent observation age") do={ :error "future observation accepted" }
:set ($intent->"observed_uptime") 101; :set ($intent->"seq") 6; $save intent=$intent
:local reclaimed [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if ((!($reclaimed->"active")) || (($reclaimed->"selected")->"default") != "wan2") do={ :error "fresh reclaim failed" }

:foreach field in={"protocol";"boot_id";"generation";"revision"} do={
    :local incomplete [:toarray ""]
    :foreach itemKey,itemValue in=$intent do={ :if ($itemKey != $field) do={ :set ($incomplete->$itemKey) $itemValue } }
    $save intent=$incomplete
    :local missingFence [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
    :if (([:len [:tostr ($missingFence->"rejection")]] = 0) || (!($missingFence->"active"))) do={ :error "missing fence was accepted or good cache lost" }
}
:local numberProtocol ($intent->"protocol"); :set ($intent->"protocol") "1"; $save intent=$intent
:local stringProtocol [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($stringProtocol->"rejection") != "intent protocol") do={ :error "string protocol was accepted" }
:set ($intent->"protocol") $numberProtocol; $save intent=$intent
/ip/firewall/address-list/remove [/ip/firewall/address-list/find where comment="sdwan-test-container-bridge"]
:local expired [$sdwanContainerBridge cfg=$cfg raw="component-a" now=102 dir=""]
:if (($expired->"active") || (($expired->"owner_instance") != "")) do={ :error "expired lease retained" }
:local changed [$sdwanContainerBridge cfg=$cfg raw="component-b" now=102 dir=""]
:if (($changed->"generation") <= ($first->"generation")) do={ :error "config fence did not advance" }
:if (($changed->"rejection") != "intent configuration fence") do={ :error "old config accepted" }
:global sdwanContainerConfigJSON
:local public [:deserialize from=json options=json.no-string-conversion value=$sdwanContainerConfigJSON]
:if (([:len ($public->"policies")] != 1) || (((($public->"policies")->0)->"name") != "default")) do={ :error "public policy array malformed" }
:local result [:toarray ""]; :set ($result->"pass") true; :set ($result->"checks") 19
/file/set [/file/find where name="sdwan-test-container-bridge-result.json"] contents=[:serialize to=json options=json.no-string-conversion value=$result]
'''

def main():
    lab=container_lab.load()
    creds=json.loads((lab.RUN/'credentials.json').read_text())['edge']
    router=Router(ROOT,'api://127.0.0.1:38728',credentials_data=creds)
    script='sdwan-test-container-bridge.rsc';intent='sdwan-test-container-bridge-intent.json'
    try:
        assert not any(f['name']==intent for f in router.call('file')), 'Intent already exists; do not overwrite active controller'
        router.upload(intent,'')
        router.upload('sdwan-test-container-bridge-result.json','')
        source=(ROOT/'container-controller/routeros/bridge.rsc').read_text()+COMPONENT
        source=source.replace('sdwanContainer','sdwanTestContainer').replace('sdwan-container-intent.json',intent).replace('sdwan-container-live','sdwan-test-container-live')
        router.upload(script,source)
        router.call('import',{'file-name':script},'POST')
        result=json.loads(router.read_file('sdwan-test-container-bridge-result.json'));assert result['pass'] and result['checks']==19
        result.update(route_writes=False,isolated_chr=True)
        (ROOT/'runtime/container-bridge-validation.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    finally:
        for row in router.call('ip/firewall/address-list'):
            if row.get('comment')=='sdwan-test-container-bridge':router.call('ip/firewall/address-list/'+row['.id'],method='DELETE')
        for row in router.call('file'):
            if row['name'] in (script,intent,'sdwan-test-container-bridge-result.json'):router.call('file/'+row['.id'],method='DELETE')
        router.close()

if __name__=='__main__':main()
