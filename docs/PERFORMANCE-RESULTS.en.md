# Initial measurements on isolated x86 L6

[Русский](PERFORMANCE-RESULTS.md)

26 October 2026: **112 completed measurements**, 27 each for baseline-before,
RouterOS RSC, local Rust container and baseline-after, plus four direct TCP
measurements between generators. Both backends passed WAN1 blackhole under load
while retaining the original WAN2 client's TCP tuple. After restoring original
QEMU arguments, absence of test objects and L6 retention were verified.
Production was not used.

This is a completed observation series, **not established physical-MikroTik
capacity or a basis for automatic mode selection**. Control TCP runs varied
substantially; direct small-packet UDP exposed generator/virtual-transport limits.
Recommendation profiles remain empty: GUI correctly shows `unmeasured` for
unvalidated platforms. Long soak separately checks stability and cannot remove
these measurement limits. Current gates: [CURRENT-STATUS.md](CURRENT-STATUS.en.md).

## Conditions and reproduction

- RouterOS 7.24.5 x86_64 L6, KVM, 1 vCPU, 1024 MiB RAM, emulated e1000.
- Two diskless Linux generators: Alpine virt 3.22.7, Linux 6.12.114, iperf3 3.19.1,
  each 1 vCPU/384 MiB; loopback QEMU TCP socket links.
- Two static WANs, three policies, one SLA profile, six TCP probes plus ICMP.
  Main client prefers WAN1; separate client pinned to WAN2.
- Each load repeated twice for 10 seconds plus 2 seconds omit. FastTrack disabled.
  NAT/routing and SD-WAN share one topology. Each backend waits for fresh SLA and
  6-second convergence before measurement. This short settle does not establish
  steady-state performance.
- Test source: `77e5e1d796710ab779ed29a9e03ba5cbded4ad38`.
  Base CI image: `a98ff28196c2ac187d89a285c511f99faa128c3279fe0fd6ef06d219231e677e`.
  Container source/coverage digest:
  `0d023c5f0a8d1cecbe47ddb429359dc9f58f676d3036118a99c286acb26775ca`.

Driver commands/limits: [PERFORMANCE-PLAN.md](PERFORMANCE-PLAN.en.md).
Machine-readable observations, both backends and direct UDP:
[x86-kvm-2026-10-26.json](benchmarks/x86-kvm-2026-10-26.json).
Private source logs/configurations are excluded from publication.

## Example observations

Medians of two repeats, Mbit/s of **iperf3 application data**. UDP size is
application payload, not Ethernet frame size or wire rate.

| Load | NAT before | RSC | Rust + RSC fallback | NAT after |
|---|---:|---:|---:|---:|
| TCP forward, unlimited rate | 269.0 | 142.9 | 168.8 | 261.6 |
| TCP reverse, unlimited rate | 215.0 | 245.1 | 129.9 | 422.0 |
| UDP 1472 B, offered 20 Mbit/s | 20.0 | 20.0 | 20.0 | 19.3 |
| UDP 1472 B, offered 50 Mbit/s | 46.6 | 37.1 | 33.1 | 45.8 |
| UDP 64 B, offered 5 Mbit/s | 2.60 | 1.78 | 1.58 | 2.63 |

TCP reverse variability prevents declaring either backend faster. Small-packet
UDP drove DUT CPU to 98–99%; some measurements degraded SLA: 5/27 in RSC, 1/27
in container mode. Matching strict policies temporarily closed their routes as
configured. Those episodes remain in JSON rather than being omitted. No controller
error does not imply no packet loss or SLA degradation.

Direct generator TCP reached approximately 1.3–2.8 Gbit/s but does not prove PPS
headroom. Twelve extra direct UDP measurements without DUT found loss at 64-byte
payload/50 Mbit/s, especially reverse. Such small-packet loads are not validated
DUT capacity. Reassessment needs virtual NIC/queue control and a warmed stable
fixture or physical generators; CPS needs its own scenario.

## Switching under load

| Observation | RSC | Container |
|---|---:|---:|
| WAN2 selection after WAN1 blackhole | 4.61 s | 4.10 s |
| WAN1 selection after recovery/fresh SLA | 7.19 s | 7.17 s |
| Original WAN2-pinned TCP | Retained, increasing counters | Retained, increasing counters |

A successful new TCP transfer followed every switch. Completion time includes
its three-second duration and an extra six-second wait after failback. It is not
downtime or time to first recovered packet; the latter was not measured here.

## Memory and storage writes

Main-series peak `container.memory-current`: 663552 bytes. A separate diagnostic
run of the same CI image at TCP 20 Mbit/s measured process RSS maximum
**307200 bytes**, cgroup **479232 bytes**, with 15 API samples and six resource
messages. These are different accounting methods; the diagnostic used temporary
RAM logging and does not replace main-series statistics. Original settings and
`logging` were restored and checked. These short observations are not memory
budgets for arbitrary WAN/VPN/policy counts or evidence of no long-term growth.

`write-sect-total` had nonzero increments. Installation, settings persistence and
route switching require writes; the counter includes deferred RouterOS saves and
other system activity. It does not measure physical NAND erase cycles. No
per-second statistics disk writes were enabled; diagnostic logging was permitted
only after confirming no active disk logging rules. An external host observer
stored statistics and long-term test reports.
