# QEMU comparison adapter / Адаптер сравнения QEMU

Experimental Linux lab tooling. This is not a completed benchmark or a hardware
recommendation. The original 48-hour acceptance and its restoration must finish
before running the full comparison. Short functional smoke and generator
calibration are separate checks and cannot satisfy that gate.

Экспериментальный адаптер создаёт отдельную VM с новым дочерним qcow2-диском.
Он не подключается к рабочему MikroTik. Полное сравнение ещё не выполнено;
короткие проверки не являются основанием для рекомендаций по производительности.

## Fixture

Use a dedicated Linux host with KVM, QEMU, iproute2, ethtool, tcpdump, a C compiler,
Python 3.12+ and calibrated iperf3 3.19.1. Commands require root on that host.
Do not use a disk from a running VM. Prepare and shut down a separate RouterOS
7.24.5 x86 L6 base with the container package, working API credentials and
Scheduler/Fetch/Container enabled in device-mode. Pin its SHA256. Device-mode
confirmation is a separate preparation step.

The disk uses `format=qcow2,bus=0,unit=0,media=disk` to preserve the tested x86
license arrangement. License level is checked after each boot. The backing chain
is hashed before allocation and after restoration; a changed parent fails cleanup.

Management listeners bind loopback. The first management NIC uses E1000; four
data NICs use VirtIO by default. Owned nonpersistent TAP descriptors belong to
two network namespaces. No host bridge or host route is created. The fixture
supports this explicit synthetic topology:

| Role | Guest address | Peer / client |
| --- | --- | --- |
| wan1..wan3 | 172.20.i.2/24 | 172.20.i.1 |
| lan | 192.168.50.1/24 | affected .101, pinned .102 |
| CPS sources | — | .110 through .237 |
| Echo target | — | 198.18.79.1 |
| SLA targets | — | 10.77.i.2, ports 28081–28083 |

The product supports other WAN kinds; this performance fixture intentionally
uses three static WANs. Prepare a configuration with interface names `wan1`,
`wan2`, `wan3`, LAN `lan`, those addresses and the supplied SLA targets. Preserve
the affected/pinned policies and include management 10.89.0.0/24 in local networks.

## Generator calibration

Calibrate TCP/UDP directly in isolated namespaces at at least twice the planned
offer, with three repetitions per workload and sufficient CPU reserve. Use the
same iperf3 build during measurement. Long CPS calibration runs independently:

```sh
sudo python3 cps_pool_calibration.py --workspace /var/tmp/cps-calibration \
  --run-id cps-001 --rate 1000 --warmup 120 --seconds 60 --repeats 3 --delay-ms 5
```

It exercises 128 source addresses, unique explicit source ports and a destination
port pool. Reservations are persisted before launch and never recycled after an
error. Destination pooling accounts for source NAT collapsing the source IPs.
Both endpoints validate each 32-byte echo; accepted/completed/client counts must
agree. No system TIME_WAIT settings are changed. The adapter checks the source
and compiled binary against the completed, cleaned calibration on the same boot.

## Private configuration

Create a private JSON file outside Git; paths resolve relative to that file:

```json
{
  "source": "/srv/sdwan/source",
  "base_disk": "/srv/sdwan/private/stopped-base.qcow2",
  "base_sha256": "REPLACE_WITH_64_LOWERCASE_HEX_DIGITS",
  "credentials": "/srv/sdwan/private/router-credentials.json",
  "identity": "comparison-base",
  "artifacts": "/srv/sdwan/private/covered-images",
  "variants": "/srv/sdwan/private/prepared-comparison",
  "calibration_tcpudp": "/srv/sdwan/private/tcpudp/report.json",
  "calibration_cps": "/srv/sdwan/private/cps/report.json",
  "port_base": 25800,
  "vcpu": 1,
  "memory_mib": 1024,
  "data_nic": "virtio-net-pci",
  "tools": {"iperf3": "/opt/iperf-3.19.1/bin/iperf3"}
}
```

Credentials use the SDK's `username`/`password` JSON format. Keep credentials,
tokens, disks, configuration exports and captures private. The adapter accepts
no arbitrary router URL: it manages only the QEMU instance it creates. Listener
ports must be free; unrelated guests and ports are left alone.

Prepare with `comparison.py prepare` as described in README. Operational Python/C
sources, native scripts, container archives and mode configurations are bound to
the plan. Regenerate the plan after changing them. Test the adapter separately:

```sh
sudo python3 dut_smoke.py --config /srv/sdwan/private/adapter.json \
  --plan /srv/sdwan/private/prepared-comparison/comparison-plan.json \
  --workspace /var/tmp/dut-smoke --run-id smoke-001
```

This uses two seconds warmup and five seconds measurement by default, plus WAN
switching observers. It explicitly records `capacity_validated=false`.

## Completed-soak gate

On the original soak host, after its process exits and restoration releases both
locks, create a portable proof:

```sh
python3 -m sdwan_lab.acceptance --soak-report /private/network-soak.json \
  --source /private/frozen-source --coverage /private/coverage-result.json \
  --output /private/completed-soak-proof.json
```

The proof binds the exact report bytes, Git commit and complete tracked-file
manifest, native runtime hashes, covered container source and image identity.
It refuses running/failed tests, held locks, incomplete restoration or changed
sources. It creates no bytecode inside the frozen tree. Copy the report and proof
to the lab, then use `comparison.py run --adapter qemu_adapter.py
--adapter-config ... --soak-report ... --soak-attestation ...` with the prepared
plan, workspace and a new run ID. Recovery uses the same private adapter config
and the recorded run; acceptance gates do not prevent cleanup.

The proof is an operational consistency check, not a signature or a replacement
for reviewing independent overlay/OSPF/cleanup evidence before release. A native
runtime change needs matching acceptance; the old report cannot approve it.

## Measurement and restoration

Resource samples are aligned to the post-warmup receiver window. Reports retain
raw iperf events, timing-fit deviation and terminal interval delivery delay.
Generator CPU measures owned endpoint processes and excludes the DUT QEMU.
Container memory is the maximum sampled `memory-current` at 1 Hz; it is not RSS
or the kernel's lifetime peak. Write-sector deltas are logical RouterOS counters,
not NAND erase cycles. Missing/reset counters remain unknown.

Web mode adds one reader polling status, history and events every five seconds.
Its token stays in a private file. Switching blackholes WAN1, verifies failover
and failback, observes the affected flow on both WANs and requires the pinned
TCP connection to survive without UDP loss.

The final baseline is booted from a fresh child of the same stopped base; its
static forwarding projection must match the initial baseline. This removes
container leftovers from the baseline comparison. Owned resources are cleaned;
private diagnostic disks/logs remain. Cleanup failure never becomes a passing
measurement. Recovery uses the durable journal and refuses uncertain ownership.
