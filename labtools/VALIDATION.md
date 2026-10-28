# Lab validation / Проверки стенда — 2026-10-28

This preparation is based on controller commit
`c3e188070c4d526ebcb3c5235ca86808283c05fe`. The original48-hour controller soak is
still running; no complete48-hour acceptance is claimed here. These reports cover
external tools and a separately tested RNDIS candidate, not physical router capacity.

| Check | Actual result | Scope |
| --- | --- | --- |
| Consolidated external-tool units |36 passed|Linux/POSIX, including explicit source-IP binding|
| SDK unit tests |348 passed|Linux Python3.12|
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
нужен конкретный DUT adapter и завершение исходного soak. Пределы физических
MikroTik, RF/SIM, WindowsGUI и SD-WAN failover новым измерителем не подтверждены.
Измеренные echo gaps включают шаг проб, RTT и планирование, а не только простой
сети. Каталог рекомендаций оборудования остаётся без неподтверждённых профилей.
