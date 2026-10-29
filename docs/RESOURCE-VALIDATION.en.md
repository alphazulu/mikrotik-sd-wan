# API, archives and CI validation

[Русский](RESOURCE-VALIDATION.md)

Historical report: counts and fixture state describe this stage. Current acceptance gates: [CURRENT-STATUS.md](CURRENT-STATUS.en.md).

Checks ran on two separate five-node CHR 7.24.5 labs. Production MikroTik was not
connected or changed. This stage changed neither the eight native RSC files nor
the Rust WAN-selection algorithm.

| Check | Result |
|---|---:|
| Python units: query scope, no-op upload, retention, corrupt journals, storage | 183 PASS |
| Windows GUI offline: creation and retention enable/disable | 6 PASS |
| Native API/REST: queries, no duplicate writes, dry-run, pending/schema/dependencies, execute | 7 CHR PASS |
| Native protected deployment, no ACK, actual API disable | 3 CHR PASS |
| Container: missing lease, premature ACK, encrypted restore, worker error | 3 CHR PASS |
| Missing metadata and new versions of three recovery RSC files | 1 CHR PASS |
| Large directory, automatic post-commit retention, original JSON restoration | 3 CHR PASS |
| Base connectivity/routes on each lab | 14+14 PASS |

Total: 17 functional CHR checks and 28 base checks. This targeted SDK/maintenance
suite does not relabel the earlier full controller matrix of 50 container + 70
native checks.

## API and storage measurements

With 2316 files, median time for three full `.id,name` directory reads was
1.926 s. A targeted small journal-pointer query plus contents took 0.04054 s,
approximately 47 times less in this experiment. This is a lab API measurement,
not a promise for all operations or hardware.

Confirmed-deployment preparation took 6.3 s; an earlier measurement on the same
long-running fixture before optimization was 65.77 s. These were different
moments and cannot be treated as a controlled CPU benchmark. Full directory
queries were replaced with bounded queries for specific names.

Safe cleanup on a real CHR directory removed 2338 obsolete files, 34895269 logical
bytes, in 195 s. Free space changed from 430567424 to 471658496 bytes (approximately
+39.2 MiB including blocks/metadata). Active JSON, controller source and the current
transaction were unchanged. This was one-time accumulated-history cleanup, not
a per-tick background operation.

Installing with `maintenance.backup_keep=3` ran cleanup exactly once after commit,
removing 13 files from the old group. Original JSON without maintenance was then
applied: all SLA healthy; default/client101 → WAN1, client102 → WAN2,
strict103 → WAN3. Both labs were left running, with the container active.

## Failure validity

The old API-disable scenario could fail while selecting a dynamic service record
before actually disabling API. The fixture now selects the sole static service,
checks `disabled=true`, then raises an explicit error. The journal must contain
that exact reason before recovery can be declared successful. The CHR scenario
passed again after this fixture correction.

Corrupt journals, empty/invalid current schemas, identity mismatch, pending/recovery
and file-ID changes cause no deletion. Preparation failure before a usable binary
backup cannot evict saved working recovery points. Unexpected maintenance errors
after commit are not presented as failed deployment.

## CI and limits at that stage

The workflow ran Linux/Windows Python, offline Windows GUI, Gitleaks, nine Rust
units and three-architecture cross-build/ELF/archive checks. CI did not connect
to MikroTik or execute CHR fault tests. A write-enabled release job ran only for
an explicitly pushed `v*` tag after other jobs; ordinary jobs were read-only.
Downloaded CI archives were checked against their artifact's `SHA256SUMS`.

Compiler build paths mean byte identity with the original local v0.1.0 ELF is not
claimed. Controller code remained the same; each build report records its own
sizes and hashes.

Full private reports stay in Git-excluded `runtime/`. Passwords, device exports,
journals/backups and private inventory are excluded from public source. Publication
review and secret scanning remain mandatory.

## Statistics/web

The [RAM-only design](STATISTICS-DESIGN.en.md) was prepared at this historical stage;
HTTP serving and history collection had not yet been added. That stage introduced
no ports, polling, database or flash metric writes. Subsequent implementation and
its separate resource/fault checks are described in [STATISTICS.md](STATISTICS.en.md)
and [STATISTICS-VALIDATION.md](STATISTICS-VALIDATION.en.md).
