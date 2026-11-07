# SD-WAN comparison: 150 measurements

[Русский](PERFORMANCE-COMPARISON.md) | English

Completed 7 November 2026: **150/150 PASS**, five stages of 30 measurements.
Separate failure/recovery checks passed in all three SD-WAN modes; pinned
UDP/TCP flows were preserved. Fifteen TCP/UDP and three CPS calibration cases
passed beforehand. The series took about 7 h 37 min including preparation.

RouterOS 7.24.5 x86 L6, KVM, virtio, three static WANs. Actual execution commit:
`57708b6a5c1aa50e860ee9a16cc018f0ba3fec62`. The publication edition adds
documentation and an offline reporter; executable controller code is unchanged.
Independent checks verified source files, images, all six PCAP counts, absence
of temporary resources, released locks and exited processes. Maximum baseline
receiver-rate drift: **0.000342%**, against a 5% limit.

At TCP 20 Mbit/s, SD-WAN mean CPU was about 21–23%; at 1000 CPS it was 87–92%.
UDP p95 reached 100% even without SD-WAN. These results do not establish reserve
for arbitrary loads or a winning backend on physical ARM/ARM64. Hardware
recommendation profiles remain empty. The logical write counter did not increase
during measurement windows; installation, switching and deferred writes outside
those windows are not covered.

[JSON aggregates](benchmarks/x86-kvm-2026-11-07.json) ·
[CSV table](benchmarks/x86-kvm-2026-11-07.csv) ·
[Earlier short measurements](PERFORMANCE-RESULTS.en.md).
Raw logs, PCAPs, configurations and licensed disks remain private.

Virtual lab. Physical hardware capacity is not established.

DUT: 1 vCPU, 1024 MiB; warmup 120 s, measurement 60 s.

This compares a fixed offered load; it does not determine maximum throughput.

Five-repeat medians; CPU p95 is the maximum of five p95 values. Bidir sums both directions.

Container memory is the maximum sampled cgroup value, not RSS or kernel memory.peak. Write sectors are a RouterOS logical counter, not NAND cycles.

| Workload | Stage | Total offered | Received | CPU mean % | CPU p95 % | Free MiB | Container KiB | Sectors |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| tcp-forward | baseline-before | 20.000 Mbit/s | 20.010 Mbit/s | 3.27 | 7.00 | 799.480 | 0.000 | 0 |
| tcp-forward | routeros | 20.000 Mbit/s | 20.010 Mbit/s | 20.80 | 25.00 | 791.602 | 0.000 | 0 |
| tcp-forward | container | 20.000 Mbit/s | 20.010 Mbit/s | 21.58 | 27.00 | 775.789 | 416.000 | 0 |
| tcp-forward | container-web | 20.000 Mbit/s | 20.010 Mbit/s | 23.00 | 26.00 | 771.254 | 724.000 | 0 |
| tcp-forward | baseline-after | 20.000 Mbit/s | 20.010 Mbit/s | 3.41 | 7.00 | 799.473 | 0.000 | 0 |
| tcp-reverse | baseline-before | 20.000 Mbit/s | 20.010 Mbit/s | 3.38 | 7.00 | 799.500 | 0.000 | 0 |
| tcp-reverse | routeros | 20.000 Mbit/s | 20.010 Mbit/s | 20.57 | 28.00 | 791.391 | 0.000 | 0 |
| tcp-reverse | container | 20.000 Mbit/s | 20.010 Mbit/s | 21.52 | 35.00 | 775.789 | 416.000 | 0 |
| tcp-reverse | container-web | 20.000 Mbit/s | 20.010 Mbit/s | 22.76 | 26.00 | 771.254 | 752.000 | 0 |
| tcp-reverse | baseline-after | 20.000 Mbit/s | 20.010 Mbit/s | 3.58 | 8.00 | 799.477 | 0.000 | 0 |
| tcp-bidir | baseline-before | 40.000 Mbit/s | 40.020 Mbit/s | 6.55 | 11.00 | 799.285 | 0.000 | 0 |
| tcp-bidir | routeros | 40.000 Mbit/s | 40.020 Mbit/s | 24.56 | 30.00 | 791.535 | 0.000 | 0 |
| tcp-bidir | container | 40.000 Mbit/s | 40.020 Mbit/s | 24.47 | 31.00 | 775.637 | 416.000 | 0 |
| tcp-bidir | container-web | 40.000 Mbit/s | 40.020 Mbit/s | 25.88 | 32.00 | 771.164 | 764.000 | 0 |
| tcp-bidir | baseline-after | 40.000 Mbit/s | 40.020 Mbit/s | 6.75 | 12.00 | 799.309 | 0.000 | 0 |
| udp-small | baseline-before | 3000.000 pps | 2999.988 pps | 34.68 | 100.00 | 799.348 | 0.000 | 0 |
| udp-small | routeros | 3000.000 pps | 2999.987 pps | 60.68 | 100.00 | 791.551 | 0.000 | 0 |
| udp-small | container | 3000.000 pps | 2999.986 pps | 61.39 | 100.00 | 775.777 | 416.000 | 0 |
| udp-small | container-web | 3000.000 pps | 2999.990 pps | 64.47 | 100.00 | 771.234 | 772.000 | 0 |
| udp-small | baseline-after | 3000.000 pps | 2999.977 pps | 31.77 | 100.00 | 799.340 | 0.000 | 0 |
| udp-large | baseline-before | 3000.000 pps | 3000.000 pps | 30.10 | 100.00 | 799.348 | 0.000 | 0 |
| udp-large | routeros | 3000.000 pps | 3000.003 pps | 59.10 | 100.00 | 791.559 | 0.000 | 0 |
| udp-large | container | 3000.000 pps | 2999.999 pps | 61.17 | 100.00 | 775.809 | 416.000 | 0 |
| udp-large | container-web | 3000.000 pps | 3000.010 pps | 62.36 | 100.00 | 771.234 | 752.000 | 0 |
| udp-large | baseline-after | 3000.000 pps | 3000.000 pps | 34.37 | 100.00 | 799.340 | 0.000 | 0 |
| cps | baseline-before | 1000.000 cps | 1000.000 cps | 54.53 | 72.00 | 791.723 | 0.000 | 0 |
| cps | routeros | 1000.000 cps | 1000.000 cps | 87.31 | 97.00 | 784.453 | 0.000 | 0 |
| cps | container | 1000.000 cps | 1000.000 cps | 87.28 | 100.00 | 767.168 | 436.000 | 0 |
| cps | container-web | 1000.000 cps | 1000.000 cps | 92.44 | 100.00 | 763.637 | 852.000 | 0 |
| cps | baseline-after | 1000.000 cps | 1000.000 cps | 54.14 | 76.00 | 791.715 | 0.000 | 0 |

