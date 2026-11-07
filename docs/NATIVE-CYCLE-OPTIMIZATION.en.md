# Native control-cycle optimization

[Русский](NATIVE-CYCLE-OPTIMIZATION.md) | English

Four measurement windows with SD-WAN running reduced mean RouterOS CPU from
**88.76% to 68.62%**. Paired differences were
**16.07 and 24.21 percentage points**, passing the predeclared
minimum of 5 points in each pair. SLAs, priorities and switching stayed enabled.

Fixture: RouterOS 7.24.5 x86 L6, 1 vCPU/1024 MiB, virtio, three WANs and four policies.
Load: 1000 fresh TCP connections/s, 128 source addresses, 120 s warmup and 30 s measured,
with a 20 s profile inside each window. A–B–B–A order, two repeats per variant.
All 150000 attempts per window, including warmup, completed without client/server errors.
Raw counts, timing windows and means were independently recomputed.

| Variant | Repeat | RouterOS CPU % | Profiler total % | Profiler console % | Whole QEMU CPU % |
|---|---:|---:|---:|---:|---:|
| baseline | 1 | 87.07 | 84.86 | 24.89 | 173.45 |
| candidate | 1 | 71.00 | 57.00 | 10.94 | 175.59 |
| candidate | 2 | 66.24 | 63.56 | 9.19 | 173.90 |
| baseline | 2 | 90.45 | 88.14 | 29.08 | 174.13 |

RouterOS CPU, profiler classifiers and whole-QEMU CPU are separate metrics. QEMU
includes I/O threads; 100% means one host logical CPU. Two repeats do not establish
a confidence interval or maximum capacity.

On this fixture, both original and new DHCP recovery initially reported
`selected=wan1` while fresh TCP connections still used WAN2. WAN2 remained visible
in samples at 0.315 and 0.629 s; the sample near 0.944 s used WAN1. Both variants
used WAN1 in steady state. The original capture is retained. Positive DHCP checks
use an explicit 1.2 s settle, revalidate the selected WAN/address and capture actual
traffic. This status-observation limit was not fixed by the optimization; no
instantaneous atomic cutover is claimed.

## Change

A separate idle profile of the original cycle measured 157.87 ms, including
117.78 ms for policy application and route/classifier checks; JSON parsing took
2.15 ms. These timings include instrumentation overhead on an otherwise idle fixture.

The controller now reads managed routes and classifiers once per tick with
`print as-value`, after WAN resolution and reconciliation. Local indexes retain
no IDs across ticks. Missing/duplicate checks, strict `disabled` types, transition
ordering and selective conntrack cleanup are preserved. RouterOS absent keys have
type `nothing`; a separate `seen` set avoids assuming `nil`. No periodic flash writes
were added.

The derived container-mode RSC uses the same native change. Rust/JavaScript/the
bridge and published v0.3.0 images remain unchanged. GitHub CI checked 100% executable
line/function coverage for both Rust profiles and JavaScript; branch coverage is
reported separately. SLA cadence and JSON freshness were not reduced for the result.

## Verification

- 405 SDK tests and 5 native-test-builder tests.
- Eight RAM-only groups exercising actual helpers and nine live x86 rule checks:
  flags, missing entries, duplicates and replacement IDs.
- Failover/failback with TCP/UDP, per-WAN captures and a preserved pinned flow.
- Container/web switching and native fallback after the container stops.
- Real DHCP lease loss, address change, priority restoration and preserved WAN2 traffic.
- All managed routes/classifiers close when every WAN SLA becomes unavailable.
- Fresh CHR 7.24.5: the same eight RAM-only groups and `as-value` field types.

Preparation failures are retained. A successful container switching case was reused
from a run later stopped by a host client's wrong stop parameter; that original run
remains failed. CPU windows were not repeated for reporting. Parent images, sources,
resource cleanup, ports and leases were independently verified.

## Limits

This is a bounded regression of new code. Earlier 48-hour and 150-run acceptance
belongs to the original v0.3.0 package and was not reassigned to this optimization.
Full switching/load tests ran on x86; the CHR smoke checks helper/field compatibility.
ARM/ARM64, large policy sets and hardware throughput were not measured. The production
router was untouched. Hardware configurator recommendations are not populated from
virtual-lab CPU numbers.

[Plot](benchmarks/native-cycle-optimization-2026-11-07.svg) · [JSON](benchmarks/native-cycle-optimization-2026-11-07.json) · [CSV](benchmarks/native-cycle-optimization-2026-11-07.csv)

`as-value` is documented in [MikroTik Scripting](https://manual.mikrotik.com/docs/developer-guides/scripting/).
Types and functions were additionally checked on actual RouterOS 7.24.5.
