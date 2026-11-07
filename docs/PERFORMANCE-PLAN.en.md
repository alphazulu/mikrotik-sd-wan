# Comparative SD-WAN load testing

[Русский](PERFORMANCE-PLAN.md)

The completed initial series and its practical limits:
[PERFORMANCE-RESULTS.md](PERFORMANCE-RESULTS.en.md). It does not create an automatic
hardware-performance recommendation profile. Current gates and the later pending
comparison: [CURRENT-STATUS.md](CURRENT-STATUS.en.md).

External nodes generate and receive traffic: LAN client → MikroTik DUT →
WAN/VPN/LTE → server. The generator runs neither on DUT nor in the controller
container. `traffic-generator` on a separate MikroTik is a possible additional
source; RAW TX on the DUT itself does not exercise the ordinary client firewall path.

Compare identical topology and CPU/RAM limits in three modes: baseline routing/NAT,
local RSC, exact CI scratch container with RouterOS fallback. Fix SD-WAN settings,
versions, WAN/policy/probe counts and FastTrack configuration. Do not restructure
topology or generate load underneath a long soak.

Start with iperf3 TCP/UDP, forward/reverse/bidirectional and multiple streams.
A separate TRex ASTF stage is needed for CPS and large session/NAT counts.
Distinguish IP/UDP payload from L2 wire packets: record the measurement layer for
64/512/1500-byte and mixed-size profiles.

Measure throughput/PPS/CPS, active conntrack, loss/retransmissions, loaded latency,
per-core CPU, RAM, container RSS, controller tick freshness, failover/failback and
client-traffic recovery. Generators need headroom. Repeat load steps under the
same conditions; generator, hypervisor or intermediate-node limits are not DUT capacity.

## Limits on conclusions

- x86 L6 belongs to a separate licensed disk. Existing CHRs did not gain a license;
  their tier limits may cap the whole path.
- Measure Python/socket RNDIS transport separately from ordinary WAN. Its ceiling
  is not LTE radio or SD-WAN capacity on physical MikroTik.
- WSL/QEMU results apply to that virtual lab. Physical ARM/ARM64 need their own
  profiles; architecture name alone cannot substitute one platform for another.
- One short functional run cannot establish sufficient RAM/CPU. Unavailable flash
  I/O counters remain unknown.

## Configurator profiles

`config/platform-benchmarks.json` has an empty profile list. Add a profile only after
successful comparative reporting: report SHA256, exact hardware signature, RouterOS,
controller source digest, traffic conditions, config size, per-mode measurements
and passing criteria. Examples/estimates are not successful results. Without a
match, GUI shows unmeasured and retains manual choice. This is independent of
48-hour stability acceptance.

Sources: [MikroTik Speed Test](https://help.mikrotik.com/docs/spaces/ROS/pages/8978571/Speed+Test),
[MikroTik Traffic Generator](https://help.mikrotik.com/docs/spaces/ROS/pages/128221376/Traffic+Generator),
[iperf3](https://software.es.net/iperf/invoking.html),
[TRex ASTF](https://trex-tgn.cisco.com/trex/doc/trex_astf.html).

## Repeatable external generator

`tools/performance_lab.py` targets only the separate x86 L6 lab prepared for LTE
acceptance. It is not a general production-router command. It checks QMP names,
loopback API, L6 license, no active SD-WAN or earlier test objects, and locks both
labs. It never uses the owner's original licensed disk: use a lab working copy
with original IDE geometry `format=qcow2,bus=0,unit=0,media=disk`.

Two diskless Linux generators run in RAM, each 1 vCPU/384 MiB. Official Alpine virt
3.22.7 ISO is SHA256-checked; `apk` verifies iperf3 packages using keys trusted by
the original initramfs. The host needs no TAP, AF_PACKET, root or kernel change.
Data uses QEMU TCP socket links; management uses fixed loopback QMP/serial ports
24500/24501 and 24510/24511.

The driver temporarily replaces its DUT and CHR-client processes, adds two Ethernet
WANs and starts Linux on the existing LAN. Other labs' processes are untouched.
`recovery.json` is saved before topology changes. Each backend uses normal protected
deployment and rollback. Before restoring original QEMU arguments, RouterOS shuts
down normally: immediate QMP quit does not prove latest settings reached disk.
Boot validation checks no test objects remain and L6 is retained.

Prepare the ISO under `<lab-root>/runtime/performance-lab/images/` and the source
launch/credentials files for your LTE lab. Start with a short smoke check:

```bash
python3 tools/performance_lab.py --lab-root /path/to/SD-WAN --seconds 5 --repeats 1 --smoke
```

Full initial series:

```bash
python3 tools/performance_lab.py --lab-root /path/to/SD-WAN --seconds 10 --repeats 2
python3 tools/performance_summary.py /path/to/SD-WAN/runtime/performance-lab/runtime/comparison.json --output /path/to/SD-WAN/runtime/performance-lab/runtime/summary.json
```

Expect 112 measurements: four generator-headroom checks before/after, plus 27 each
for baseline-before/RSC/container/baseline-after. Each mode repeats TCP
forward/reverse/bidir/P4 and UDP payload 64/512/1472 bytes at 5/20/50 Mbit/s;
a separate TCP client stays pinned to WAN2. Both backends also test WAN1 blackhole
under TCP load, retaining the original WAN2 TCP tuple and transferring data after
failover/failback. This tests neither LTE radio, VPN encryption nor CPS; those
need separate scenarios.

Raw JSON, logs and generator versions stay in private host `runtime/`.
`comparison_complete` means series completeness, not zero loss at every offered
load: analyze loss, SLA and channel selection separately. Result-transport or
restoration errors are failures. A remaining `recovery.json` blocks rerun;
first diagnose and restore your lab, retaining baseline and evidence.
