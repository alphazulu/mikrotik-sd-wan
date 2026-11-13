# hAP ax2 load and writes: 0.4.0

[Русский](HAP-AX2-04-PERFORMANCE.md) | English

On 13 November 2026, an initial comparison of baseline, RouterOS RSC and the
local ARM64 base 0.4.0 container finished on a dedicated hAP ax2 running RouterOS
7.25.1. Of **27 windows, 19 qualify for steady-path comparison**; eight UDP
windows remain negative load results. The entire matrix is not reported as PASS.
The original configuration and files were restored and the temporary fixture
removed. [Functional acceptance and exact source/image pins](HAP-AX2-04-VALIDATION.en.md).

## Method

One physical uplink carried two virtual WANs and a LAN through a local computer
on the same switch. Linux namespaces, WireGuard MTU 1200 and VXLAN inner MTU
1140 were used; WSL MTU was 1280. Traffic generators and receivers were outside
MikroTik. Reported CPU includes processing these tunnels.

Each mode had 60 seconds of settling, 120 seconds without client traffic and a
45-second delayed-write observation, TCP in both directions with two 20-second
repeats and four streams, followed by UDP with a 1000-byte payload, again two
repeats per direction. Offered UDP load was 85% of the lower of the two baseline
TCP results **in the corresponding direction**: approximately 187.16 Mbit/s up
and 180.30 Mbit/s down.

The observer used one persistent API session, without reconnection inside
measurement windows. Resources were sampled every two seconds and SD-WAN status
every six seconds. Traffic CPU covers only the generator interval. Receiver
results were checked separately from WAN-selection stability.

## Without client traffic

| Mode | Mean router CPU | Written-sector increase over 120 + 45 seconds | Peak container memory-current |
|---|---:|---:|---:|
| Baseline | 0.02% | 0 | — |
| Native RSC | 14.17% | 0 | — |
| Local Rust base | 15.93% | 0 | 544,768 bytes, about 0.52 MiB |

CPU is the total MikroTik load with active SLA monitoring and the observer.
memory-current is the container cgroup reading in this window, not total
RouterOS memory or the complete SD-WAN cost including native scripts and
Netwatch. The web profile was not measured here. Zero sector increase applies
to these bounded windows.

## TCP: mean of two repeats

Up means client → receiver beyond the WAN; down is the reverse direction.
All 12 TCP windows had stable WAN selection and usable measurements.

| Mode | Receiver up, Mbit/s | Receiver down, Mbit/s | CPU up | CPU down |
|---|---:|---:|---:|---:|
| Baseline | 221.15 | 213.24 | 69.50% | 71.55% |
| Native RSC | 176.65 | 179.48 | 81.60% | 79.50% |
| Local Rust base | 170.77 | 173.43 | 84.15% | 80.30% |

At least one core reached 100% in each mode. No written-sector increase was
observed in these TCP windows. Differences apply to the entire measured setup,
including tunnels, rules, SLA and the container. These numbers are not the hAP
ax2's maximum ordinary Ethernet routing capacity or an acceleration comparison
against 0.3. Two short repeats do not establish general hardware recommendations.

## Negative UDP windows

The four baseline UDP windows qualify for measurement. All eight native/container
UDP windows are excluded from steady-path comparison: WAN selection changed
under load, including closure of both paths by SLA. The first native upload
windows lost approximately 52.72% and 69.92%; later download receivers terminated
on timeout. Successful generator completion alone does not establish path health.

The original method had no separate healthy-SLA barrier before each UDP window.
Later windows could therefore start during recovery from a previous failure.
They describe a load-stress sequence rather than eight independent steady-path
comparisons. A smaller common offered load and an explicit health barrier before
each window are needed for clarification; this series is not retrospectively
replaced with successful attempts.

Writes were observed during these transitions: native 14/15/4/12 sectors,
container 21/13/8/12. They cannot be attributed to idle RAM-inbox polling because
the windows included state and route changes. Sector counters do not measure
flash erase cycles or establish storage lifetime. [Remaining writes](RAM-CONTROL.en.md).

## Pins and independent assessment

SDK: `048604048a2427b415680820b7a35d13c3b3beb8`.
Container and per-file base/web/main/JS coverage digest:
`40bdb3f9e3e1bf0747fe835f35556cba3c05fbc9eff56a7877ee1ae1d86ff37e`.
SHA256 of the original 27-window report:
`4d31ff5747fd2bdac46b095fb8662c7cbec024df93c229b4a672c988e949787f`.

Independent assessment replayed receiver byte counts, the 19/8 classification
from saved status, idle counters including delayed writes, source digests and
cleanup. CPU in the table comes from the pinned measurement driver; the
assessment does not claim a separate replay of its CPU interval boundaries.
Raw snapshots, management addresses, backups and secrets remain private.
