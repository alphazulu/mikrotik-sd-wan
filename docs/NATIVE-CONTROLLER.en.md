# Local SD-WAN on RouterOS

[Русский](NATIVE-CONTROLLER.md) | English

Native mode executes decisions in `native/sdwan-controller.rsc`, installed as
`/system script sdwan-controller`, scheduled every second. In container mode,
local Rust proposes choices and RouterOS validates/applies them with native
fallback: [container](CONTAINER.en.md). External software is not the recurring
control-loop collector/selector and is unnecessary after deployment.

## Native core behavior

- Separate probe tables/sources: lookup-only-in-table prevents failed-WAN probes
  from escaping through backup.
- Netwatch ICMP RTT/jitter/loss plus multiple HTTP/HTTPS/TCP/DNS targets. HTTPS
  checks certificates; DNS requires an explicit server.
- Target quorum and per-profile/WAN unknown/healthy/degraded/down/recovering states.
- Good/bad windows and hold-down since last bad sample; scheduler polling does
  not repeatedly count one Netwatch window.
- Immediate carrier loss handling and no permanently healthy stale samples.
- Prefer selects first healthy allowed WAN; strict permits one without main bypass.
  Degraded is explicit and only used when no allowed WAN is healthy.
- FIB, client/incoming/router marks and symmetric WAN/DNAT replies; local bypass.
- Policy-scoped conntrack removal on switching/return, preserving other policies;
  ordinary NAT remains.
- Router-local state/route logs and diagnostic global `sdwanStatusJSON`.
- Native deployment, owned-object reconciliation and baseline rollback, tagged
  `sdwan:v1:`. Public configuration has no secrets.

[Marks, tables and cleanup](DATAPLANE.en.md).

## Configuration files

Editable `config/sdwan.json` becomes compact router `sdwan-config.json`. After
successful reconciliation, installer promotes it to `sdwan-active.json`.
Controller reads only the active copy; editing an uploaded draft does not mutate
the running configuration.

| Section | Purpose |
|---|---|
| revision | Operator version label |
| health | Interval, timeout, packet count, quorum, fail/recover windows, hold-down, stale timeout |
| wans | static/dhcp/pppoe/lte/vpn, L3 interface, APN/VPN transport, static-only address/gateway, probe table/targets |
| sla_profiles | Mean RTT, jitter=max-min and loss limits |
| policies | Client/subnet, table, SLA, mode and WAN order |
| local_networks | Destinations using main |
| takeover_route_comments | Explicit original defaults adopted/disabled |
| takeover_rule | Original rule replaced by SD-WAN policies |
| takeover_routes | Optional exact defaults, including uncommented routes |
| disable_fasttrack | Optional FastTrack selectors for policy routing |

Lab timers are accelerated: interval 2 s, fail 2 windows, recover 3 windows,
hold-down 6 s, not approved production defaults. A 20-packet ICMP window makes
one lost packet 5%; finer limits need more samples/time. Configurator checks
that train plus timeout fits the interval.

RTT/jitter use ms with 0.001 ms precision; loss uses % with 0.01% precision.
Scripts scale fractional JSON values to integers. Loss comes from sent/response
counts rather than RouterOS internal loss-percent format. Status rtt_us/jitter_us
are microseconds; loss_basis_points=100 means 1%.

JSON changes require protected redeployment. Active-config change resets windows
and warms up again. GUI/CLI upload, reconcile and activate a version; do not edit
active files directly to change topology.

## Windows GUI

Double-click `Configure-SD-WAN.cmd`, or:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Start-Configurator.ps1
```

Python/Tkinter is used; Windows GUI was tested with Tk 8.6. Connect/read first,
then select WANs/targets; generation opens WAN/SLA/client/timer forms.
[Wizard](CONFIGURATOR-WIZARD.en.md). Actions include open/save JSON, local validation,
offline bundle export, change preview, protected installation/fresh confirmation,
state/decision-log reads and return-to-baseline.

Lab URL is `api://127.0.0.1:18728`; Lab fills credentials from local
`runtime/credentials.json`. For another device enter URL/user/password; discovery
reads identity. API TCP, TLS and REST HTTPS are supported; HTTP only on loopback.
TLS verifies hostname/certificate with optional CA. Existing interfaces/NAT are
prerequisites. Physical static/DHCP/PPPoE/LTE use logical interfaces without
dynamic lease snapshots; provider clients/credentials already exist. LTE uses
its existing APN and appropriate gateway: [LTE](LTE.en.md),
[dynamic WANs](DYNAMIC-WAN.en.md).

## Development CLI

From the project directory:

```bash
python3 sdwan.py validate
python3 sdwan.py bundle --output build
python3 sdwan.py plan
python3 sdwan.py apply
python3 sdwan.py status
python3 sdwan.py events
python3 sdwan.py disable
python3 sdwan.py enable
python3 sdwan.py rollback
```

Disable stops the local scheduler and retains last routing. Rollback returns
baseline. Closing CLI/GUI does not stop autonomous scheduling.

Apply checks identity/version 7.24.5/interfaces/conflicts and saves a diagnostic
snapshot. Local scheduler/watchdog, encrypted full backup and fresh API ACK
protect deployment. Failure/missing ACK restores and reboots:
[procedure/permissions/limits](DEPLOYMENT.en.md).

`sdwan-backup.json` separately retains adopted route/FastTrack/rp-filter flags.
Baseline rollback restores these; emergency deployment recovery restores the
full snapshot immediately before that operation. `sdwan-*` files/tables and
project script/scheduler names plus `sdwan:v1:` are reserved. Never run concurrent
installers. Standard export is JSON plus 11 RSC files; manual import bypasses
protection, so use the normal GUI/CLI.

## Lab targets

`tools/probe_services.py` serves HTTP on host loopback 28081/28082/28083, reachable
from each ISP through QEMU alias `10.77.N.2`. Edge→ISP→targets traverses ISP
forwarding/NAT, so disabling forwarding keeps gateway ping but breaks probes.

```bash
python3 tools/probe_services.py start
python3 tools/probe_services.py status
python3 tools/probe_services.py fail a
python3 tools/probe_services.py heal
```

Lab up starts these simulated Internet servers, not a controller. Three ports
on one host are not independent operators. Replace with agreed independent
production targets; host/shared uplink remain lab failure points.

## Initial native checks and limits

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 tests/native_acceptance.py
python3 tests/native_numeric.py
```

Units reject unsafe configurations. Integration injects faults while RouterOS
decides: client paths, quorum, duplicate windows, failure beyond reachable gateway,
hold-down, different SLAs, strict, all-WAN down, stale, reboot, rollback/reapply.
Fixtures restore in finally; private report is `runtime/native-acceptance.json`.

These describe the original native milestone. Dynamic WANs, optional overlay
and protected installer recovery are now implemented; see
[current acceptance](CURRENT-STATUS.en.md). PCC/weighted balancing, seamless TCP
NAT-IP migration, QoS, IPv6, expanded secrets/roles and persistent logging are
not claimed. Probe-window quality is not monthly statistical SLA or a production
guarantee. [Roadmap](../ROADMAP.en.md).

## Groups, applications and diagnostics

[Policies](POLICIES.en.md) describes selectors/groups. Native links includes
ordering/match helpers and bounded RAM history; standard package is 11 RSC+JSON.
Status has interface/APN, age, recovery/hold timers and selection reasons.
[GUI diagnostics](DIAGNOSTICS.en.md) reads owned snapshot/active JSON; decisions
remain local.

Runtime reports, credentials and device snapshots stay private.
[Reproduction](TESTING.en.md).
