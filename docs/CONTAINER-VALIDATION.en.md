# Container backend: initial acceptance completed

[Русский](CONTAINER-VALIDATION.md) | English

**Historical initial-milestone report, 24 October 2026.** Counts, sizes and final
lab state below describe that milestone, not the current candidate.
See [current acceptance and pending checks](CURRENT-STATUS.en.md).

**PASS**, UTC 2026-10-24T05:57:41.972020+00:00, report
`runtime/container-final-validation.json`. Production MikroTik was not connected
or changed for this validation. The controller ran on MikroTik with one RouterOS
actuator and warm native fallback.

| Suite | Result |
|---|---:|
| Python unit | 155 PASS |
| Rust unit | 9 PASS |
| RouterOS protocol: types, boot/config fences, nonce/sequence/release/replay | 19 PASS |
| Real TCP/NAT, WAN/SLA, scoped conntrack, stop/HB loss/restart/SIGKILL | 11 PASS |
| RTT/quorum, API loss, two local containers, config/reboot | 8 PASS |
| Preparation, ownership, LAN/routed aggregates, permissions/mounts | 8 PASS |
| Errors and actual encrypted backup rollback/reboot | 3 PASS |
| Missing metadata, early ACK, recovery-framework upgrade | 1 PASS |
| Native regression: eight sequential suites | 70 PASS |
| Windows GUI: backend and ordinary static/LTE/Create6 | 4 suites PASS |
| Static scratch archives and Docker contexts | 3 architectures PASS |

Total: **50 container-backend CHR checks plus 70 native regression checks**.
Resource measurement and artifact checks also passed. The previous 147 unit /
121 CHR native matrix is retained in [policy validation](POLICIES-VALIDATION.en.md);
these numbers do not replace it.

## Historical image sizes

| Architecture | ELF bytes | Docker-save tar bytes | gzip bytes |
|---|---:|---:|---:|
| amd64 | 534208 | 552960 | 269309 |
| arm64 | 484984 | 501760 | 264823 |
| arm/v5 | 485148 | 501760 | 262688 |

Scratch contained only `/sdwan-controller`, without shell/distribution/SDK/shared
libraries, settings or password. Binary/tar/gzip/image-config SHA256 values were
in that build's `dist/container/build-report.json`. amd64 tar/gzip import and
UID 65532 execution passed on RouterOS 7.24.5 CHR. ARMv5/ARM64 builds/ELFs were
inspected, not executed on physical ARM.

## Resource observation

A 65.37-second observation used three WANs, two SLA profiles, four policies and
ordinary Netwatch probes. Process RSS was **192512–311296 bytes**; container
memory-current was **454656–507904 bytes**; process CPU counter increased four
ticks. Data: `runtime/container-resources-validation.json`.

This was a short running-CHR observation, not a startup-peak or maximum-load
guarantee. RSS/cgroup accounting differs and is not total RouterOS overhead.
No language comparison based on invented memory numbers was performed.

## Recovery and discovered issues

Stable selection avoids rewriting intent. Without heartbeat the process waits
for RAM lease rather than writing each poll. Lease expiry returns selection to
native logic. Invalid intent does not replace a good cached plan; requested WANs
are rechecked against current SLA.

Healthy native fallback and an early fresh ACK cannot confirm container deployment
without lease/metadata. Actual timeout, encrypted restore and reboot were checked.
Framework-upgrade testing found incomplete archival of three deployment RSC files.
The SDK fix saves old flash/root files before overwriting and seals the previous
manifest before payload/arm. Regression changes all three versions and checks
restoration. Current recovery worker/watchdog executes recovery while backup/
archives return configuration and prior package files.

RouterOS ignored this SIGSTOP method for PID1, so no successful SIGSTOP test is
claimed. Actual heartbeat break with a live process and hard SIGKILL were checked.
Reboot checks policy convergence and boot fence, not the first intermediate
snapshot after healthy metrics appear.

Initial 200 ms delay in each direction also broke HTTP quorum. Separate SLA testing
used 90 ms/direction, about 180 ms RTT, with quorum available. Two lab details were
corrected for long-lived state: REST place-before uses the actual first rule ID;
normal installation uses the default 120-second SDK deadline (65.77-second
preparation). Remaining negative cases also use 120 seconds so payload upload
does not consume their deadline before arm. Failed initial attempts and measurements
remain in private runtime evidence.

A voice-jitter incident with ten VMs was not called an algorithm regression.
The historical native timing matrix ran on its original five VMs before the
additional container lab was brought back up.

## Historical final state and limits

Both five-node labs were running at milestone completion: canonical native on
the original, one active unprivileged container/actuator on the separate lab,
start-on-boot enabled, debug metrics/logging disabled. No test jobs/rules/forward/
groups remained; proxy impairments were removed, original APN/provider fixtures
were empty, package hashes matched. Audits:
`runtime/container-final-clean-state.json` and
`runtime/container-native-final-clean-state.json`.

Physical ARM/LTE, long hardware/load/soak, IPv6/DPI and migration of existing
third-party OSPF/VPN marks were not claimed. Guards remained. RouterOS API
permissions are broad, not file-scoped; the dedicated user was restricted to
veth IP with other permissions explicitly disabled. [Setup](CONTAINER.en.md).

Private runtime reports, credentials and device snapshots are not distributed.
[Reproduction](TESTING.en.md).
