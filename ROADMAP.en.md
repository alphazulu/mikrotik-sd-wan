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

## Before completing this release

1. Finish long acceptance of the exact candidate: RSC, then container.
2. Independently verify restoration, configurations, OSPF and resource cleanup.
3. Execute the prepared 150-measurement comparison on an available lab.
4. Normalize documentation into equivalent RU/EN versions and verify links.
5. Audit public source/assets and prepare the release after the required checks.

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
