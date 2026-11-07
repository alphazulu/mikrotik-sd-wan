# Static, DHCP-client, PPPoE and LTE WANs

[Русский](DYNAMIC-WAN.md) | English

This page describes four physical addressing methods. Existing VPNs also join
common WAN policies; see their [transport guide](VPN-EGRESS.en.md).

Controller, installer and GUI support these four IPv4 methods. LTE/APN was a
separate [iteration](LTE.en.md). Historical 79 unit/78 acceptance checks below
cover the first three types on CHR 7.24.5, including mixed lifecycle, emergency
recovery and Windows GUI regression. [Report](DYNAMIC-WAN-VALIDATION.en.md).

## Configuration

`kind` is `static`, `dhcp`, `pppoe` or `lte`; omission means static for old JSON.

- Static requires `interface`, assigned static `address` and `gateway`, pinned
  as `IP%interface@main`.
- DHCP selects the existing DHCP-client interface, Ethernet or VLAN. `address`
  and `gateway` are absent/empty; lease snapshots are rejected.
- PPPoE selects an existing logical client such as `pppoe-out1`, not its physical
  parent. Do not save address/gateway.
- LTE selects native LTE plus its existing `apn_profile`, without address/gateway.
  Automatic default is managed through `/interface/lte/apn`, not DHCP-client.
  See [LTE](LTE.en.md).

Other WAN fields are shared: unique name, probe table, ICMP target and application
probes. Normal prefer/strict policies set priority. Provider client, credentials
and NAT must already exist; the wizard does not create clients or read passwords.

API discovery shows dynamic IP/gateway read-only, never copying them into JSON.
An enabled client can be selected without a current lease/session. Current
standard export contains JSON and 11 RSC files, including `sdwan-links.rsc`.

## RouterOS execution

`sdwanResolveWANs` reads actual DHCP leases or the matching dynamic PPPoE `/32`.
On CHR 7.24.5, scripted `pppoe-client monitor once as-value` returned nil, so
assigned address and `network=peer` are used. DHCP requires the actual dynamic
default in its dedicated table, including option121; no unique default closes
the WAN. DHCP next hop is `IP%interface@main`; PPPoE uses the logical interface.

Installer saves original provider routing options. DHCP default is isolated in
the probe table and PPPoE automatic default disabled, preventing provider routes
from bypassing SLA via `main`. Existing lease scripts, PPP credentials/profile
and DNS options remain unchanged. Removed DHCP WANs keep automatic default
disabled until baseline rollback, avoiding renewed SLA bypass.

`sdwanReconcileWANs` responds to ready/address/gateway/interface changes. It closes
affected policy routes/classifiers, removes exact policy marks for that WAN and
its incoming/router sessions, then updates source pins, routes and probes. Other
WANs and inbound API sessions remain. Old probe tuples expire separately.

Before probing, route and mangle bindings must be ready. New Netwatch objects
receive a valid source and three-second start delay. Starting immediately after
rule changes reproduced a wrong first ICMP mark/NAT through main WAN; QEMU capture
confirmed WAN1 egress. The delay corrected marks and path. Controller waits for
fresh generations of all probes, a complete measurement window, recovery windows
and hold-down. Old metrics cannot reopen a WAN; reconciler does not enable policy routes.

Stable parameters cause no configuration rewrite. Status exposes kind, current
address/gateway/route_gateway, carrier, link_ready/link_reason and warming. Runtime
is fully local; GUI/Python are unnecessary after deployment.

Baseline rollback restores saved add-default-route/default-route-tables only
when client identity and managed values match, preserving manual edits. Emergency
watchdog restores the full encrypted binary backup/files and reboots CHR.
[Deployment](DEPLOYMENT.en.md).

## Limits and checks

Duplicate primary WAN IPs close the links; support would require separate VRF
isolation. IPv6, provider-client creation and TCP session migration across public
IPs are not implemented. LTE reconnect/new-IP works; registration and particular
modems need hardware validation. Permanent aliases are included during setup;
temporary leases never become alias pins.

Historical pre-LTE units: 79 PASS; LTE expanded them to 109. Component/mixed
checks use `tests/link_resolver_acceptance.py`, `tests/link_reconcile_acceptance.py`
and `tests/dynamic_wan_acceptance.py`. Private results are in
`runtime/dynamic-final-validation.json` and related reports. Historical static
results do not establish dynamic lifecycle acceptance.

## MikroTik references

- [DHCP Client](https://manual.mikrotik.com/docs/network-management/dhcp/client/): leases, tables, option121.
- [Netwatch](https://manual.mikrotik.com/docs/diagnostics-monitoring-and-troubleshooting/netwatch/): source, start delay, ICMP statistics.
- [Scripting](https://manual.mikrotik.com/docs/developer-guides/scripting/): `json.no-string-conversion`, used throughout native code to preserve yes/no/IP strings and routing-option restoration.
- [PPPoE monitor](https://manual.mikrotik.com/docs/cli-reference/interface/pppoe-client/monitor/): session fields; scripted execution checked separately on the target version.

The original post-LTE milestone passed 109 units, 105 CHR checks, Windows GUI
and final clean-state audit. See [historical LTE report](LTE-VALIDATION.en.md)
and [current candidate status](CURRENT-STATUS.en.md).

Runtime reports, credentials and device snapshots remain private.
[Test reproduction](TESTING.en.md).
