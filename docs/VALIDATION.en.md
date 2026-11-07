> Original lab validation before SD-WAN installation. Later local-controller checks:
> [NATIVE-VALIDATION.md](NATIVE-VALIDATION.en.md).

# Environment validation — 23 October 2026

[Русский](VALIDATION.md)

Environment: Windows 11 Pro, WSL2 Ubuntu-24.04, QEMU 8.2.2, KVM acceleration.
All five nodes booted RouterOS **7.24.5 (stable)** from the owner's specified ZIP.
The source image is immutable; writes go to separate overlays. RAM: edge 1024 MiB,
others 512 MiB each, total 3072 MiB. One vCPU per node.

## Results

| Check | Result |
|---|---|
| Versions, three WANs, LAN, active priorities | 14/14 PASS |
| Lab acceptance | 7/7 PASS |
| `.101` → WAN1, `.102` → WAN2 | Confirmed by matching ISP packet counters |
| WAN1 physical link-down | `.101` switched to WAN2; observed recovery 1.855 s |
| WAN1 silent frame loss | `.101` switched through check-gateway in 26.589 s |
| WAN3 +60 ms each direction | RTT rose from 1.3–2.4 ms to 122–124 ms |
| All WANs disabled | Transit stopped; management REST available on all five nodes |
| Restoration | All WANs up; loss/delay/jitter/rate=0, blackhole=false |
| Internet from `.101` and `.102` | DNS/HTTPS to mikrotik.com, HTTP 200, certificate checked |
| Windows access | WebFig localhost:18080, HTTP 200 |
| Complete down → up from PowerShell | Config/passwords retained; repeat base verification 14/14 PASS |

Timings describe a single lab run, not guaranteed SLA. Recovery includes route
waiting and test pings, not preservation of established sessions; new flows were
checked. At this original stage, automatic response to SLA degradation, Internet
failure beyond a responding gateway, flapping and overlay were not implemented.
Later stages/current gates: [CURRENT-STATUS.md](CURRENT-STATUS.en.md).

Machine reports: `runtime/verification.json`, `runtime/acceptance.json`,
`runtime/internet.json`. Original edge config: `runtime/edge-export.json`.
Repeatable checks: `lab.py verify`, `tests/acceptance.py`, `tests/internet.py`.

## Host-specific observations

- NTFS under WSL did not support QEMU Unix sockets. Monitor/serial use TCP bound
  only to 127.0.0.1.
- KVM access uses the normal `kvm` group; a temporary ACL was removed after opening
  the device. Other virtualization settings, physical network and Windows
  routes/firewall were unchanged.
- External ICMP through user networking depends on Linux ping sockets. Deterministic
  ICMP probes target virtual ISPs; actual Internet was checked with DNS/HTTPS.
- CHR's built-in trust store rejected the `example.com` chain; `mikrotik.com` passed
  with `check-certificate=yes`. HTTPS probe targets need a verified trusted chain.
- All virtual providers share one computer's Internet. Actual provider independence
  is not emulated.
- Free CHR limits interface egress to 1 Mbit/s. Performance tests need another license.

## SHA256

ZIP: `16f07222a3213352c9c4fbea4f4dec6a8ffb78fdc0fa5e398c23103ed357c6eb`

RAW: `e4caf173aceb497433c5fc285bffee09c1e6761dfe0e658a2b178970249fc2d2`

Downloaded over HTTPS from download.mikrotik.com; ZIP CRC checked. SHA256 was
computed locally to bind source; no independent manufacturer signature was checked.

Local `runtime/` reports, credentials and device snapshots are excluded from the
repository. Repeatable verification: [TESTING.md](TESTING.en.md).
