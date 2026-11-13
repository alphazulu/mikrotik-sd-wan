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
:set ($intent->"protocol") 2; :set ($intent->"boot_id") ($first->"boot_id")
:set ($intent->"generation") ($first->"generation"); :set ($intent->"revision") "component"
:set ($intent->"observed_uptime") 100; :set ($intent->"instance") "11111111111111111111111111111111"
:set ($intent->"seq") 1; :set ($intent->"selected") $plan; :set ($intent->"release") false
:local save do={ /ip/firewall/address-list/set [/ip/firewall/address-list/find where list="sdwan-container-intent"] comment=[:serialize to=json options=json.no-string-conversion value=$intent] }
/ip/firewall/address-list/add list=sdwan-container-intent address=127.0.0.1 dynamic=yes comment="initial"
$save intent=$intent
:local claim [$sdwanContainerBridge cfg=$cfg raw="component-a" now=100 dir=""]
:if (($claim->"rejection") != "") do={ :error "valid claim rejected" }
:if ($claim->"active") do={ :error "claim activated without heartbeat" }
/ip/firewall/address-list/add list=sdwan-container-live address=172.31.255.2 timeout=1m comment=sdwan-test-container-bridge
:set ($intent->"seq") 2; $save intent=$intent
:local active [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:set sdwanContainerBridgeTestJSON [:serialize to=json options=json.no-string-conversion value=$active]
:if ((!($active->"active")) || ((($active->"selected")->"default") != "wan1")) do={ :error ([:serialize to=json options=json.no-string-conversion value=$active] . " RAM=" . [/ip/firewall/address-list/get [/ip/firewall/address-list/find where list="sdwan-container-intent"] comment]) }
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
:local numberProtocol ($intent->"protocol"); :set ($intent->"protocol") "2"; $save intent=$intent
:local stringProtocol [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($stringProtocol->"rejection") != "intent protocol") do={ :error "string protocol was accepted" }
:set ($intent->"protocol") $numberProtocol; $save intent=$intent
:set ($intent->"protocol") 1; $save intent=$intent
:local legacyProtocol [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if ((($legacyProtocol->"rejection") != "intent protocol") || (!($legacyProtocol->"active"))) do={ :error "legacy file protocol accepted" }
:set ($intent->"protocol") 2
:foreach text in={"";"broken-json"} do={
    /ip/firewall/address-list/set [/ip/firewall/address-list/find where list="sdwan-container-intent"] comment=$text
    :local malformed [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
    :if (([:len [:tostr ($malformed->"rejection")]] = 0) || (!($malformed->"active"))) do={ :error "malformed payload replaced good plan" }
}
# Removing the inbox invalidates cached ownership even with a live heartbeat.
/ip/firewall/address-list/remove [/ip/firewall/address-list/find where list="sdwan-container-intent"]
:local absent [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (($absent->"active") || (($absent->"owner_instance") != "")) do={ :error "missing inbox retained owner" }
:foreach shape in={"static";"wrong-address";"duplicate"} do={
    /ip/firewall/address-list/remove [/ip/firewall/address-list/find where list="sdwan-container-intent"]
    :if ($shape = "static") do={
        /ip/firewall/address-list/add list=sdwan-container-intent address=127.0.0.1 comment="static"
    } else={
        :local address "127.0.0.1"
        :if ($shape = "wrong-address") do={ :set address "127.0.0.2" }
        /ip/firewall/address-list/add list=sdwan-container-intent address=$address dynamic=yes comment="wrong-shape"
        :if ($shape = "duplicate") do={ /ip/firewall/address-list/add list=sdwan-container-intent address=127.0.0.2 dynamic=yes }
    }
    :local rejected [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
    :if ((($rejected->"rejection") != "intent RAM inbox ownership") || ($rejected->"active")) do={ :error ("inbox shape accepted: " . $shape) }
    :if (($rejected->"intent_list") != "") do={ :error "malformed inbox still invites writer retries" }
}
/ip/firewall/address-list/remove [/ip/firewall/address-list/find where list="sdwan-container-intent"]
/ip/firewall/address-list/add list=sdwan-container-intent address=127.0.0.1 dynamic=yes comment="initial"
:set ($intent->"seq") 7; $save intent=$intent
:local restored [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if (!($restored->"active")) do={ :error "fresh RAM claim did not recover" }
# A former on-flash intent is not a protocol-2 input.
/file/set [/file/find where name="sdwan-test-container-bridge-legacy.json"] contents="malformed legacy file"
:local ignoredFile [$sdwanContainerBridge cfg=$cfg raw="component-a" now=101 dir=""]
:if ((!($ignoredFile->"active")) || (($ignoredFile->"rejection") != "")) do={ :error "legacy file influenced RAM bridge" }
/ip/firewall/address-list/remove [/ip/firewall/address-list/find where comment="sdwan-test-container-bridge"]
:local expired [$sdwanContainerBridge cfg=$cfg raw="component-a" now=102 dir=""]
:if (($expired->"active") || (($expired->"owner_instance") != "")) do={ :error "expired lease retained" }
:local changed [$sdwanContainerBridge cfg=$cfg raw="component-b" now=102 dir=""]
:if (($changed->"generation") <= ($first->"generation")) do={ :error "config fence did not advance" }
:if (($changed->"rejection") != "intent configuration fence") do={ :error "old config accepted" }
:global sdwanContainerConfigJSON
:local public [:deserialize from=json options=json.no-string-conversion value=$sdwanContainerConfigJSON]
:if (([:len ($public->"policies")] != 1) || (((($public->"policies")->0)->"name") != "default")) do={ :error "public policy array malformed" }
:local result [:toarray ""]; :set ($result->"pass") true; :set ($result->"checks") 27
/file/set [/file/find where name="sdwan-test-container-bridge-result.json"] contents=[:serialize to=json options=json.no-string-conversion value=$result]
'''

def execute(router):
    script='sdwan-test-container-bridge.rsc';inbox='sdwan-test-container-intent'
    result_name='sdwan-test-container-bridge-result.json'
    legacy='sdwan-test-container-bridge-legacy.json'
    try:
        assert not router.call('ip/firewall/address-list/print',{'.query':['list='+inbox]},'POST'), 'Test inbox already exists'
        assert not any(f['name'] in (script,result_name,legacy) for f in router.call('file')), 'Test file already exists'
        router.upload(result_name,'')
        router.upload(legacy,'')
        source=(ROOT/'container-controller/routeros/bridge.rsc').read_text()+COMPONENT
        source=source.replace('sdwanContainer','sdwanTestContainer').replace('sdwan-container-intent',inbox).replace('sdwan-container-live','sdwan-test-container-live')
        router.upload(script,source)
        router.call('import',{'file-name':script},'POST')
        result=json.loads(router.read_file(result_name));assert result['pass'] and result['checks']==27
        result.update(route_writes=False,isolated_chr=True)
        return result
    finally:
        for row in router.call('ip/firewall/address-list'):
            if row.get('comment')=='sdwan-test-container-bridge' or row.get('list')==inbox:router.call('ip/firewall/address-list/'+row['.id'],method='DELETE')
        for row in router.call('file'):
            if row['name'] in (script,result_name,legacy):router.call('file/'+row['.id'],method='DELETE')

def main():
    lab=container_lab.load()
    creds=json.loads((lab.RUN/'credentials.json').read_text())['edge']
    router=Router(ROOT,'api://127.0.0.1:38728',credentials_data=creds)
    try:
        result=execute(router)
        (ROOT/'runtime/container-bridge-validation.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    finally:router.close()

if __name__=='__main__':main()
