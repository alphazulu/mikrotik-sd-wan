# MikroTik SD-WAN

[Русский](README.md) | English

SD-WAN for RouterOS with SLA monitoring, WAN priorities, automatic failover and
client policies. The controller runs on MikroTik itself: RouterOS scripts or one
static Rust process in a `FROM scratch` image. Routing does not need an external
server. The configurator handles setup and diagnostics and can be closed after
installation.

## Project status

This branch develops candidate **0.3.0**. The web interface, VPN WANs and branch
overlay are implemented and have passed targeted checks. Long acceptance of the
current candidate is still running; release 0.3.0 has not been published. The
image catalog contains its future URLs, so automatic downloads can return HTTP
404 until publication.

[Current validation status](docs/CURRENT-STATUS.en.md) is separate from historical
reports and the [roadmap](ROADMAP.en.md). A short passing check does not establish
completed long acceptance or physical hardware capacity.

## Features

- IPv4 WANs: static interfaces, DHCP-client, PPPoE, LTE with an existing APN,
  and already configured WireGuard, L2TP, SSTP and OpenVPN clients.
- Availability, RTT, jitter and loss SLAs: independent targets, quorum, failure
  and recovery windows, hold-down and stale-measurement protection.
- Shared WAN preference lists, including VPNs. Policy source and destination
  can each be an IP/subnet or MikroTik Address List and can be combined.
  Interface, protocol, ports, rule priority and `prefer`/`strict` modes are supported.
- Connection marks and routing tables for symmetric WAN/DNAT replies, with
  selective removal of owned conntrack entries during switching.
- `enabled`, `drain`, `down` maintenance modes and separate `jump` chains.
- Optional branch WireGuard/OSPF paths through a reachable public hub, including
  branches behind CGNAT; inner SLA probes and local-network protection.
- GUI/CLI, editable JSON, change preview, diagnostics and flow explanations.
  Provider clients and external VPNs must already be configured.
- Protected deployment using local workers/watchdogs, encrypted backup and
  confirmation over a fresh API connection. RSC takes over after container loss.
- Optional web image: RAM history for SLA/RX/TX, policies and events, with JSON
  export to the operator's computer. Disabled by default; no configuration writes.
- Avoidance of repeated identical file writes and explicit backup retention.

## Supported environment

Installation is pinned to **RouterOS 7.24.5**. GUI/CLI are tested with **Python 3.12**;
there are no pip dependencies, and the GUI requires Tkinter. Rust images target
`linux/amd64`, `linux/arm64` and `linux/arm/v5`; execution is checked on CHR/x86.
An ARM build alone does not prove operation or capacity on physical hardware.
Container mode needs suitable packages, architecture, device-mode and storage:
[device preparation](docs/CONFIGURATOR-PROVISIONING.en.md).

The lab uses Linux/WSL2 and QEMU. Each topology has its own disks, ports and
resource ownership; disruptive workloads run sequentially. See the
[lab guide](docs/LAB.en.md) and [external generators (English)](labtools/README.en.md).

## Quick start

```sh
git clone https://github.com/alphazulu/mikrotik-sd-wan.git
cd mikrotik-sd-wan
python3 configurator.py
```

Windows also provides [Configure-SD-WAN.cmd](Configure-SD-WAN.cmd).

1. Connect to the API and read the router configuration. Use `apis://` with a
   verifiable certificate for TLS; use plain API inside a trusted management network.
2. Select WANs and priorities. PPPoE uses its logical client interface; LTE uses
   its interface and existing APN. Add an external VPN as an ordinary WAN.
3. Configure probe targets, SLAs, internal networks and policies; save the JSON.
4. Select RSC or the local container. For a container, inspect prerequisites,
   choose storage and prepare the appropriate image separately.
5. Review the change plan and run protected deployment. Check confirmation and
   diagnostics over a fresh API connection.

Existing third-party mangle rules require a [migration plan](docs/MIGRATION.en.md),
rather than disabling all rules. Generating a draft does not authorize its installation.

## CLI and configuration

The repository contains synthetic examples only. `config/sdwan.json` describes
the lab; generate your own device configuration in the wizard. The historical
`config/sdwan-intent.json` is not installer input.

```sh
python3 sdwan.py --config config/sdwan.json validate
python3 sdwan.py --config config/sdwan.json bundle --output build/native
```

Credentials belong in a separate local file outside Git. `plan`, `apply`, `status`,
`events` and `rollback` use the connection, CA, credentials and expected device
identity options. See the [wizard](docs/CONFIGURATOR-WIZARD.en.md),
[JSON reference](docs/CONFIGURATION.en.md), [deployment](docs/DEPLOYMENT.en.md)
and [secret handling](SECURITY.en.md).

## Container and web

Each scratch image contains one Rust/musl ELF running as UID `65532:65532`, without
a shell, distribution or database. Separate read-only mounts supply settings and
secrets. Two profiles (`base`, `web`) and three architectures produce six archives.
Exact sizes, SHA256 values and image IDs live in the [catalog](config/container-images.json)
and build report; local builds can differ from CI byte for byte.

Every container change requires **100% executable line and function coverage**
for Rust base/web, `main` and browser JavaScript before building. Coverage binds
to exact source bytes; branches are reported separately. The resulting image
also needs isolated RouterOS checks. See [coverage](docs/CONTAINER-TESTING.en.md),
[building](docs/BUILD.en.md), [installation](docs/CONTAINER.en.md)
and [web](docs/STATISTICS.en.md).

Statistics stay in RAM. Reboot, configuration changes or container replacement
clear history. Unavailable write counters are not treated as zero. Virtual-lab
results do not automatically establish physical ARM/ARM64 recommendations:
[methodology](docs/PERFORMANCE-PLAN.en.md),
[historical results](docs/PERFORMANCE-RESULTS.en.md).

## Checks and limits

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 tools/audit_public_tree.py
python3 tools/container_checks.py
```

The last command needs the SDK from the [coverage guide](docs/CONTAINER-TESTING.en.md).
Do not duplicate an existing run or inject faults into a busy lab. Historical
and current counts are not added together as unique tests.

IPv4 is supported. IPv6, PCC/weighted balancing, QoS and application classification
beyond L3/L4 remain planned. Existing OSPF/VPN, VRFs and foreign marks need review;
universal automatic migration is not implemented. CGNAT alone does not provide
inbound reachability.

[Documentation index](docs/README.en.md) · [OSPF/VPN compatibility](docs/OSPF.en.md) ·
[Roadmap](ROADMAP.en.md) · [RU/EN conventions](docs/LANGUAGES.en.md)

Licensed images, real device exports, passwords, backups, captures, screenshots
and `runtime/` contents are not distributed as source.
