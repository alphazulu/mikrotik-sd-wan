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

## Verified for the current candidate

- Uninterrupted 48 hours at `57708b6`: 24 hours RSC and 24 hours container, no failures.
- Independent configuration/file, OSPF/route and resource restoration.
- Consistent 65 RU/EN pairs; links and public materials checked.

## Acceptance of 0.3.0

1. The 150/150 comparison with fresh calibration is complete; [results](docs/PERFORMANCE-COMPARISON.en.md).
2. Results, limits and the final source/asset audit are recorded.
3. Release v0.3.0 is published; all six public image URLs were downloaded and verified by SHA256.

Short runs and old reports do not replace these gates. Hardware recommendations
must not be filled with unverified extrapolations from virtual measurements.

## Subsequent iterations

- Physical ARM/ARM64, real LTE modems and hardware load testing.
- Reproducible migration of existing OSPF/VPN and third-party marks.
- Clear whole-router resource statistics separate from container process metrics.
- IPv6 and dual-stack SLAs.
- PCC/weighted balancing, QoS and bandwidth management.
- FQDN sets and application classification beyond existing L3/L4 selectors.
- Further branch overlay and multi-node management work.

Changes for the next iteration are prepared separately and validated on their own.
The package under long acceptance is not replaced during that run.
