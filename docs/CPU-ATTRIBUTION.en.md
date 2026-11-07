# SD-WAN CPU attribution

[Русский](CPU-ATTRIBUTION.md) | English

Diagnostic switches apply only to a disposable lab VM. A paused controller does not provide failover.

RouterOS 7.24.5 x86 L6, 1 vCPU/1024 MiB, virtio, 1000 new TCP connections/s. Two repeats: 120 s warmup + 30 s measurement, with a 20 s profile inside it. Second order is reversed.

RouterOS CPU, profiler classifiers and whole-QEMU CPU are separate measurements. QEMU includes I/O threads; 100% is one host logical CPU.

Means of two repeats; ranges are observed min/max, not confidence intervals. Differences are conditional, not independent shares of total CPU.

| State | RouterOS CPU % | Profiler total % | Host QEMU % |
|---|---:|---:|---:|
| Baseline with NAT | 52.23 (50.20–54.27) | 40.79 (38.92–42.67) | 173.90 (172.04–175.75) |
| Full RSC | 89.28 (89.00–89.57) | 86.00 (85.83–86.17) | 176.52 (175.84–177.20) |
| Controller paused, probes running | 61.22 (59.60–62.83) | 44.42 (43.64–45.19) | 176.36 (175.38–177.34) |
| Controller and probes paused | 55.22 (53.50–56.93) | 47.85 (40.28–55.42) | 176.59 (176.55–176.63) |
| Mangle/policy routing bypassed | 55.08 (53.20–56.97) | 46.26 (43.42–49.11) | 175.69 (175.44–175.94) |
| NAT and automatic conntrack bypassed | 51.15 (46.03–56.27) | 35.56 (34.36–36.75) | 168.34 (167.57–169.11) |
| Resource polling paused | not sampled | 43.24 (38.67–47.81) | 176.50 (176.27–176.72) |

## Conditional differences

| Component | Metric | Mean points | Range points |
|---|---|---:|---:|
| controller | resource_cpu_percent | 28.07 | 26.17–29.97 |
| probes | resource_cpu_percent | 6.00 | 2.67–9.33 |
| mangle_policy_routing | resource_cpu_percent | 0.13 | -3.47–3.73 |
| NAT_and_auto_conntrack | resource_cpu_percent | 3.93 | -3.07–10.93 |
| resource_observer_profile_metric | profile_cpu_percent | 4.61 | 1.61–7.61 |
| resource_observer_host_QEMU_metric | qemu_host_cpu_percent | 0.10 | -0.09–0.28 |

Resource polling is disabled only in observer-paused: RouterOS CPU there is unknown. Observer comparisons use the profiler and QEMU separately.

Mangle bypass uses a fixed main route through WAN1; NAT bypass adds a Linux peer return route. A supplementary check of the same configuration showed enabled=auto: active-ipv4=true with mangle bypass and false after disabling NAT. Thus the NAT column also changes automatic conntrack activation; it does not isolate NAT alone. These states measure costs, not SLAs/leak protection.

The first successful baseline window is retained from a previous run stopped by a guard when NAT print omitted disabled. An explicit get reads the flag, and all switches were validated before new loads. The old run remains failed; its successful window was not repeated.

This is a virtual lab; it does not establish ARM/ARM64 hardware performance or peak throughput. The v0.3.0 rules/controller/container source files are unchanged.

Classifier definitions are in [MikroTik Profiler](https://manual.mikrotik.com/docs/diagnostics-monitoring-and-troubleshooting/profiler/); auto mode is described in [Connection tracking](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/connection-tracking/). API format and activation were checked on 7.24.5; current documentation targets 7.26.

## SHA256

- report_sha256: `8399dbe8fc0688fd9100b8438efdab9a781488f6a57a25b6354cb6626e53f309`
- reused_baseline_report_sha256: `5d22ebcd42fd55873192640769e0e2c7a4dd5665dc51fe93235e80a018adcbd9`
- tracking_confirmation_report_sha256: `2ac1092d3ad6268970c56f0d22f6ffb562aa1861dcf8cd8fa84f664302886475`

## Conclusion and optimization priority

The strongest confirmed candidate is the periodic `sdwan-controller` cycle:
pausing it reduced RouterOS CPU by **26.17–29.97 points** (mean 28.07).
Pausing Netwatch probes additionally gave **2.67–9.33 points** (mean 6.00).
These are conditional differences between diagnostic states, not savings already
achieved by a working controller. Optimization must retain the required SLAs
and failover behavior.

Mangle/policy-routing differences changed sign: −3.47 and +3.73 points.
Combined NAT/auto-conntrack differences were +10.93 and −3.07 points. Two repeats
do not reliably isolate these smaller effects. Baseline changed by 4.07 points.
Disabling only the external resource sampler gave 1.61–7.61 profiler points, but
almost no whole-QEMU CPU change (−0.09…+0.28 points). This does not estimate all
container API calls; the RSC-cycle conclusion is stronger.

The first optimization prototype should target the common native layer:

1. Time WAN resolution/reconciliation, Netwatch reads, decision application
   and status serialization separately. The console classifier is a broad class,
   not the cost of a particular script line.
2. Evaluate bulk reads of managed objects instead of repeated `find/get` calls
   inside loops, and a RAM cache for unchanged configuration. Preserve detection
   of address changes, missing/duplicate rules and SLA freshness.
3. Compare the prototype on the same fixture, then check switching, symmetric
   replies, selective conntrack and RSC/container parity. Do not slow SLA sampling
   merely to obtain a favorable CPU number.

These changes have not been applied; the current release and accepted executable
files are preserved.

[Plot](benchmarks/cpu-attribution-2026-11-07.svg) ·
[JSON](benchmarks/cpu-attribution-2026-11-07.json) ·
[CSV](benchmarks/cpu-attribution-2026-11-07.csv)
