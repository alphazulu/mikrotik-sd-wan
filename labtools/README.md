# SD-WAN lab tools / Инструменты стенда SD-WAN

External test tools for Linux. SD-WAN decisions stay on MikroTik: RouterOS RSC or
the router's local Rust scratch container. These tools generate traffic, observe
continuity and exercise the configurator; they are not an external controller.

Внешние инструменты Linux-стенда: генерация трафика, измерение перерывов,
обезличенные API-снимки и настоящий Tk GUI. Управление WAN остаётся на MikroTik.

## Quick start / Запуск

Python3.12+, standard library. Run commands from `labtools/`:

```sh
python3 -m sdwan_lab check --config configs/smoke.json
sudo python3 -m sdwan_lab run --config configs/smoke.json \
  --workspace /var/tmp/sdwan-lab --run-id smoke-001
python3 -m sdwan_lab status --workspace /var/tmp/sdwan-lab
```

Selected modes require iproute2/ethtool, iperf3, tcpreplay/tcpdump or a C compiler.
Tool paths are configurable in JSON; relative paths resolve against the JSON file.
The functional four-mode smoke uses TCP, UDP, bounded C/POSIX-poll CPS and IMIX.
The measured lab used iperf3 3.19.1; calibrate other versions before comparisons.

IMIX is direct L2 veth calibration with experimental EtherType0x88b5. Frame sizes
include FCS; pcap lengths exclude four FCS bytes. It is not routed IP IMIX or
physical wire PPS. The original short CPS tool limits each case to20,000
connections. The separate `cps_pool_calibration.py` tool uses a durable source
address/port pool and multiple destination ports for longer tests through NAT.
TIME_WAIT settings are not changed.

CPU p95 uses nearest-rank samples every200ms across the whole case, including
setup/warmup/drain. iperf receiver rates use post-omit measurements. IMIX permits
a two-second receiver drain. These are distinct windows, retained in the reports.

## Isolation and recovery / Изоляция и восстановление

Host-per-UID and workspace locks prevent overlapping tool runs. Namespace names
are random. Veth endpoints are created inside owned namespaces. Process ownership
uses PID/start time/boot ID; namespaces use inode/device/boot ID. Owned TAPs also
check ifindex and a run-specific alias before deletion. Logs/run IDs are never
silently overwritten. JSON journals use fsync plus atomic replace.

SIGINT/SIGTERM perform cleanup. After SIGKILL, recover a registered run explicitly:

```sh
sudo python3 -m sdwan_lab recover --workspace /var/tmp/sdwan-lab --run-id smoke-001
```

Recovery does not turn an unsuccessful measurement into a pass and preserves the
original report. A crash during an unconfirmed resource creation leaves `pending`;
the tool requires inspection rather than guessing ownership. Locks cover this
package, not unrelated host workloads; performance windows need a quiet host.

## Echo continuity / Перерывы связи

```sh
python3 -m sdwan_lab.continuity serve --listen 198.18.251.2 --port 25351
python3 -m sdwan_lab.continuity measure --host 198.18.251.2 --port 25351 \
  --seconds 60 --interval-ms 20 --output /var/tmp/continuity-001.json
```

Use `--source-address` with an existing local IPv4 to select the client policy
under test. Both UDP and TCP bind that address; reports retain their actual tuples.
This permits separate affected and pinned-client streams without changing routes.

The echo peer belongs in an isolated test network; default bind is loopback.
A run nonce and client monotonic timestamps identify replies. Reports distinguish
unanswered messages, duplicates, reordering, RTT, initial/trailing silence and
maximum reply gaps. TCP connection IDs and tuples distinguish survival from
reconnection. The client does not close a stalled TCP connection merely because
an echo is late. TCP offered means application queue submission, not wire sends.
A two-second drain accepts late replies; the drain does not inflate trailing silence.

Разрыв между ответами включает интервал проб, RTT и планирование. Он не равен
точному времени сетевого отказа. Если ответов нет, max gap=null. Общий лимит —
30,000 probes на протокол. Для корреляции с внешними событиями нужны сопоставимые
часы; два namespace одного Linux-хоста используют общий CLOCK_MONOTONIC.

## Configurator replay / Проверки конфигуратора

```sh
python3 snapshot_matrix.py --source .. --output /var/tmp/snapshot-001.json
xvfb-run -a python3 gui_replay.py --source .. --output /var/tmp/gui-001
```

`fixtures/mixed-router.json` is entirely synthetic: documentation addresses,
example.test endpoints and test interfaces. No production export was used.
The replay API only permits known reads and applies `.proplist` projection.
The11 headless cases exercise discovery/generation, LTE/APN permissions, dynamic
WANs, legacy mangle drafts, missing packages/features and all four VPN protocols.

