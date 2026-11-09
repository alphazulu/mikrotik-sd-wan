# Mixed WAN, LTE, VPN and OSPF validation

[Русский](MIXED-WAN-VALIDATION.md) | English

**Bounded functional validation passed.** Orderly restarts passed; abrupt
power loss remains a separate limitation below.

The lab uses RouterOS 7.24.5, a disposable x86 L6 with 1 vCPU/1024 MiB and a CHR
peer. The production router and export are excluded. Controllers run in RouterOS
or the local Rust scratch container; the host only injects faults and observes.

## Topology and verified scenarios

WAN1 is static Ethernet. WAN2 is actual USB RNDIS exposed as `lte1`; its dynamic
DHCP client is configured through APN, with a 60-second lab lease. VPN1 is an
existing WireGuard exit over WAN1/LTE. A source IP plus destination Address List
policy prefers VPN, then physical WANs. Default and LTE-pinned policies are separate.

The branch has two WireGuard/OSPF paths with costs 10/20. Branch checks require
unmarked traffic without NAT, a Full adjacency, an active OSPF route and real
TCP/UDP exchange. A neighbor alone is insufficient.

| Scenario | Verified RSC and local-container behavior |
| --- | --- |
| VPN remains connected but its destinations fail | The policy falls back; six unrelated flows survive |
| Primary WAN loses data forwarding | Default traffic and VPN transport use LTE; the branch uses its secondary OSPF path |
| VPN HTTP expectation changes during the outage | Affected SLA/flows are reevaluated; healthy LTE/branch flows survive |
| Equivalent source IP spelling | Unaffected health and eight flows survive |
| Branch prefix also appears in the VPN destination list | Local-network exclusion preserves private routing without NAT |
| Both physical underlays fail | Internet admission closes while fresh management remains available; LTE can recover first |
| Only Internet SLA fails, with physical paths working | Six fresh TCP/UDP connections are blocked with no Internet packet leakage; OSPF, branch traffic and management continue |
| Local container stops and restarts | Native fallback and return to the container preserve eight flows |

The adapter keeps `backend=container` during fallback. Container ownership is
indicated by `container.active=true`; native fallback has `false` and an expired
ownership lease.

## Restarts and emulator correction

Sixteen checks passed: four orderly guest restarts, two in RSC and two in local
container mode. Each mode covered primary-WAN loss and simultaneous primary-WAN
and VPN-destination loss. Every restart required fresh LTE evidence, actual
traffic over eight TCP/UDP paths and the retained L6 license.

Each mode then collected 125 observations over 125 seconds with a 60-second DHCP
lease. Every observation retained the bound lease and expected WAN selection;
eight held flows continued without TCP disconnects. Independent replay verified
48 flow-to-packet correlations and 3616 conntrack-row observations. Connection
survival across the reboot itself is not claimed: fresh flows start afterward.
Source, three parent disks and resource cleanup were independently verified.

The original emulator silently discarded cancelled USB requests. The
[usbredir protocol](https://github.com/SPICEorg/usbredir/blob/master/usb-redirection-protocol.txt)
requires a completion carrying the original ID. QEMU retains cancelled IDs until
that response arrives; reusing an ID could lose incoming traffic.

USB and RouterOS diagnostics showed incoming reads stopping after reboot: queued
frames accumulated and the DHCP server replied, while the RouterOS sniffer saw
only outgoing requests. The patch completes a pending cancelled read with
`cancelled` status while preserving unrelated requests. An already completed
operation is not completed twice.

The emulator suite contains 32 tests covering 64-bit IDs, reuse, independent
requests and the AT endpoint. One TAP test intentionally skips without a
prepared interface. The old handler fails three new regressions. A separate
RNDIS zero-tail correction is excluded from this result.

## Source and evidence

Functional scenarios use tree `317bfeb5c40ceac385219ccab0a1667e11494c36`.
Cancellation recovery is tested on tree `664d737969dcf661ea792aa8de3a88532ea65b3d`
([commit](https://github.com/alphazulu/mikrotik-sd-wan/commit/fc004a09ee3adb7a604bbd1f91236d11d512ba58)).
Only the USB emulator, its tests and documentation differ. RSC, SDK, Rust and
JavaScript are identical; the six container images are unchanged.

Evidence includes actual TCP/UDP replies, full original/reply conntrack tuples,
marks and advancing counters, with a 0.5-second healthy-flow observer. Internal
conntrack IDs can be reused: retirement requires obsolete policy/WAN marks to be
absent, while new routing is correlated with NAT and zero-drop packet captures.
One failed API snapshot was excluded from its scenario's acceptance; a scoped
repeat passed without observer errors. This is bounded observation, not proof
that no transition can occur between samples.

Parent disks, source and resource cleanup receive independent verification.
Raw traces, disks and credentials stay private. CI requires 100% unit-test line
and function coverage for both Rust profiles, including `main.rs`, and browser code.

## Limits

**Abrupt power loss is not qualified.** A separate hard QMP reset left
`sdwan-active.json` empty. This change does not implement recovery from that
case; orderly RouterOS restart is a different check.

Physical LTE radio/SIM operation, ARM capacity and connectivity between two
CGNAT endpoints without a reachable hub/relay are untested. Previous 48-hour
and 150-run measurements are neither repeated nor reassigned to this change.

[Live configuration](LIVE-CONFIGURATION.en.md) · [VPN WANs](VPN-EGRESS.en.md) ·
[LTE/APN](LTE.en.md) · [OSPF](OSPF.en.md) · [Emulator](../lte-rndis-emu/USAGE.en.md)
