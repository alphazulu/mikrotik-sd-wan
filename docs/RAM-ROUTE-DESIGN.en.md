# Permanent routes and RAM admission: investigation

[Русский](RAM-ROUTE-DESIGN.md) | English

Changing route availability without `route disable/enable` was demonstrated on
isolated CHR 7.24.5. This experimental design is **not enabled in the 0.4.0
production dataplane**. Its delay and additional constraints need a separate
configurable mode and acceptance; the container RAM inbox does not depend on it.

## Already permanent

Classifiers and per-WAN tables already survive selection changes. A dynamic
Address List admits new connections to the selected WAN or weighted subset.
Marked connections retain their WAN table. Remaining policy/main-route switches
support initial lookup, router-originated traffic and compatible source rules.

The current cycle checks `disabled` before issuing a command; it does not repeat
the same enable/disable every second. Replacing it with distance/gateway changes,
route recreation or routing-rule switches still changes persistent configuration.

## Demonstrated design

1. Each permanent recursive default points to a dedicated control IPv4 address.
   A permanent host route resolves that address through a specific carrier.
2. `check-gateway=ping` probes it. A static RAW/output rule blocks control ICMP
   unless a dynamic Address List admits that WAN. Admission changes affect RAM only.
3. RouterOS marks a gated next hop unreachable and selects another route by distance.
   Static route properties and the `disabled` flag remain unchanged.
4. Gating both WANs removes the active main default. An actual OSPF neighbor loses
   the default with `originate-default=if-installed` and relearns it on recovery.
   Separate source-bound SLA probes remain usable.

A single-route experiment passed five checks. The two-WAN experiment with a real
OSPF neighbor passed seven. Owned static-route, routing-rule and RAW configuration
fields were unchanged throughout. Responders were inside the isolated lab;
public-carrier behavior was not tested.

| Transition | Observation in this experiment |
|---|---:|
| Gate primary → backup selected | 13.54 s |
| Gate both → neighbor default withdrawn | 30.69 s |
| Restore primary → neighbor default restored | 9.46 s |

These are state-observation waits including gateway checking, observer polling
and OSPF. They are neither application outage measurements nor latency guarantees.
Normal RouterOS check intervals were used.

## Why this is not the default

- Gateway checking adds delay after an SLA decision. Normal ICMP checking runs
  every ten seconds and closes a gateway after two timeouts. `/routing/settings`
  applies device-wide; changing it silently could affect unrelated routes.
- Control targets must be independent of recovery measurements. Blocking the same
  ICMP used to recognize WAN recovery creates feedback that can prevent failback.
  An extra target can also fail independently.
- The demonstrated design requires different control IPs per WAN. RouterOS 7.24.5
  rejected `gateway=IP@ordinary-FIB-table`; it is not a proven way to share a target.
  VRF-based resolution is a different, untested topology here.
- DHCP/PPPoE/LTE address/gateway changes, VPN underlay, per-policy SLA, drain/PCC,
  WAN/DNAT replies and reboot with empty RAM admission need further acceptance.
  Host routes to probe targets also affect traffic addressed to those IPs.
- Full SLA logic must control admission. Gateway checking is an actuator; one
  ping cannot replace RTT/loss/jitter thresholds, quorum or recovery hold-down.

Consequently 0.4.0 retains direct static-route control on actual WAN changes.
This investigation provides a basis for an optional mode with fewer persistent
updates and an explicit convergence-time contract.

[MikroTik recursive failover](https://manual.mikrotik.com/docs/high-availability-solutions/load-balancing/failover-wan-backup/),
[gateway checking and intervals](https://manual.mikrotik.com/docs/user-guides/routing-and-networking-protocols/routing-decision/),
[OSPF default origination](https://manual.mikrotik.com/docs/user-guides/routing-and-networking-protocols/unicast/ospf/areas-and-virtual-links/).
The manual describes current RouterOS; these experiments separately used 7.24.5.
Raw addresses, logs and lab access are not published.