## Switching continuity

Maximum over the whole failure/recovery window. The gap between echo replies includes probe interval, RTT and scheduling; it is not exact network outage time.

| Stage | Flow | Protocol | Unanswered | TCP sessions | Disconnects | Max gap ms |
|---|---|---|---:|---:|---:|---:|
| routeros | affected | udp | 290 | 0 | 0 | 5819.912 |
| routeros | affected | tcp | 329 | 3 | 2 | 6779.996 |
| routeros | pinned | udp | 0 | 0 | 0 | 22.298 |
| routeros | pinned | tcp | 0 | 1 | 0 | 22.322 |
| container | affected | udp | 351 | 0 | 0 | 7039.883 |
| container | affected | tcp | 329 | 3 | 2 | 6780.956 |
| container | pinned | udp | 0 | 0 | 0 | 24.428 |
| container | pinned | tcp | 0 | 1 | 0 | 24.425 |
| container-web | affected | udp | 310 | 0 | 0 | 6220.850 |
| container-web | affected | tcp | 330 | 3 | 2 | 6800.340 |
| container-web | pinned | udp | 0 | 0 | 0 | 23.389 |
| container-web | pinned | tcp | 0 | 1 | 0 | 23.556 |

## SHA256

- plan_semantic_sha256: `ab8b686dac94e68793fc87be3d94c0ca28a7c2f804ddba9347130755d3cb4758`
- container_source_sha256: `7af650e6b49c6aaa925c7be72836b01255a60478be52f5ceafde245d322e0ead`
- base_image_config_sha256: `a98ff28196c2ac187d89a285c511f99faa128c3279fe0fd6ef06d219231e677e`
- web_image_config_sha256: `4e3cf126836c0242f37d7b2e1411c2dfe476dbc5924e190368bf586f44d91fcd`
- report_file_sha256: `0a4ad0b5500af536b9d615ac0a8a2a30446928febd89925fe406829e266c83fe`
- plan_file_sha256: `e01276b4f71e7c18d4d6ccc17a869fe21ada780a664a625f4a7d029ba4e6ded9`
