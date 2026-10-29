# Lab validation / Проверки стенда — 2026-10-29

This preparation is based on controller commit
`c3e188070c4d526ebcb3c5235ca86808283c05fe`. The original48-hour controller soak is
still running; no complete48-hour acceptance is claimed here. These reports cover
external tools and a separately tested RNDIS candidate, not physical router capacity.

| Check | Actual result | Scope |
| --- | --- | --- |
| Consolidated external-tool units |64 passed|Linux/POSIX, including explicit source-IP binding and real HTTP reader checks|
| SDK unit tests |365 passed|Linux Python3.12; includes both native API service prefix field names and web source NAT bypass|
| Configurator API snapshots |11 passed|Synthetic replies, headless model path|
| Tk configurator|10 passed;0 network calls|Real LinuxTk8.6/Xvfb, mocked transport/dialog acknowledgement|
| Generator smoke|4 passed, cleanup passed|TCP bidir, UDP, CPS/netem and L2 IMIX; functional only|
| SIGKILL recovery|Passed|Registered child stopped, namespaces removed, original unsuccessful report preserved|
| Continuity control|400 UDP and400 TCP replies|External Linux namespace/veth peers|
| Two-second egress drop|100/400 UDP unanswered;2019.91ms maximum reply gap|Actual netem loss100%, not MikroTik failover|
| TCP during that drop|400/400 replies, one connection,3333.99ms maximum gap|Retransmission delayed recovery; session survived|
| Echo-server restart|Two TCP connections, one disconnect; later replies on new session|Actual reconnect distinguished from survival|
| Current RNDIS candidate|25 unit checks passed|Includes privileged TAP fixture and MTU/OUT-completion regression|
| Fresh CHR LTE chain|USB, lte1, APN-controlled dynamic DHCP, ICMP and public HTTPS passed|Two new CHRs, no licensed-x86 or production mutation|
| TLS bulk input/output|40 GET:6225920bytes;40 POST:1310720bytes|Each POST body checked; local synthetic certificate|
| Registration gate|ICMP3/3→0/3→3/3|Drop/recovery through the same emulated LTE interface|
| TAP capture|8563 Ethernet frames;8434 IPv4 TCP;0 oversized/badchecksums/uncheckedfragments|IP/TCP checksums checked offline|
| Capture-inspector negative checks|Corrupted TCP checksum and truncated packet rejected|Synthetic corruption of one captured test packet|
| Comparison preparation|150 slots generated; gate rejects current running-soak report|No actual four-mode DUT comparison yet|

The consolidated package's unit and replay checks are also run against its final
publication layout before publishing. CI records the corresponding commit checks.
Controller runtime source digest remains
`0d023c5f0a8d1cecbe47ddb429359dc9f58f676d3036118a99c286acb26775ca`.
No Rust/JavaScript controller code was changed, so existing exact-source coverage
is retained rather than attributed to these Python tests.

## RNDIS trigger and fix scope

Mixed64/2598-byte receive frames reproduce QEMU8.2.2's
`usb_packet_complete_one` assertion on the original emulator and the OUT-only fix.
Normal64-byte control frames do not. A backtrace passes through
`usb_combined_input_packet_complete` and USB redirection. The captured bulk FIFO
order is intact; this does not prove correctness of the entire USB protocol.

The candidate rejects Ethernet receive frames above1514bytes for its advertised
IP MTU1500, before RNDIS wrapping. Mixed input then delivers450 valid frames
without BABBLE/assertion; a normal series delivers600. This prevents that invalid
input condition, not every QEMU assertion. Jumbo/VLAN data paths are not claimed.
Source-side GSO/checksum offload still needs disabling on the dedicated fixture
NIC: a length guard does not repair an incomplete TCP checksum.

## Retained failed attempts

- An early USB experiment never opened bulk-IN URBs and was inconclusive.
- GDB initially stopped on QEMU's internal SIGUSR1; the corrected run passes that
  signal through and captures the actual assertion.
- A background shell inherited SIGINT-ignore and caused a service-test shutdown
  timeout. Restoring the default signal disposition made the suite pass.
- The first Tk replay failed during test-driver timer cleanup. The driver's Tcl
  cancellation was fixed; the product GUI was unchanged.
- Fresh-CHR bootstrap initially tried to remove the LTE-owned dynamic DHCP object.
  It now removes nondynamic clients only. A later readiness check compared literal
  false while LTE REST returned no; both representations are now accepted.

Raw failed reports remain private; they were not relabelled as passes. Successful
cleanup stops owned processes and deletes owned network objects while retaining
private diagnostic disks. Backing CHR image hashes remain unchanged.

## Границы доказательств

Пройдены функциональные проверки внешних инструментов, GUI и отдельного LTE
кандидата. Сравнение производительности четырёх режимов ещё не выполнялось:
нужны завершённые проверки DUT adapter и исходного soak. Пределы физических
MikroTik, RF/SIM, WindowsGUI и SD-WAN failover новым измерителем не подтверждены.
Измеренные echo gaps включают шаг проб, RTT и планирование, а не только простой
сети. Каталог рекомендаций оборудования остаётся без неподтверждённых профилей.

## Namespace TAP transport follow-up

Five additional unit checks cover explicit child descriptor transfer, peer
identity, rejection/closure of excess descriptors and namespace ownership.
At that checkpoint the consolidated lab unit suite contained41 tests. A dedicated Linux
privileged integration passes3/3 ICMP replies with frames in both directions
and verified cleanup. The first attempt timed out because an abstract UNIX
socket is network-namespace scoped; switching to a private filesystem socket
resolved that specific cause. No DUT capacity or SD-WAN switching claim follows.

## Comparison adapter preparation follow-up

