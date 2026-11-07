# Network iteration: verification and remaining gates

[Русский](NEXT-NETWORK-PLAN.md) | English

The development branch targets 0.3.0. The published release remains 0.2.0 until
final acceptance, privacy checks and CI finish. Runtime decisions stay on each
MikroTik, using RouterOS scripts or its local Rust scratch container. No external
controller or production router is used for development acceptance.

Implemented and exercised on isolated RouterOS 7.24.5 CHRs:

- Strict HTTP path/body/status and DNS-answer checks, bounded RAM Fetch workers,
  independent deadlines, generation fencing, TLS validation and fail-closed SLA.
- Per-WAN drain/down, priority admission, scoped conntrack retirement and warm
  RouterOS fallback. Existing marked sessions can finish during healthy drain.
- Existing WireGuard, L2TP, SSTP and OpenVPN exits as ordinary WANs, alongside
  static, DHCP, PPPoE and native LTE/APN discovery. No separate VPN policy engine.
- Source/destination IPv4/CIDR or MikroTik Address Lists, AND across selectors,
  ordered common policies and stable per-policy jump chains. Dynamic list entries
  remain owned by the operator and RouterOS.
- Optional dual-CGNAT branch overlay through a reachable public hub, independent
  encrypted WAN paths, inner SLA and isolated OSPF with explicit prefix export.
  Existing OSPF is protected; private routes fail closed when all paths fail.
- Public-key preparation/exchange and GUI topology editing; bounded optional
  RAM-only web telemetry, off by default, with separate mounted authentication.
- Shared plain-DNS and DoH bootstrap for hostname endpoints while generic
  Internet SLA is closed. Early multicast/broadcast bypass preserves local OSPF
  and DHCP; terminal client guards prevent leaks through control-plane routes.
- Bounded RAM tracking of outer WireGuard geometry. Cleanup matches the exact
  previous remote tuple and an owned listener/local-address snapshot, preserving
  unrelated outer UDP and established inner TCP.

Earlier scoped milestone checks (historical counts, not the latest aggregate;
see [current status](CURRENT-STATUS.en.md)):

| Area | Verification |
| --- | --- |
| Python | 348 unit tests on Linux and Windows; Windows skips 14 POSIX-only cases |
| Container | 41 base Rust, 75 web Rust, 6 browser JS tests; 100% executable lines and functions per runtime file |
| Scratch artifacts | Six static single-binary profiles: amd64, arm64, ARMv5, base/web |
| Strict probes | 13 functional and 21 native/Python contract cases |
| Drain | 6 multi-WAN TCP and 3 final-WAN closure cases |
| Unified WAN/policy selectors | 6 real routing/TCP cases, 88 IP/list contracts, 18 VPN contracts |
| Overlay schema/ownership | 123 schema and 24 ownership/VRF/list cases |
| Overlay lifecycle | 6 install/reapply/off/on/rollback cases and 3 original-JSON guards |
| Outer UDP roaming | 4 checks including direct standby removal count; latest NAT-port retirement 1.074 s, independent UDP/TCP retained |
| Dynamic VPN parents | 2 DHCP and 2 PPPoE live lease/reconnect cases on the final native runtime |
| Cold external DNS | 5 plain-DNS and 6 actual HTTPS DoH checks |
| MTU/MSS | 2 real DF-boundary and bidirectional forwarding-SYN checks |
| Windows GUI | Four offline suites pass; earlier unified GUI inventory checks also passed read-only |

These are scoped results, not a claim that the complete release gate has passed.

The derived RouterOS container adapter additionally checks cached intent against
the current native priority choice. The previous eligibility-only guard could
retain a healthy backup after a preferred WAN recovered, or accept stale `none`.
The real RouterOS component regression reproduces seven old counterexamples and
passes all 20 corrected cases on each owned CHR/x86 node. A matching forced smoke subsequently passed; the frozen 48-hour gate remains
in progress. See [current status](CURRENT-STATUS.en.md) for actual execution commits.
The plain-DNS cold TCP handshake took 20.388 s within a 60 s cold-start test bound;
the DoH run took 0.832 s. The first delay's cause has not been established.
Default SLA limits were not relaxed to obtain these results. The functional QEMU
fixture declares a 250 ms inner jitter budget; the product default stays 50 ms.

Exact 0.3.0 CHR parity (6 checks), two-VPN priority matrix (7), all four VPN
protocols (8 each), the same-configuration resource sample and the final
native dynamic/cleanup/lifecycle gates now pass. The standby retirement helper
removed one actual incoming UDP conntrack when called in the controller's
scheduler environment; the earlier direct-API fixture had a different RAM scope.
The first PPPoE final attempt captured an empty transient UDP inventory; the
subsequent run passed, and the fixture now uses a bounded wait for the actual
new-source bidirectional tuple with no old-source tuple. Failed attempts remain
in private evidence. Missing process I/O counters remain unknown; byte-stable
intent is not a hardware flash counter.

Current release gates:

1. Green CI and exact CI-image CHR checks passed for frozen candidate37a68a9.
   Edited source still needs its own exact coverage/catalog checks before publication;
   ELF paths can make local and CI bytes differ.
2. One source/image-bound 48-hour run is in progress with [the locked driver](NETWORK-SOAK.en.md).
   Native/container phases, three real TCP streams and bounded resources remain
   required. No second soak or edits underneath it; smoke is not long acceptance.
3. The prepared150-measurement comparison waits for matching long PASS and an
   available owned lab. Hardware recommendation profiles stay empty.
4. Complete bilingual documentation, recheck staged source/history/image layers
   against private fingerprints, run CI and publish only after the release gates.
   Earlier audit of473Git blobs/18image blobs and 21gitleaks commits was a historical
   checkpoint, not an audit of subsequent edits. Synchronize reviewed root source last.

Physical ARM/LTE performance and production addressing remain separate from CHR
emulation. Tests never publish private exports, authentication or private keys.

The OpenVPN remote fixture allowed two simultaneous PPP sessions with the same
assigned IPv4 and two active return routes. Under its unchanged 60-second
keepalive setting, ordinary default WAN admission moved to the physical backup
in 0.957 s; preferred VPN resource SLA recovered in 91.156 s. A separate
180-second VPN reconnection test bound covers that remote-session convergence;
SLA thresholds and server settings were not changed. The preceding 65-second
attempt remains recorded as a failed test, not a successful fast VPN recovery.

A protected upgrade failure was also tested with the previous compatible
framework genuinely lacking `sdwan-dns.rsc`. Encrypted rollback restored all
previous sources/configuration and public identities, removed the newly added
library and recovered OSPF after reboot (2 checks).

The observer matches full original/reply TCP tuples, policy and monotonic bytes,
and requires one live HTTP request per stream. RouterOS API handle changes are
recorded without inventing a reconnect. Standby SLA degradation is counted
separately; selected-route SLA, private paths and real traffic remain strict.
