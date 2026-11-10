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
    previous = {"source_check_version": 2, "source_ready": True,
                "source_check_until": 110}
    window_cases = [
        ("new geometry", previous, False, True, True, 100, 130),
        ("healthy audit continues", previous, True, True, True, 100, 110),
        ("healthy audit expires", previous, True, True, True, 120, 110),
        ("inclusive deadline", previous, True, True, True, 110, 110),
        ("failed probe rearms expired audit", previous, True, True, False, 120, 150),
        ("failure keeps audit open", previous, True, True, False, 160, 190),
        ("physical down clears deadline", previous, True, False, True, 100, 0),
        ("WAN return starts new audit", dict(previous, source_ready=False),
         True, True, True, 120, 150),
        ("old module state rearms", dict(previous, source_check_version=1),
         True, True, True, 120, 150),
        ("absent state rearms", {}, False, True, True, 120, 150),
        ("missing deadline rearms", {"source_check_version": 2, "source_ready": True},
         True, True, True, 120, 150),
        ("observed tuple does not end audit", dict(previous, source_checked=True),
         True, True, True, 100, 110),
    ]
    created = []
    try:
        for menu in ("system/script", "system/scheduler"):
            assert not router.call(menu + "/print", {
                ".proplist": ".id", ".query": ["name=" + TAG]}, "POST"), TAG
        source = '''/system/scheduler/disable [/system/scheduler/find where name="'''+TAG+'''"]
:global '''+RESULT+'''
:global sdwanOverlayWrongSource
:global sdwanOverlaySourceUntil
:onerror failure in={
 :local results [:toarray ""]
 :local localAddresses {"100.64.10.2"=true;"100.65.10.2"=true;"100.65.10.3"=true}
 :local wanAddresses {"100.65.10.2"=true;"100.65.10.3"=true}
 :local cases [:deserialize from=json options=json.no-string-conversion value='''+json.dumps(json.dumps(cases))+''']
 :foreach item in=$cases do={
  :local actual [$sdwanOverlayWrongSource wireSource=($item->1) localAddresses=$localAddresses wanAddresses=$wanAddresses]
  :set ($results->[:len $results]) {"case"=($item->0);"pass"=($actual = ($item->2))}
 }
 :local windows [:deserialize from=json options=json.no-string-conversion value='''+json.dumps(json.dumps(window_cases))+''']
 :foreach item in=$windows do={
  :local actual [$sdwanOverlaySourceUntil previous=($item->1) same=($item->2) ready=($item->3) probeUp=($item->4) now=($item->5)]
  :set ($results->[:len $results]) {"case"=($item->0);"pass"=($actual = ($item->6))}
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
                assert isinstance(result, list) and len(result) == len(cases) + len(window_cases), result
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
