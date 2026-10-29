# GUI: from connection to a configuration

[Русский](CONFIGURATOR-WIZARD.md) | English

On Windows, double-click **`Configure-SD-WAN.cmd`**. No pip dependencies are needed;
Python with Tkinter is required.

## 1. Read MikroTik settings

Enter the API address, username and password, then use the connect/read-settings
button. A password file is not required. The form masks the password and does not
save it in SD-WAN JSON or discovery reports.

| Connection | Example |
|---|---|
| RouterOS API | `api://192.168.88.1:8728` |
| RouterOS API with TLS | `apis://router.example.net:8729` |
| REST with TLS | `https://router.example.net` |
| Prepared lab | Lab button, then connect to `api://127.0.0.1:18728` |

The corresponding router service must already be enabled and reachable. The
wizard does not enable management services or open the firewall. Plain API sends
credentials without encryption; use a trusted management network or protected
VPN transport. `apis://` requires a server certificate; the CA field accepts a
trusted PEM, with hostname and chain validation. HTTP REST is allowed only on
loopback, such as lab `http://127.0.0.1:18080`.

The wizard reads identity, version, interfaces, IPs, routes, routing rules,
DHCP/PPPoE, bridges, WAN list, NAT, FastTrack and routing marks. It also reads an
existing SD-WAN active configuration. User lists, PPPoE passwords and private
keys are not requested. Inventory stays in local `runtime/discovery-*.json`.

Reading does not change the router. Permission errors appear in the log; missing
conflict-check data blocks configuration creation.

## 2. Select WAN interfaces

On step 1, select WAN checkboxes in the first column. Connecting does not select
interfaces automatically. The recommendation button uses existing SD-WAN, WAN
list membership and discovered gateways as hints.

Check each WAN's IPv4, gateway and priority: **1 is primary**, subsequent values
are backups. Choose among multiple addresses/gateways in the lower form. Enter an
unknown gateway explicitly; the wizard does not invent `.1`. Interface names can
be arbitrary, including spaces.

Recursive routes use the actual next hop from `immediate-gw`, not the remote
probe target in `gateway`. Missing static IPv4/gateway makes Next/Create identify
the WAN and reason, return to step 1 and select its row. Dynamic runtime addresses
are not saved as static values. The recommendation button excludes dynamic WANs
and interfaces without an address.

Static addresses must already exist on MikroTik. Bridge ports are not independent
L3 WANs; select the corresponding bridge/VLAN. Overlapping WAN subnets require
separate VRF design and are rejected.

## 3. Targets and generation

On step 2, set ICMP and TCP/HTTP/DNS targets reachable through selected WANs.
Existing devices can retain their probes and client policies. Existing SD-WAN SLA
profiles are copied into the editor.

Probe names can contain dots, for example `ya.ru`. This is an identifier; the
actual target is entered separately in the IP/DNS field.

Generate from selected interfaces to open step 3 forms for WANs, SLAs, clients,
WAN order and timers. Local networks come from unselected interfaces' addresses.
Removing a WAN needed by a saved client policy requires correcting that selection.

New-device initial timers are a five-second interval, three bad windows, six good
windows, 60-second hold-down and quorum two. These are starting settings, not an
agreed SLO. Existing SD-WAN keeps its timers/lab targets if retention is selected.

**Generation is local.** Subsequent actions are:

1. Validate values and conflicts.
2. Save editable JSON, suggested as `config/discovered-<identity>.json`.
3. Export RouterOS files: the standard bundle has 12 files, `sdwan-config.json`
   and 11 core/deployment `.rsc` files. `sdwan.py` defines `FILES`.
4. Review the change plan, including original routes and FastTrack.
5. Install: prepare a backup, start the local worker and confirm over a fresh API connection.

Deployment retains a snapshot and original disabled flags. Selected WAN default
routes are disabled using exact selectors, even without comments. FastTrack that
conflicts with policy routing is disabled with its original state retained. Changed
objects require another discovery. Return-to-baseline restores flags and removes
project objects.

The controller, SLA and switching run on MikroTik. The configurator can close
after deployment. Connection marking, symmetric WAN/DNAT replies and selective
conntrack cleanup are included automatically. See [dataplane limits](DATAPLANE.en.md).

## Version limits

- Deployment is checked and permitted for RouterOS **7.24.5**.
- Static, DHCP-client, PPPoE and native LTE IPv4 WANs are supported. Select the
  logical PPPoE client or DHCP client interface, including a VLAN. Provider clients
  must already exist. Runtime IPs are informational; JSON stores type/interface
  and RouterOS resolves address/gateway. An enabled client without a lease/session
  can be selected; it stays closed until an address and fresh SLA exist.
  See [dynamic WANs](DYNAMIC-WAN.en.md).
- Existing IP, NAT and baseline firewall are used; initial configuration is outside
  this wizard. Missing outbound NAT is reported in the log.
- Conflicting active mangle needs review. The wizard can save a draft/report, but
  installation remains blocked until migration. VRFs, recursive gateways and
  third-party policy routing need separate design.
- Return-to-baseline differs from emergency binary restore/reboot after deployment
  error or missing confirmation. Reboot/sensitive permissions are required.
  See [deployment](DEPLOYMENT.en.md).

Use [config/sdwan.json](../config/sdwan.json) only as a lab example. Generate your
own device configuration. [GUI validation](WIZARD-VALIDATION.en.md).

Already configured WireGuard/L2TP/SSTP/OpenVPN clients join common policy preference
lists as VPN WANs: [VPN wizard](VPN-EGRESS.en.md). The wizard does not configure
external servers or client passwords.

LTE displays its selected APN profile. JSON stores kind/interface/apn_profile
without runtime IP/gateway. APN automatic default routes are coordinated with
SD-WAN and original values retained for rollback. See [LTE](LTE.en.md).

## Diagnostics and advanced policies

The diagnostics tab works after connection without generating JSON: WAN/SLA,
policy selections/history, manual/automatic refresh, export and new-flow
explanations. See [diagnostics](DIAGNOSTICS.en.md). The editor has address groups
and source/group/interface/protocol/port selectors, priorities and overlap checks:
[policies](POLICIES.en.md).

Runtime reports, credentials and device snapshots remain private.
[Reproducing checks](TESTING.en.md).

## Existing mangle

The wizard can prepare a draft/conflict list while preserving the installation
block until old marking is migrated. [Workflow and local reports](MIGRATION.en.md).
