# Static / DHCP-client / PPPoE validation

[Русский](DYNAMIC-WAN-VALIDATION.md)

Historical report: counts, file sets and lab state describe this stage. See [current status](CURRENT-STATUS.en.md) for current checks and pending release gates.

Iteration completed on 23 October 2026. The controller runs locally on RouterOS
7.24.5; the external GUI configures it through API. All changes and injected
failures ran on five CHRs. Production MikroTik was unchanged.

**79 units and 78 acceptance checks passed.** Windows GUI smoke and six regressions
for the original Create configuration error also passed. Source-bound SHA256
summary: private `runtime/dynamic-final-validation.json`.

| Suite | PASS | Evidence |
|---|---:|---|
| Mixed lifecycle | 14 | Static + DHCP VLAN + logical PPPoE, Windows API GUI, TCP/NAT/marks, symmetry, address changes, reboot, baseline rollback |
| Dynamic protection | 3 | Option121 without default closes WAN; default recovery; actual binary restore after worker error |
| Resolver | 7 | Live address/peer/gateway, option121, loss/reconnect, duplicate IP guard |
| Reconciler | 4 | Pin/route/probe updates, idempotence, actual ICMP, closed policy routes before SLA |
| Protected deployment | 3 | Fresh API ACK, no ACK, error after API disable; autonomous restore/reboot |
| Deployment | 4 | Alias WAN IPs, local bypass, access with main defaults disabled, full rollback |
| Legacy migration | 2 | Old package without mangle; old files restored and new objects removed after error |
| Native SLA | 15 | Quorum, loss, degradation, priorities, strict policies, hold-down, stale telemetry, fail-closed |
| Connections | 8 | Incoming API/DNAT, actual TCP streams, selective conntrack on failover/failback |
| API wizard | 4 | Discovery, generation, deployment, policy retention |
| Final lab | 14 | Five CHRs, real probes, LAN, routing, priorities |

Individual reports: `runtime/*acceptance.json`; sequence and exit codes:
`runtime/dynamic-regression-suites.json`. Fault suites ran sequentially.

## Dynamic-WAN behavior checked

Deployment permits enabled clients without a lease/session: that WAN stays closed
and a working backup remains available. On address acquisition, the controller
updates source pins, tables, mangle and Netwatch, then waits for fresh measurements
and recovery/hold-down. Lease address/gateway are not saved in JSON.

Three actual background TCP/NAT streams use different WANs. DHCP loss and return
remove only affected policy conntrack; another client's stream and incoming API
through PPPoE survive. DHCP new-IP/new-gateway, option121 gateway change and PPPoE
new-IP are checked with new source NAT and a strict policy. Deleting old sessions
does not transfer TCP seamlessly between public IPs.

Incoming ping/API to each WAN IP replies through that channel. PPPoE DNAT to a
client preferring DHCP for outgoing traffic retains PPPoE on replies. Provider
clients' automatic defaults are isolated and cannot bypass SLA through main.

Reboot restores the library/controller without an external process. Baseline
rollback restores original DHCP/PPPoE routing options and retains the DHCP hook.
A separate faulty install excludes the DHCP WAN and then deliberately fails:
the watchdog restores an encrypted backup, eight previous core/config files,
routing options and the working mixed controller after reboot.

During debugging, starting Netwatch immediately after rebinding reproduced an
ICMP tuple marked and NATed through WAN1 incorrectly. QEMU capture confirmed the
wrong path. Route/mangle readiness waits and `start-delay=3s` were added; final
lifecycle/regression passed with original SLA thresholds. One previous run
coincided with an independent WAN2 SLA switch; a later window log also captured
actual jitter above the 15 ms voice limit. The final complete flow-retention run
passed. Thresholds were not relaxed in that iteration.

## Windows GUI

- `runtime/gui-dynamic-wan-validation.json`: static/DHCP/PPPoE from actual API,
  read-only dynamic fields, editor removal of lease snapshots, valid nine-file
  bundle, API plan and unchanged active JSON.
- `runtime/gui-wizard-validation.json`: actual checkbox WAN selection, policy
  retention, export and plan without router changes.
- `runtime/gui-create-regression.json`: six checks including the original empty
  address error and offline inventory; no network access.

## Final state and limits

Private `runtime/dynamic-final-clean-state.json`: no temporary resources on five
CHRs, background test fetches finished, temporary host forwards removed, fault
proxy healthy. All eight installed RSC files exactly matched source. Edge ran
original `lab-v1`: default/client101 → WAN1, client102 → WAN2, strict103 → WAN3,
all SLA healthy. Baseline contained no temporary provider clients.

Scope: CHR 7.24.5 and admin/full. Duplicate-address VRF, IPv6, real RouterBOARD,
restricted roles and load acceptance require separate work. LTE lifecycle and
overlay were outside this historical iteration and have later checks. PCC/weights
and QoS remain on the [roadmap](../ROADMAP.en.md). This stage completed three WAN
methods, not the whole production SD-WAN.

Local `runtime/` reports, credentials and device snapshots are excluded from the
repository. Repeatable verification: [TESTING.md](TESTING.en.md).