The extended lab suite passes 64 unit tests, including compiled CPS networking,
source/port reservations, receiver/resource windows, restoration and completed-soak
attestation checks. The positive attestation test uses a synthetic temporary Git
repository; it is not evidence that the real 48-hour soak has finished.

| Check | Actual result | Scope |
| --- | --- | --- |
| Long CPS pool calibration | 3 × (120 s warmup + 60 s measurement), 540,000 validated echoes | 128 source addresses, pooled destination ports, 5 ms netem per interface; cleanup passed |
| Measured CPS | 999.983333 / 1000.016667 / 999.983333 | 1000 CPS offered; direct namespace peers, no DUT |
| Long CPS through the actual x86 NAT path | 180,000 validated echoes per case; 1000.0 CPS baseline, 1000.016667 CPS RSC | 120 s warmup + 60 s measurement each; 353 control snapshots, no errors, cleanup and backing hashes passed |
| TCP/UDP generator reserve | 15 cases passed, cleanup passed | Three repetitions; 40 Mbps TCP forward/reverse/bidir and 6000 PPS UDP64/1472; iperf3 3.19.1 |
| Short x86 L6 baseline | Six workloads passed with VirtIO data NICs | 20/20/40 Mbps TCP, 3000 PPS UDP64/1472, short 1000 CPS through NAT; not steady-state capacity |
| Same UDP64 baseline with E1000 | Approximately 1422 PPS at 3000 PPS offered, guest CPU 100%, host TAP drops | Virtual NIC bottleneck; failed generator-path prerequisite, not a physical MikroTik limit |
| Same UDP64 baseline with VirtIO | Approximately 3000 PPS, zero reported loss | Both sides captured 28,665 frames, no bad IPv4/UDP checksums; L6 and parent image unchanged |
| Original RSC startup after those baseline workloads | Failed and automatically rolled back; cleanup verified | Private instrumentation locates `no such item (4)` in the initial conntrack `find`, before deletion |
| Candidate native retry checks | Five checks passed on RouterOS 7.24.5 x86 L6 via Scheduler | Explicit selectors, transient recovery, empty result, permission propagation and five-attempt bound |
| Candidate RSC short cycle | Six baseline and six RSC workloads passed; WAN failover/failback and pinned flow passed | Container stage then hit its confirmation deadline and rolled back; cleanup passed |

The full five-stage short smoke now passes: 30 workload cases, three WAN switching
checks, pinned-flow preservation, 72 HTTP reads with zero errors, rebuilt baseline
and verified cleanup/backing hashes. This is a functional check with short windows;
the 150-measurement long comparison remains unaccepted. An earlier separate short RSC fixture passed failover/failback,
pinned-flow preservation and rollback; it did not include the preceding CPS
churn and does not override the newer failure. Diagnostic payloads have private
stage markers and are not frozen-source acceptance. The frozen original remains
unchanged. The candidate now includes a [bounded native retry](../docs/CONNTRACK-EXPIRY.md)
and needs its own runtime acceptance. Rust/JS sources and covered container image
source remain unchanged.

## Restricted native API service follow-up

Before installing SD-WAN, the new x86 fixture exposed the API service prefix list
as `available-from=10.89.0.0/24`. The old SDK read only `address`, treated the
missing field as unrestricted and did not add the container address. The local
container's complete login sentence matched its provisioned credentials, while
the same credentials worked from the management network. User/group relaxation
and a fragmented host login did not explain or fix the container failure.

The candidate now reads both `available-from` and the legacy `address` and updates
the field returned by the router. Existing management prefixes are retained; only
the container's /32 is added when needed. Readiness checks use the same effective
prefix list. Five new SDK units pass for aliases, repeatability, IPv4/IPv6 prefix
retention, disabled services and unreadable values. Live installation, six
container workloads and WAN failover/failback with the fix pass. The updated
[MikroTik documentation](https://manual.mikrotik.com/changelog/changelog-2026-09-29/)
also identifies `available-from` as the replacement for deprecated `address`.

## Web source address and image transition follow-up

The adapter now waits for the owned container's actual stopped state before
replacing its image, checking its ID and ownership comment throughout. The live
base-to-web transition passes that check and starts the web controller.

The fixture's broad existing masquerade exposed another real integration case:
it translated the allowed LAN client to the router's container-side address.
The web server correctly rejected that source. Preparation now adds a narrow
owned source-NAT bypass for the configured clients, container address, bridge
and HTTP port, before foreign source-NAT rules. Existing NAT rules are retained.
Two SDK regression checks cover scope and ordering; disabled telemetry adds no
such rule.

An actual owned-guest A/B/A check passes: all three endpoints return HTTP200 with
the bypass, all are rejected/reset when only that rule is disabled, and all
return HTTP200 with valid JSON after it is re-enabled. The final full five-stage
short smoke passes, including that reader and the fresh baseline. These checks do not approve the
full 150-case performance comparison or a hardware recommendation.

## Configurator storage regression (Python SDK / offline GUI)

A writable internal disk previously let `container-storage` report ready for a
selected read-only or unmounted external disk. A renamed mount also used its
slot instead of the actual `mount-point`. The SDK now checks the selected mount
and preserves an unknown/blocked result rather than substituting internal space.

Validation: 377 SDK unit tests, including 12 storage scenarios; 11 synthetic API
snapshot cases; 13 real Tk/Xvfb GUI checks with all live network calls rejected.
The GUI checks the offered directory, readiness failure for a read-only disk and
readiness of a writable mounted volume. A failed storage check is also asserted
to precede image metadata lookup, download, transfer and container preparation.
Legacy projections can prove the mount with a `/file` disk entry.

These are SDK and synthetic GUI checks, not a physical USB-disk acceptance. No
RouterOS script, Rust/JavaScript runtime or running container image was changed.
