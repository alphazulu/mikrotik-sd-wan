# RAM statistics and local web interface

[Русский](STATISTICS.md) | English

The optional module runs in the same Rust container on MikroTik. The main loop
and single RouterOS executor continue handling routes, conntrack and SLA. Web
displays state, charts and events; it has no HTTP configuration/routing commands
and needs no external server.

## Enabling

The module is disabled by default. Minimal `sdwan-controller-ARCH` builds without
Cargo feature `web` and contains no HTTP server. Separate `sdwan-controller-web-ARCH`
embeds the server and HTML/CSS/JS. Even that image creates no listener, history or
threads and reads no web token until `container.telemetry.enabled` is enabled.

1. Select local Rust mode in the configurator and prepare the matching web image:
   amd64 for CHR/x86_64, arm64 or armv5 for the appropriate MikroTik.
2. Enable the module on the web/statistics tab. Set sample period, history size,
   port, allowed RFC1918 IPv4 networks and incoming LAN/VLAN interfaces. Networks
   must belong to `local_networks`. WANs, their PPPoE/VLAN carriers, bridges and
   bridge ports are forbidden. WAN-list include/exclude and explicit members
   follow [RouterOS ordering](https://manual.mikrotik.com/docs/cli-reference/interface/list/).
3. Stop the prepared container before changing files. Prepare the container,
   then run protected SD-WAN installation. Preparation verifies image web entrypoint,
   read-only mounts, permissions and API identity.
4. Copy the token from MikroTik, then open web. The browser must be on an allowed
   LAN/VLAN with a route through MikroTik to the separate container subnet, for
   example `http://172.31.255.2:8080/`.
5. Enter the token on the login page. It stays only in page memory, never URL,
   localStorage or sessionStorage. Logout/reload clears it. The configurator clears
   its clipboard after 60 seconds if the clipboard has not changed.

The complete [container-web.json](../config/examples/container-web.json) uses
synthetic lab addresses; inspect your device with the wizard first. Example
public telemetry fragment:

```json
"telemetry": {
  "enabled": true,
  "sample_seconds": 10,
  "history_points": 360,
  "port": 8080,
  "allowed_sources": ["192.168.50.0/24"],
  "allowed_interfaces": ["bridge-lan"]
}
```

This field belongs inside `container`; JSON contains no password/web token.
The secret is 32 random bytes encoded as 64 hex characters, stored at
`<storage>/secrets/web-token`, mounted as `/secrets/web-token`. Preparation reuses
a valid token. To rotate, stop the container, remove only that file and prepare
again. Disabling telemetry does not delete the secret automatically.

## Displayed information

WAN cards show RTT, jitter, loss, selected-profile SLA state, IP/interface and
RX/TX rates. Policies show selected WAN and observed transition counts. All SLA
profile states, events, charts and bounded JSON history export are available.

The network iteration adds enabled/drain/down modes, new-connection admission,
drain timers and VPN-egress physical transport. Branch paths show inner SLA,
WAN, OSPF cost and probe age. This is SLA admission for OSPF; actual neighbors
are inspected separately by the API configurator. Each new table has at most
16 rows in the current RAM snapshot without expanding history rings. API passwords,
peer keys and endpoints are excluded. Exact CI images passed targeted CHR checks;
long candidate acceptance continues. [Current status](CURRENT-STATUS.en.md).

Rates use differences in selected interfaces' `rx-byte`/`tx-byte` counters without
extra traffic probes. Counter reset, interface change or missed reads yield
`null`/a dash. This is interface traffic including control packets, not provider
billing or per-application/client statistics. Events belong to the current
revision/boot/generation epoch.

Time without a healthy path covers observed intervals only; long gaps do not
invent downtime. If HTTP replies but observations exceed ten seconds, web marks
them stale. HTTP failure retains the last snapshot with a no-fresh-data marker;
age becomes a dash, and VPN/overlay admission is also marked stale. Successful
polling restores current state. Missing new snapshots clear old metrics. Selected
`none` means no available WAN. Browser display does not control MikroTik routing.
Container/router restart and epoch changes clear history; long-term SLA reporting
is not provided.

## Resource limits

| Parameter | Value |
|---|---|
| History interval | Default 10 s, range 5–60 s |
| History per WAN | Default 360 points, maximum 600 |
| WANs / policies / SLA states | 16 / 64 / 1024 |
| Events | Last 128 with bounded strings |
| Main-loop snapshot delivery | Queue 1, `try_send`, maximum 256 KiB |
| API counters | Separate session, replies up to 64 KiB / 32 rows |
| Module threads | Collector and HTTP, each 128 KiB stack |
| HTTP | Headers 4 KiB / 250 ms, response up to 1 MiB / 2 s |
| HTTP rate | Shared bucket 8 requests, refill 2 requests/s |

JSON serialization/send happens after releasing the lock. Slow clients, unavailable
counter API or a full queue do not delay heartbeat. Web startup failure leaves
the main controller operating. The image stays scratch with one static binary,
without shell, database, Node.js or CDN.

## Storage and swap

The module creates no data/cache/access-log/temp/SQLite/WAL/checkpoint files.
History/event rings stay in RAM. Export builds an HTTP response in RAM; the
browser saves the file on the operator's computer. Explicit preparation writes
settings and secret once. Existing controller intent still records WAN/claim
changes: no statistics writes does not mean no RouterOS writes at all.

Preparation disables container logging. On CHR 7.24.5, `swap-max=0` reads back
as `unlimited`, so preparation sets minimum positive `swap-max=1`. Kernel page
rounding means this alone is not proof of no swap. Enabling RAM statistics also
requires no enabled swap devices under `/disk`; global disks are not modified.
Do not enable swap afterward if data must remain strictly in RAM. See
[RouterOS containers](https://manual.mikrotik.com/docs/containers/) and
[disks/swap](https://manual.mikrotik.com/docs/hardware/disks/).

## Access and API

Preparation creates a separate address list and exact forwarding rules for allowed
LAN interfaces, sources and container TCP port. WAN drop precedes LAN accept;
general forwarding restrictions to/from the container remain. No WAN port/DNAT
is opened. Preflight rejects changed scopes/order/image. The container also
checks source IP and bearer token. HTTP is for trusted LAN/VPN access; built-in
TLS and public exposure are not provided.

To retain client IP, preparation inserts a narrow `srcnat accept` before existing
source NAT, restricted to the allowed source list, container address/bridge and
HTTP port. Broad LAN masquerade then does not hide statistics clients. Existing
NAT rules are unchanged; disabling telemetry removes only this owned exemption.

| GET endpoint | Content |
|---|---|
| `/`, `/style.css`, `/app.js` | Embedded shell without secrets |
| `/api/status` | Safe current snapshot, age/stale and resources |
| `/api/history?max=120` | History, `max` 1–600 |
| `/api/events?since=0` | Up to 128 events for the current epoch |
| `/api/export` | History/events JSON attachment |

JSON requires `Authorization: Bearer <web-token>`. Query tokens are forbidden.
POST/PUT/DELETE, foreign Origin, ambiguous headers and extra parameters are
rejected. There is no CORS. Responses use `no-store`, CSP and iframe prevention.
Full configuration, API password, owner nonce, intent, backups and recovery
journal are excluded. The UI does not use `innerHTML`.

## Upgrade and rollback

Changing GUI `image_file` does not replace an existing container filesystem.
Preparation requires the web image to be imported first. Upgrade stopped instances
while retaining old image, settings and secret; `/container/save` can archive
root directory and settings. Native fallback operates during the stop. Statistics
snapshots are not preserved across replacement.

Protected SD-WAN deployment restores RouterOS configuration, **not the container
image filesystem**. Restore that separately by importing the saved image archive
and preparing the corresponding mounts.

[Original architecture](STATISTICS-DESIGN.en.md).
