# Optional statistics and web: original architecture

[Русский](STATISTICS-DESIGN.md) | English

Status: **implemented as optional Cargo feature `web` in version 0.2.0**.
Instructions, actual limits and settings are in [STATISTICS.en.md](STATISTICS.en.md).
The original requirements below are retained as design history. Measured behavior
and implementation limits take precedence over target budgets. The base image
contains no HTTP server.

## Purpose and placement

Statistics/web run in the same local MikroTik container. The existing Rust/RouterOS
mechanism retains all WAN decisions. Web receives read-only snapshots, never
becoming another route executor. Stopping web must not alter SLA, heartbeat,
conntrack or WAN selection.

The base remains `FROM scratch`. Cargo feature `web` allows the controller-only
variant to stay minimal. Even the web variant is disabled by default, without
listener, HTTP thread, history or web token until explicitly enabled. No framework,
database, Node.js, CDN or separate process is needed.

## Sources and data

Use already-read `sdwanStatusJSON`: RTT/jitter/loss, WAN readiness, sample freshness,
selected WAN and container/fallback mode. Never expose full configuration, API
password, intent, recovery journal or backup. Read selected-WAN RX/TX separately
at its own interval without duplicate Netwatch probes. Counter failures must not
affect decisions; unavailable values are `null`, not fabricated zero.

RAM stores a small current WAN/policy snapshot, revision/stale marker, ring history
of measurements/rates, bounded events for WAN/SLA/fallback/reboot/config changes,
uptime, switching counts and observed unavailability during the current run.
Traffic counters are not provider billing. Counter/interface/reboot changes must
not create rate spikes; boot/config epoch changes invalidate old time-series
compatibility and mark an event boundary.

## RAM budget

Initial design: ten-second interval, 360 points (about an hour), maximum 16 WANs
and 600 points. Store WAN/profile/policy strings once; points use indexes and
numbers. A 64-byte WAN-point budget gives at most 614,400 bytes for series.
This is a design calculation, not measured implementation RSS.

Up to 128 bounded events, a fixed current-snapshot buffer, bounded JSON replies
and one HTTP thread with a 128 KiB stack were proposed. Target module budget:
at most 2 MiB, to be checked on CHR and physical ARM. Do not allocate unbounded
memory per request/client. Ring overflow replaces old data without expanding
files/memory. Insufficient budget rejects module startup while SD-WAN continues.

## Storage writes

| Operation | Statistics-module writes on MikroTik |
|---|---:|
| Polling, history points, events, charts, HTTP requests | 0 |
| Heartbeat and RAM snapshot updates | 0 |
| Restart/reboot | History is lost; no automatic checkpoint |
| Browser JSON/CSV download | 0; file saved on the operator's computer |
| Module settings/secret change | Explicit preparation/deployment only |

No SQLite/WAL, append logs, cache, access log, temp files or periodic autosave.
Build replies from RAM with `Cache-Control: no-store`. Disable container logging
and avoid logging each HTTP request/packet. This is not a promise of zero writes
by all RouterOS: configuration, backups, container startup and existing intent
changes are outside RAM statistics. Unchanged WAN selection avoids intent rewrites.

Long history should use external metric reads or manual export while decisions
remain local. Optional USB/SSD persistence would need a separately enabled mode,
explicit directory, bounded size and batched writes, never automatic internal
flash selection. It is outside the first RAM-only milestone. MikroTik recommends
attached storage for container volumes: [containers](https://manual.mikrotik.com/docs/containers/).

## HTTP and interface

The first version is read-only: WAN state, RTT/jitter/loss and RX/TX charts,
switch history, actual actor and export. Editing remains in the existing GUI.
Statistics reads do not invoke apply/rollback.

Proposed bounded GET endpoints: `/` for embedded assets; `/api/status` for safe
state/age; `/api/history?max=120` for bounded points; `/api/events?since=...` for
events in the current boot epoch; `/api/export` for bounded RAM-history output.
Reject POST/PUT/DELETE and unknown paths. Bound headers to 4 KiB, path/query
length, read/write deadlines and polling rate. Slow clients cannot hold the
controller lock: copy briefly using `try_lock`/messages, then serialize/send after
unlocking. Bind/client/export failures are isolated from the main loop.

## Access and configuration

Allow only explicit management networks through the firewall. Keep forwarding
to the container blocked by default. Only web enablement adds allowances; no
WAN/DNAT access is created. Use a separate random read-only web token in a secret
mount, never the API password. Do not place it in URLs, configuration JSON or logs.
The browser keeps it in page memory, not localStorage.

Remote access requires a protected management channel. The first small HTTP
service is for trusted LAN/VPN only; public HTTPS, embedded TLS and configuration
mutation would require another milestone. Enforce same origin, no wildcard CORS,
frame prevention and safe labels through `textContent`, never executing configuration
strings as HTML/JS.

The original proposed `container.telemetry` contract was `enabled=false`,
`sample_seconds=10`, `history_points=360`, `port=8080` and explicit `allowed_sources`.
Those fields were not accepted at the design stage; the implemented schema is
now documented in [STATISTICS.en.md](STATISTICS.en.md). No default persistent
history path exists. GUI should show RAM/reboot retention, estimated buffer size
and allowed networks.

## Acceptance requirements

1. Disabled: no listener/new rules/history allocation/disk writes.
2. Enabled: bounded history/events/replies and rejected excess requests; no API
   password/secrets in JSON, HTML, URL, errors or stdout.
3. HTTP bursts, slow clients and invalid tokens do not delay WAN selection or
   native fallback; actual routes/marks/conntrack checked on CHR.
4. Counters/I/O inspection show no history/metric/access-log writes; unchanged
   intent avoids writes. Export creates a file only on the client.
5. Measure RSS/CPU/image size for three architectures with feature off/on; check
   long soak, config changes, reboot, counter reset and abnormal termination.

Original sequence: bounded RAM storage/unit checks → sanitized API → embedded
page → LAN/token/firewall GUI → fault/resource acceptance. Public exposure and
periodic flash persistence are not part of that design.
