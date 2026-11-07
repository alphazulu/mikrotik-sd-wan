# Connections, WAN symmetry and conntrack cleanup

[Русский](DATAPLANE.md) | English

RouterOS manages routes, marks and conntrack removal. GUI prepares/deploys only.
The standard bundle contains `sdwan-config.json`, eight core RSC files and three
deployment RSC files. Installer imports `sdwan-dataplane.rsc` after creating FIB tables.

## Marks and routing

| Traffic | Connection mark | Routing mark/table |
|---|---|---|
| New connection entering WAN | `sdwan-in-<wan>` | Incoming packet continues INPUT/DNAT; replies use that WAN table |
| Outbound client connection | `sdwan-out-<policy>:<wan>` | Permanent table of selected WAN |
| Router-originated connection | `sdwan-router-<wan>` | Actual egress WAN table |
| Source-bound probe to configured target | `sdwan-probe-<wan>` | Tested WAN table, excluded from ordinary-session cleanup |

Prerouting jumps to `sdwan-pre`, output to `sdwan-output`, postrouting to
`sdwan-post`, before other static mangle rules. Incoming connection mark is set
before DNAT. A DNAT server reply retains it and uses original WAN even if the
server's outbound policy prefers another. Router replies get routing marks in output.

New clients match explicit policies before default. Marks include policy and WAN,
so clients on one provider can switch/clean independently. Marked flows are not
reclassified every packet. Unmarked established/related traffic can receive marks
so a missed first packet does not leave it permanently unclassified.

Router-local addresses and `local_networks` bypass outbound WAN selection first.
Incoming WAN packets do not get a routing mark back to that WAN: after connection
marking they continue ordinary INPUT/DNAT/reply delivery.

Controller enables only selected-WAN classifiers. If none assigns a connection
mark, the policy chain's terminal `drop` rejects matching unmarked traffic rather
than falling through to default. Strict has no backup. Permanent WAN tables also
have blackhole default distance254, preventing main bypass when next hop is unavailable.

For initial local-reply lookup, installer adds source rules for selected IP and
additional IPv4 addresses on that interface. Reachable WAN IPs can still answer
when SLA disables main defaults. Reapply after adding/removing permanent aliases.
Primary DHCP/PPPoE/LTE address/gateway/interface resolve locally on lease/session
changes rather than being saved as aliases. See [dynamic WANs](DYNAMIC-WAN.en.md).
Marks cannot restore physical reachability.

Router-originated traffic gets a postrouting mark before srcnat, separated from
forwarded clients by `src-address-type=local`. Source-bound probes remain on their
own WAN, never escaping a failed channel through backup.

Targets use `sdwan-probes-<wan>` lists and a separate connection mark, so ordinary
router-session cleanup preserves probes. DNS targets its server; TCP/HTTP targets
host; ICMP targets `icmp_target`. Lists support IP/DNS using
[RouterOS Address-lists](https://help.mikrotik.com/docs/spaces/ROS/pages/130220135/Address-lists);
the device must be able to resolve probe names.

## Removal during switching

When a policy changes from WAN A to B or `none`, controller:

1. Reconciles routes and the new-connection classifier.
2. Removes exact previous `sdwan-out-<policy>:<wan-A>` entries.
3. Also removes `sdwan-router-<wan-A>` when default changes.
4. Publishes reason, old/new WAN and removal count.

Return to primary does the same. Another client retaining WAN2 keeps its sessions.
There is no global `/ip firewall connection remove [find]`.

For three seconds after selection change, exact client marks of unselected WANs
are additionally retired, covering packets already processing at the switch.
Selected marks and other policies are excluded.

Confirmed WAN down removes its ingress/router-originated marks. A voice-only SLA
degradation does not remove inbound sessions on a reachable WAN. Healthy WANs and
separate LAN/management access remain.

Status includes `conntrack_removed` and `last_cleanup.<policy>` with from/to/
removed/uptime_seconds. RouterOS logs `SDWAN conntrack ...` alongside state/route
events, readable through state/decision-log controls.

Removing conntrack does not send TCP RST to both endpoints. Applications may
need reconnection; changing public NAT IP does not seamlessly migrate TCP.

## Compatibility and installation

- Disable FastTrack for managed traffic; preview saves selected original flags.
- Foreign active mark-routing/mark-connection/route and RAW notrack require review,
  not automatic disabling. Owned SD-WAN mangle permits reconfiguration.
- Connection tracking must be enabled (`auto` allowed); explicit disable is rejected.
- Strict rp-filter becomes loose with baseline saved; other values remain.
- Management services, input/forward allowances, DNAT and outbound NAT remain
  existing configuration. Marks fix reply routing, not firewall exposure or CGNAT.
- `sdwan-*` marks/tables, `sdwan-pre`/`sdwan-output`/`sdwan-post` chains,
  `sdwan-local` list and `sdwan:v1:` comments are reserved.

Preview shows mangle, local lists, blackholes and source rules. Installation clears
published state and waits for a fresh report. Failed update/missing API ACK invokes
independent watchdog restore of encrypted backup/files with reboot:
[deployment](DEPLOYMENT.en.md). Baseline rollback removes owned objects and restores flags.

Pre-installation unmarked connections need coordinated migration/reconnection:
automatic cleanup is scoped to owned marks. Assigning a mark does not rewrite
existing NAT binding. Seamless migration of active unmarked/FastTracked sessions
is not implemented.

PCC/weights and QoS remain planned. L3/L4 selectors and optional branch overlay
are implemented, without DPI or full weighted balancing. See
[current candidate acceptance](CURRENT-STATUS.en.md).

LTE uses current dynamic IPv4 and interface gateway for raw-IP or internal lease
gateway for RNDIS. APN controls automatic default; internal DHCP is not edited.
Source pins/scoped conntrack share dynamic-WAN logic. [LTE](LTE.en.md).

## Composite policies

Source/group, destination/group, L3 ingress, protocol and ports use matching
classifier/guard selectors. Private tables have blackhole default254; composite
rules have no broad source-only routing rule. Smaller explicit priority wins,
default last. Selector/group/order edits recreate owned outbound client flows,
preserving incoming WAN API/probes; identical reapply retains clients.
[Policies](POLICIES.en.md).

Runtime reports, credentials and device snapshots remain private.
[Reproduction](TESTING.en.md).

## Policy chains in this branch

Shared prerouting/output/postrouting entry points hand off to SD-WAN. `sdwan-pre`
has one selector `action=jump` per policy (`sdwan:v1:policy-jump:<policy>`) into
`sdwan-p-<policy>`, containing `sdwan:v1:classify:<policy>:<wan>` and its guard.
Connection-mark-to-routing-mark restoration stays shared. No eligible WAN means
guard closes the flow, preserving first-match semantics.

[Mangle reference](https://manual.mikrotik.com/docs/cli-reference/ip/firewall/mangle/)
describes jump-target/return. Actual CHR 7.24.5 checked IP/both Address Lists,
physical/VPN backup, return and independent TCP sessions.
