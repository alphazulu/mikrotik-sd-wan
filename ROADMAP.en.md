# Roadmap

[Русский](ROADMAP.md) | English

See [current candidate status and evidence](docs/CURRENT-STATUS.en.md).
The items below describe capabilities and next steps, not a release readiness claim.

## Implemented

- Local RSC and Rust/scratch controllers, heartbeat, owner fencing and RSC fallback.
- IPv4 SLAs, quorum, priorities, automatic failover and return.
- Static, DHCP-client, PPPoE, LTE/APN and existing VPNs as WANs.
- Shared source/destination IP or Address List policies, interface and L3/L4 selectors.
- `jump` chains, symmetric replies and selective conntrack cleanup.
- Drain, strict DNS/HTTP probes, DNS bootstrap and branch WireGuard/OSPF paths.
- GUI/CLI, conflict preview, protected deployment, rollback and diagnostics.
- Optional RAM statistics and web, two image profiles for three architectures.
- CI, mandatory container coverage and exact CI-image catalog validation.

## Verified for the original v0.3.0 source

- Uninterrupted 48 hours at `57708b6`: 24 hours RSC and 24 hours container, no failures.
- Independent configuration/file, OSPF/route and resource restoration.
- RU/EN documentation pairs, links and public materials checked.

## Acceptance of 0.3.0

1. The 150/150 comparison with fresh calibration is complete; [results](docs/PERFORMANCE-COMPARISON.en.md).
2. Results, limits and the final source/asset audit are recorded.
3. Release v0.3.0 is published; all six public image URLs were downloaded and verified by SHA256.

Short runs and old reports do not replace these gates. Hardware recommendations
must not be filled with unverified extrapolations from virtual measurements.

## CPU attribution after 0.3.0

14 diagnostic windows are complete; [findings and limits](docs/CPU-ATTRIBUTION.en.md).
The common native cycle now uses fresh managed-object snapshots, preserving SLAs.
[Four load windows and bounded switching/DHCP/CHR regression](docs/NATIVE-CYCLE-OPTIMIZATION.en.md) passed.
New RSC code has not repeated the original 48-hour or 150-run acceptance.

## Subsequent iterations

The owner prioritizes core SD-WAN functionality. Statistics/web expansion is deferred;
all privileged work remains deferred too. The container retains `privileged=no`.

Optional weighted WAN policies are implemented and passed separate bounded
qualification: actual two/three-WAN forwarding, affinity, failure/drain/reserve,
selectors, container fallback, DHCP, protected lifecycle and resource windows.
[Configuration](docs/WEIGHTED-WAN.en.md) · [Evidence and limits](docs/WEIGHTED-WAN-VALIDATION.en.md).
API flags remain configuration observations; the guide records DHCP convergence,
explicit WAN-kind edit disruption and transient web polling during reconfiguration.

Scoped live configuration is implemented: unaffected SLA state, probe evidence
and healthy flows survive successful edits; reinstall requires new measurements.
[Configuration](docs/LIVE-CONFIGURATION.en.md) · [Evidence and limits](docs/LIVE-CONFIGURATION-VALIDATION.en.md).
The earlier explicit WAN-kind reset limitation applies to the old source;
transient optional web polling limits remain recorded separately.

Remaining directions:

- Physical ARM/ARM64, real LTE modems and hardware load testing.
- Reproducible migration of existing OSPF/VPN and third-party marks.
- IPv6 and dual-stack SLAs.
- QoS and bandwidth management.
- FQDN sets and application classification beyond existing L3/L4 selectors.
- Further branch overlay and multi-node management work.

Changes for the next iteration are prepared separately and validated on their own.
The package under long acceptance is not replaced during that run.