GUI replay uses real Tk widgets, callbacks, modal editors and files; only the API
transport, file chooser and message acknowledgement are replaced. It covers13
checks including source IP AND destination Address List, VPN-first priorities,
export/reopen and a disabled installation button for foreign mangle conflicts.
Storage checks cover renamed mount points, exclusion of read-only/unmounted
disks, blocked preparation and readiness of a verified writable volume.
It proves Linux/Tk behaviour, not Windows rendering or live router installation.
Tk8.6 and Xvfb are required. Python network connections are rejected in this replay.

## LTE/RNDIS regression

```sh
sudo env PYTHONPATH=. python3 lte_acceptance.py \
  --source .. --image /path/to/chr-7.24.5.img \
  --workspace /var/tmp/sdwan-lab --run-id lte-001 --port-base 25500
```

This creates two fresh CHRs, an owned TAP and loopback management endpoints.
Probe must choose usbredir-userspace. Serve becomes ready before QEMU connects.
The ISP CHR serves DHCP; the emulator forwards Ethernet. RouterOS APN controls
the dynamic LTE DHCP client. USB modules, usbip and production routers are unused.
CHR Free bandwidth limits make this a functional test, not a capacity measurement.

The candidate passes public HTTPS,40 local TLS GETs,40 TLS POSTs with server-side
POST-body validation and registration-gate recovery. The local TLS certificate is
synthetic/self-signed with certificate checking disabled for that fixture; this is
not a PKI test. [Actual scope and results](VALIDATION.md) distinguish older failures.

Generated disks, router credentials, TLS keys, captures and raw router dumps stay
in a private workspace. Never add the whole workspace to Git. Processes and owned
TAPs are cleaned; diagnostic disks remain available privately.

## Comparison preparation / Подготовка сравнения режимов

```sh
python3 comparison.py prepare --source .. --config ../config/sdwan.json \
  --artifacts ../dist/container --output /var/tmp/comparison-001 \
  --lan-interface ether5 --lan-source 192.168.50.0/24
```

Prepared sequence: baseline-before → RouterOS → container → container-web →
baseline-after. Three validated mode configs and a plan bind native source hashes,
covered container source, verified base/web archive hashes and config hashes.
The default150 measurements each use120s warmup+60s measurement: at least7.5h,
plus mode settling and switching. TCP forward/reverse/bidir, UDP64/1472 payload
and CPS share one workload definition. Long CPS requires a source address pool.

An owned-QEMU DUT adapter is included. Its short five-stage functional cycle
passes; the full long comparison and hardware capacity validation have not run.
See [DUT setup and limits](DUT-ADAPTER.md).
The reference FakeAdapter in tests must never be presented as benchmark evidence.
The run command is gated on successful completion/restoration of the original
48-hour native/container acceptance and a source-bound cleanup attestation.
Recovery remains available after a failed run.

The adapter implements readonly `preflight`, durable `snapshot`, `set_mode`,
`measure`, `switching` and verified `restore`. See comparison.py for the contract.
It must confirm source bindings, ownership, generator calibration and CPS pooling.
Measurements include explicit rate units, DUT CPU/RAM, container peak memory,
generator CPU, host steal and write-sector delta or unknown. Write-sector counts
are not physical NAND erase cycles. Web mode includes one reader polling every5s.

A >5% before/after baseline drift or exhausted generator/host reserve invalidates
the comparison. Switching requires the continuity observer and preservation of a
flow pinned to the unaffected WAN. No automatic hardware profile is produced;
`capacity_validated` remains false.

## Tests

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
sudo env PYTHONPATH=. python3 tests/recovery_integration.py \
  --workspace /var/tmp/sdwan-lab --run-id recovery-001
sudo env PYTHONPATH=. python3 continuity_integration.py \
  /var/tmp/sdwan-lab continuity-001
sudo env PYTHONPATH=. python3 continuity_integration.py \
  /var/tmp/sdwan-lab reconnect-001 reconnect
```

Privileged integration commands belong on the dedicated Linux lab. CI runs the
pure unit/replay checks; QEMU/TAP acceptance is reported separately with its scope.
Controller code is unchanged by this package, including its mandatory exact-source
unit coverage requirements.

## Namespace TAP descriptors / TAP внутри netns

`sdwan_lab.namespace_tap.open_tap(run, namespace, name)` opens a nonpersistent
TAP in a namespace already owned by the run. It exports one descriptor through
a private filesystem UNIX socket with peer PID/UID verification. Abstract UNIX
sockets cannot cross network namespaces. The returned descriptor is not
inheritable until explicitly passed with `Run.spawn(..., pass_fds=(fd,))`.
Close it after the child stops; the final descriptor closure removes the TAP.
The QEMU process can retain loopback management while its data TAPs remain
inside disposable peer namespaces, without a host bridge or host IP changes.

```sh
sudo env PYTHONPATH=. python3 namespace_tap_integration.py \
  --workspace /var/tmp/sdwan-lab --run-id namespace-tap-001
```

This privileged check relays frames between two namespace TAPs and verifies
three ICMP replies and cleanup. It is a transport fixture check, not a DUT
capacity or SD-WAN failover measurement.
