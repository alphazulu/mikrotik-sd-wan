#!/usr/bin/env python3
"""RouterOS-only source-adoption contract; call run(router) on an owned lab DUT.

Uses one temporary scheduler/script and reads the installed native helpers.
It does not edit addresses, routing, firewall, or connection tracking.
Actual tuple retirement and preservation require the separate traffic fixture.
"""
import json
import time

TAG = "sdwan-overlay-source-contract"
RESULT = "sdwanOverlaySourceContract"
POLICY = "read,write,policy,test,sensitive"


def run(router):
    cases = [
        ("untranslated other WAN", "100.64.10.2", True),
        ("chosen WAN", "100.65.10.2", False),
        ("chosen WAN alias", "100.65.10.3", False),
        ("unknown external SNAT", "198.18.210.3", False),
        ("remote address", "198.18.210.1", False),
        ("zero", "0.0.0.0", False),
        ("absent", "", False),
        ("malformed", "bad-ip", False),
        ("IPv6", "2001:db8::1", False),
    ]
    created = []
    try:
        for menu in ("system/script", "system/scheduler"):
            assert not router.call(menu + "/print", {
                ".proplist": ".id", ".query": ["name=" + TAG]}, "POST"), TAG
        source = '''/system/scheduler/disable [/system/scheduler/find where name="'''+TAG+'''"]
:global '''+RESULT+'''
:global sdwanOverlayWrongSource
:onerror failure in={
 :local results [:toarray ""]
 :local localAddresses {"100.64.10.2"=true;"100.65.10.2"=true;"100.65.10.3"=true}
 :local wanAddresses {"100.65.10.2"=true;"100.65.10.3"=true}
 :local cases [:deserialize from=json options=json.no-string-conversion value='''+json.dumps(json.dumps(cases))+''']
 :foreach item in=$cases do={
  :local actual [$sdwanOverlayWrongSource wireSource=($item->1) localAddresses=$localAddresses wanAddresses=$wanAddresses]
  :set ($results->[:len $results]) {"case"=($item->0);"pass"=($actual = ($item->2))}
 }
 :set '''+RESULT+''' [:serialize to=json value=$results options=json.no-string-conversion]
} do={ :set '''+RESULT+''' [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
'''
        script = router.call("system/script/add", {
            "name": TAG, "source": source, "policy": POLICY, "comment": TAG},
            "POST")["ret"]
        created.append(("system/script", script))
        scheduler = router.call("system/scheduler/add", {
            "name": TAG, "on-event": "/system/script/run " + TAG,
            "interval": "1s", "disabled": "true", "policy": POLICY, "comment": TAG},
            "POST")["ret"]
        created.append(("system/scheduler", scheduler))
        assert not router.call("system/script/environment/print", {
            ".proplist": ".id", ".query": ["name=" + RESULT]}, "POST")
        router.call("system/scheduler/" + scheduler, {"disabled": "false"}, "PATCH")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            rows = router.call("system/script/environment/print", {
                ".proplist": "value", ".query": ["name=" + RESULT]}, "POST")
            if rows and rows[0].get("value"):
                try:
                    result = json.loads(rows[0]["value"])
                except (ValueError, TypeError):
                    time.sleep(.2)
                    continue
                assert isinstance(result, list) and len(result) == len(cases), result
                assert all(x["pass"] for x in result), result
                return result
            time.sleep(.2)
        raise AssertionError("Native source contract did not complete")
    finally:
        for menu, item in reversed(created):
            router.call(menu + "/" + item, method="DELETE")
        for row in router.call("system/script/environment/print", {
                ".proplist": ".id", ".query": ["name=" + RESULT]}, "POST"):
            router.call("system/script/environment/" + row[".id"], method="DELETE")
