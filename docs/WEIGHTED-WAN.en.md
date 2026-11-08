# Weighted WAN policies

[Русский](WEIGHTED-WAN.md) | English

This optional extension uses the existing WAN, SLA and connection-marking engine.
It passed separate bounded laboratory checks; it is not included in the previous
48-hour acceptance or the earlier native CPU comparison. See the
[validation scope and resource cost](WEIGHTED-WAN-VALIDATION.en.md).

## Configuration

Add `balance` to a `mode="prefer"` policy, or enable **Балансировка** in its GUI
editor. Without this field, ordered preference/failover remains the default.
`strict` still permits one WAN and cannot enable balancing.

```json
{
  "name": "office",
  "source": "192.0.2.0/24",
  "table": "sdwan-office",
  "profile": "default",
  "mode": "prefer",
  "wans": ["wan1", "wan2", "wan3"],
  "allow_degraded": false,
  "balance": {
    "weights": {"wan1": 3, "wan2": 1, "wan3": 0},
    "classifier": "both-addresses-and-ports"
  }
}
```

This is one policy fragment, not a complete device configuration. The WAN names
must already exist in the same configuration. Source/destination IP prefixes or
existing MikroTik Address Lists, including their intersection, remain selectors
of the same policy. Explicit policy priority and the default-policy ordering do
not change. Configured VPN clients can be weighted WANs too; their existing
underlay resolution and SLA requirements still apply.

A weight is the expected **share of new connections**, not bandwidth, packets or
a guarantee for a small sample. A single download uses one WAN. Weights do not
merge providers into one faster TCP connection or migrate a session's NAT address.
A zero weight is an ordered reserve: place these WANs after all positive weights.
A healthy reserve is used when no healthy positive member remains. If degraded
fallback is allowed, a healthy reserve still precedes degraded positive members.

## Affinity

| `classifier` | Fields hashed | Consequence within an unchanged active pool |
|---|---|---|
| `both-addresses-and-ports` (default) | Source/destination IP and ports | Connections from one client may use different WANs |
| `both-addresses` | Source/destination IP | One client/destination pair stays on one WAN |
| `src-address` | Source IP | One client stays on one WAN |

The hash selects among the currently eligible members. A pool change may change
the WAN chosen for **new** connections. Existing healthy marked connections keep
their WAN when a member returns. Applications requiring a stable public IP across
multiple connections should use address affinity or an ordered single-WAN policy.
PCC is not supported with the RouterOS Hotspot proxy/captive portal.

## Health, drain and connection tracking

Only enabled members meeting the policy's current SLA enter the active pool.
Healthy members are preferred as a class. Degraded members enter only when none
is healthy and `allow_degraded` is true. Recovering, down, stale and unresolved
links cannot receive new connections. Existing recovery windows and hold-down
remain in effect.

When a member fails, the controller withdraws its admission and removes that
policy's exact connection marks on the excluded WAN. Healthy members and other
policies retain their sessions. A returning member participates in new
connections without removing existing healthy backup sessions. Drain stops new
connections and retains established eligible sessions until its deadline; an
emergency down or lost SLA retires them. If all permitted paths fail, the policy
fails closed. Conntrack removal does not send TCP RST or transparently move TCP.

`selected` remains the **priority anchor**, used by the existing policy route and
router-originated default traffic. Forwarded balanced traffic uses each
connection's WAN table. RouterOS status additionally reports
`policies.<name>.active_wans` and `balance_mask`. Existing web displays of
`selected` show the anchor, not all pool members. Router-originated connections
are not distributed by PCC.

An explicit WAN **configuration** change, such as changing its kind from static
to DHCP, resets shared SLA warm-up and can interrupt sessions on other WANs. This
is distinct from a lease renewal on an already configured DHCP WAN. Runtime
DHCP loss/new-address recovery is checked separately for selective preservation.
Protected configuration application can also briefly interrupt optional web
polling; steady-state web checks are separate from the update interval.

## Implementation and limits

- Two to four positive-weight WANs per policy; additional zero-weight reserves
  remain priority-only. Every policy WAN must have one integer weight `0..100`.
- Divide weights by their greatest common divisor: `30:10` equals `3:1`.
  At most 32 normalized slots, 256 PCC rules per policy and 1024 total PCC rules.
- Each nonempty subset is compiled in advance (at most 15 groups). SLA changes
  select a group through one owned dynamic `0.0.0.0/0` Address List entry.
  Classifier rules remain fixed. Existing marks bypass new-connection admission.
- `sdwan-a-*`, `sdwan-b-*` lists/chains and `sdwan:v1:admission:*` comments are
  internal; do not add operator addresses or policies to those lists.
- Runtime admission is RAM-only and is recreated after reboot from fresh SLA.
  It adds no persistent configuration write per admission change. Existing route
  changes and event logging retain their usual RouterOS behaviour; this does not
  claim zero flash activity for the whole router.
- Both native mode and the local Rust container use the shared RouterOS actuator.
  Rust supplies the existing priority-anchor intent; RouterOS validates current
  SLA and selects the weighted subset. No external controller is introduced and
  no new container image is needed for this extension.

Use fewer members and slots on small routers. These bounds prevent unbounded
rule generation; they are not hardware performance recommendations. Resource
recommendations need measurements on the target platform.

API route/rule flags and `selected` acknowledge configuration, not the first
packet forwarded on the new path. Actual cutover must be measured using traffic
and captures. Baseline diagnostics observed roughly 0.98 seconds until the first
primary flow; RAM admission probes still showed about 0.12 seconds. Neither is
an atomic-cutover or hardware timing guarantee.

The standard bundle now has 12 RSC files and JSON, including
`sdwan-admission.rsc`. Use the updated GUI/SDK for protected installation and
rollback; do not mix package versions. See [deployment](DEPLOYMENT.en.md).

## Validation and example

[Bounded functional checks and four cost windows](WEIGHTED-WAN-VALIDATION.en.md)
include actual two/three-WAN TCP/UDP, failover, drain, selectors, container fallback,
DHCP, cold reboot, protected upgrade and uninstall. Typical two-WAN PCC cost in
that virtual fixture was 5.68 CPU percentage points at 1000 new TCP connections/s.
The [complete synthetic example](../config/examples/weighted-wan.json) is for the
lab topology; create a device-specific configuration with the wizard.

Official references: [PCC](https://manual.mikrotik.com/docs/high-availability-solutions/load-balancing/per-connection-classifier/)
and [Address Lists](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/firewall/address-lists/).
The current manual describes RouterOS 7.26; the implementation must also pass
actual tests on the project's pinned 7.24.5 guest.
