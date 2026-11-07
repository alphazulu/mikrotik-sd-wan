# Diagnostics and extended-policy acceptance

[Русский](POLICIES-VALIDATION.md)

Historical iteration report; file/test counts and final fixture state belong to
this run. Current release gates: [CURRENT-STATUS.md](CURRENT-STATUS.en.md).

**Iteration complete: 147 units, 121 CHR checks and five Windows GUI suites PASS.**
All 17 sequential suites exited 0; eight installed RSC files matched frozen source.
Summary: `runtime/policies-final-validation.json`; audit:
`runtime/policies-final-clean-state.json`. UTC: 2026-10-24T00:35:31.381990+00:00.

## New functional checks

`tests/policies_acceptance.py` uses real traffic on five CHR RouterOS 7.24.5 nodes.
It creates temporary tagged VLAN 993 between client and edge, isolated TCP services
and an API session through WAN3. Production MikroTik was not connected.

| Check | Established behavior |
|---|---|
| Order and guard | Explicit priorities, groups, blackhole policy tables; composite selectors have no broad source-only routing rule |
| Four TCP/NAT streams | Source/destination groups, prefixes, ports and actual VLAN ingress match; other clients/ports use their own policies |
| UDP | UDP-specific rule does not inherit a TCP application; connection marks and actual ISP traversal checked |
| Diagnostics | IP/interface, probe age, recovery/hold, reasons, bounded events and new-flow explanation agree with RouterOS |
| Windows GUI | Live API read, groups/dialog/rule reordering, diagnostics, explanation, nine-file/JSON export without password; router unchanged |
| Group | Membership editing recreates managed outgoing flows while preserving incoming API |
| Reapply | Unchanged selectors/groups/order preserve established client streams |
| Order | Priority change selects a different rule for new flows, even on the same WAN |
| Remove conditions | Old protocol/src-port/dst-port matchers disappear; UDP receives the new policy |
| Strict | Silent WAN2 outage cannot send a matching flow through healthy WAN1/WAN3; VLAN and incoming API survive |
| History | Application failure/recovery appear in local RAM history |
| Delete policy | Old marks removed, cleanup counter reflects it, incoming API survives |
| Baseline | Rollback removes owned groups, selectors and blackholes |

Report: `runtime/policies-acceptance.json`. Additional Windows checks cover local
snapshot aging, automatic polling, cleanup after API errors and switching
connections: `runtime/gui-policies-diagnostics-validation.json`. The 147-unit suite
covers old JSON compatibility, overlap/full shadowing, port limits, groups, flow
explanation and SLA diagnostics.

## Protection and history

`tests/policies_protection_acceptance.py`: 105 event-helper calls retain exactly
100 most recent ordered events; native installer rejects a selector on main/default;
a worker failure after actual group/rule creation restores encrypted binary backup,
eight RSC and prior JSON with reboot. Report:
`runtime/policies-protection-acceptance.json`.

The first component run had not loaded the function into its API context
(`typeof=nothing`), although its name appeared in environment. The test now explicitly
loads the same links library; the 100-event boundary then passed. Native source
was unchanged: `runtime/policies-component-scope-evidence.json`.

On that CHR, UDP traceroute with size28 had a zero-length UDP header and did not
create expected conntrack. The fixture explicitly uses size64 and waits for
conntrack publication. Capture/details: `runtime/policies-udp-fixture-note.json`.
Production rules were not changed to bypass this fixture detail.

## General regression

The 16 new checks extend the previous 105 CHR cases: APN/LTE resolver/lifecycle/
protection, static/DHCP/PPPoE mixed lifecycle, dynamic resolver/reconciler,
worker/watchdog/legacy deployment, strict SLA faults, connections, wizard and base
verification. They run sequentially. Full matrix passed: 147 units, 121 CHR checks,
five Windows GUI suites; all 17 suites completed successfully.

Native file SHA256 values were frozen before regression. Final audit compares
installed RSC, checks all five CHRs, absence of fixture groups/VLAN/rules/jobs/host
forwards, exact managed tags and healthy `lab-v1`. Successful suites are not
repeated automatically.

## Limits

IPv4 selectors support addresses/groups/L3 interfaces/protocols/ports. DPI, FQDN
feeds, long-term charts/history, migration of existing OSPF/VPN policies, hardware
and load tests were outside this iteration. History is bounded RAM and resets on
reboot. Control is fully local; routing does not require the GUI.

## Final state

Five CHRs checked. No temporary groups/VLAN/rules, background test/fetch jobs,
component files or host forwards 18996/18997/18998/18999. Managed tags exactly
match baseline config; all eight RSC equal source; no LTE test adapter.
`lab-v1` healthy: default/client101 WAN1, client102 WAN2, strict103 WAN3. Fault proxy
healthy. Production MikroTik was neither connected nor changed. This native
iteration completed; container development continued separately.

Local `runtime/` reports, credentials and device snapshots are excluded from the
repository. Repeatable verification: [TESTING.md](TESTING.en.md).
