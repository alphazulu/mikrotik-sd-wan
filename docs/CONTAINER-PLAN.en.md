# Local container backend plan — completed

[Русский](CONTAINER-PLAN.md) | English

Historical initial-milestone plan. New candidate checks and long acceptance are
tracked separately in [current status](CURRENT-STATUS.en.md).

Rust was selected for a small process without GC/async framework, static musl
and scratch. One process, one persistent native API session; separate read-only
JSON/password mounts, UID 65532, bounded buffers/timeouts.

- [x] ARMv5/ARM64/amd64 cross-build, minimal single-layer Docker-save without daemon.
- [x] Shadow and actual execution inside CHR 7.24.5.
- [x] Typed fenced intent, RAM heartbeat, owner/sequence/boot/config epochs.
- [x] One RouterOS route writer with warm native fallback.
- [x] SDK/GUI backend, separate preparation and protected local deployment.
- [x] Actual TCP/NAT/SLA/failover, stop/API/HB loss, competing owner and reboot.
- [x] Errors, missing lease/metadata, early ACK and full package rollback.
- [x] Permissions/ownership/mount/overlap checks and no idle flash rewrites.
- [x] Resource observation, GUI/native regression, both labs cleaned and running.

See [historical results and limits](CONTAINER-VALIDATION.en.md) and
[installation](CONTAINER.en.md). Physical ARM/LTE and deployment into an existing
production OSPF/VPN topology remain separate milestones, not automatically resumed.

Runtime reports, credentials and device snapshots remain private.
[Reproduction](TESTING.en.md).
