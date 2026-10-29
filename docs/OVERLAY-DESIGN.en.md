# Branch overlay implementation notes

[Русский](OVERLAY-DESIGN.md) | English

Status: the first native overlay slice is installed on three CHRs. All four
tunnels and eight OSPF neighbor entries are healthy. A real inner TCP stream
survives WAN failure and failback; all-down activates a remote-LAN blackhole.
The per-router GUI/key workflow is implemented and verified with 5offline and 4live
Windows/Tk checks; see OVERLAY-GUI.md. Subsequent targeted native/rollback/container checks passed; long acceptance
continues. See [current status](CURRENT-STATUS.en.md). This remains unreleased.

## CGNAT and the test fabric

Both branches can be behind CGNAT. Each branch initiates two independent
WireGuard paths to one reachable public MikroTik/CHR hub, with keepalives.
The hub is responder-only. No direct CGNAT-to-CGNAT reachability, relay service
or purchased infrastructure is assumed. Production addressing is still unknown.

`tools/overlay_lab.py --project-root <private project>` manages only its separate
`runtime/overlay-lab` disks, ports, credentials and bootstrap markers. Commands:
`up`, `status`, `baseline`, `keys`, `down`. Do not rerun a pending mutation.
Management/API ports are loopback-only; all five CHR instances use isolated
qcow2 overlays of the pinned official 7.24.5 raw image.

- hub: API 55728, management10.78.0.15, public198.18.100.1/30, WAN ether2.
- sitea: API 55729, management10.78.1.15, WANs100.64.10.2/30 and 100.65.10.2/30,
  LAN 10.201.1.1/24 on ether4.
- siteb: API 55730, management10.78.2.15, WANs100.64.20.2/30 and 100.65.20.2/30,
  LAN 10.201.2.1/24 on ether4.
- nata: API 55731, management10.78.3.15; shared public198.18.100.2 on ether2,
  inside gateways on ether3/4, Internet transit198.18.200.1 on ether5.
- natb: API 55732, management10.78.4.15; shared public198.18.200.2 on ether2,
  inside gateways on ether3/4, default through198.18.200.1.

NAT-A translates only 100.64.0.0/16 and routes NAT-B's public source unchanged.
NAT-B translates100.65.0.0/16. There are no inbound mappings into the branches.
Both providers reach the same hub IPv4; this was verified from all four WANs.
Probe HTTP services58081..58083 are test endpoints, not decision controllers.
NAT-A/B loopback probe IPs198.19.100.1 and 198.19.200.1 DNAT to their QEMU host
service addresses. Host LAN endpoints behind each branch are10.201.N.2.

## Configuration and keys

`sdwan/overlay.py` validates the optional overlay block through the main
JSON validator and native installer. Roles are site
and hub; defaults: MTU 1380, optional MSS clamp off, bounded inner SLA timings.
Each tunnel declares name, underlay WAN, unique local listen port, /30 or /31
local address, peer address, local/peer PUBLIC keys, peer prefixes and OSPF cost.
Sites additionally require endpoint and endpoint_port, with keepalive25 s.
Hubs forbid endpoints/keepalives. Up to16 tunnels per router, no private keys.
Local/remote site prefixes must not overlap; defaults/multicast/loopback/link
prefix overlap and recursive hub endpoints are rejected. Derived local bypass
networks include explicit local/remote site prefixes and tunnel link subnets.

Preparation creates only disabled `sdwan-wg-<name>` interfaces. Ownership comment
is `sdwan:v1:overlay:interface:<name>`. `sdwan/overlay_runtime.py` requests an
explicit public-only API property list, never reads private-key, refuses foreign
name/port collisions and pending deployments, and removes only newly created,
still unused disabled interfaces after a partial API failure. Protected install
must check the current local public key against the declared key; it must never
silently regenerate a lost identity. Existing settings change only in a protected
transaction. All8 lab identities are prepared; public-only exchange file is in
`runtime/overlay-lab/runtime/overlay-public-keys.json` (private lab runtime).

Planned lab links: sitea hub-wan1/2 paired with hub sitea-wan1/2, siteb equivalents.
Site local listen ports51821/22; hub ports51821/22 for A and 51823/24 for B.
Use distinct10.203.N.0/31 link networks, local site .0 and hub .1, unique stable
router IDs in 10.202.0.0/24. Exchange keys from prepared interfaces; never invent
keys or publish router exports. Both branches' peer prefixes cover remote branch
LANs; each hub peer accepts only its corresponding branch LAN and inner peer IP.
Include224.0.0.5/32 in allowed-address for OSPF multicast on each separate interface.

## Native integration constraints

The first overlay milestone added a ninth RSC library. The current standard
package now contains 11RSC+JSON; FILES, SDK payload and recovery archive include
its optional modules. Legacy absence is archived as absence so rollback removes
new files. The constraints below are architectural requirements rather than a
claim that these integration steps still await implementation. Optional helpers
must not be reimported every disabled tick; effective bypass prefixes are shared.

Installer preflight validates all planned objects and ownership before mutations.
Require existing prepared WireGuard interfaces with matching public keys. Keep
foreign OSPF instances/templates/routes intact. Reject a foreign enabled template
that would also match a new WG interface/subnet; keys exist before addresses, so
actual interface/list membership can be inspected safely. Account for built-in
all/static lists and broad network matches. Never auto-migrate legacy OSPF.

Core cleanup currently removes all managed routes/rules/Netwatch objects and
sdwan-* tables not in its wanted sets; dataplane has a separate wanted map for
mangle rules. Overlay must contribute its expected objects or explicitly preserve
its namespace until its own reconciler runs. It must not delete/recreate active
WG interfaces or peers on each apply. Teardown removes only owned objects.

Pin outer UDP using each owned local WG listen port to the configured WAN probe
table, before generic source/router marks and local-net bypass. Preserve ingress
reply symmetry; hub responder replies must use the receiving WAN. Each listener
belongs to its declared WAN. The branch's outer UDP needs appropriate source NAT
on that WAN, including packets whose initial main lookup selected another source.
Revalidate dynamic WAN readiness/bindings and stop stale outer conntrack as needed.

For every inner peer, install a separate `sdwan-ol-<name>` lookup-only table,
a /32 route through that WG interface and a default blackhole. A source/peer
routing rule must precede generic local bypass rules. Inner Netwatch probes bind
to the tunnel's local IP; no alternate tunnel can answer a failed path's SLA.
Use inner RTT/jitter/loss/quorum + physical WAN readiness independently of public
Internet probe quorum. Maintain bounded RAM state, fresh-generation barriers,
fail/recovery windows and hold-down. Administrative drain/down withdraws that
path from overlay admission; do not disable the WG interface solely to drain.

Create one owned OSPFv2 instance/area, default origination NEVER. Redistribute only
connected routes through an output filter that accepts exactly local_prefixes
then rejects everything else. Hub can have an empty local prefix set. Interface
templates only on owned WG interfaces, type ptp, hello1 s/dead4 s, configured costs.
Disable failed templates instead of merely raising their cost: all-bad paths
must withdraw. Modify properties only on actual state transitions, not every tick.
Protect each remote LAN prefix with a high-distance main blackhole; site prefixes
bypass Internet classifiers. Stable inner addressing and conntrack must survive
an outer WAN/OSPF path switch. MSS clamp, when enabled, affects only owned WG
forward TCP SYN traffic and derives from the explicit IPv4 tunnel MTU.

## Acceptance criteria

- Native import/validation, ownership collisions and protected rollback with the
  extra library; key preparation idempotency/public-only inventory.
- Two WAN tunnels per site behind shared CGNAT, authenticated inner SLA, OSPF
  neighbors and only explicit site prefix advertisements; no default/WAN leakage.
- Outer path pinning/source NAT, provider faults/recovery, both down blackholes,
  NAT endpoint changes, dynamic source/address changes and unrelated OSPF scope.
- A real inner TCP stream across site A/hub/site B remains established while
  the outer path changes. Test services may run on the QEMU host; control stays
  on MikroTik. Add a lab-only site-B LAN SNAT if the user-network endpoint needs
  a directly connected source for its return traffic.
- GUI public-key exchange/topology draft and per-node configs, diagnostics,
  bounded optional web telemetry, MTU/MSS checks, actual Rust/native parity.
- Only after final functional code: one48–72h soak, guarded PID/lock/checkpoints;
  no duplicate soak. Then privacy audit, CI/release and reviewed root source sync.

Drain follow-up is implemented: a deliberate drain/down of ALL WANs in the
default policy carries a narrowly derived allow_no_default flag in the protected
deployment journal. Commit additionally requires fresh RouterOS evidence that
all default-policy WANs have admission disabled and a fresh management session.
An unavailable/unverified health state alone does not qualify. Four unit flag
combinations and 3 real single-WAN CHR drain/down/re-enable cases pass, in addition
to6 multi-WAN TCP drain cases. Incoming management and probes stay independent.

## Primary references

- [WireGuard and multi-WAN replies](https://manual.mikrotik.com/docs/virtual-private-networks/wireguard/)
- [OSPF instance](https://manual.mikrotik.com/docs/cli-reference/routing/ospf/instance/)
- [OSPF interface templates](https://manual.mikrotik.com/docs/cli-reference/routing/ospf/interface-template/)
- [OSPF area/redistribution behavior](https://manual.mikrotik.com/docs/user-guides/routing-and-networking-protocols/unicast/ospf/areas-and-virtual-links/)

Docs currently describe7.26; relevant responder/instance/template/filter commands
were separately tested on the isolated7.24.5 hub with disabled temporary objects,
then removed. No existing OSPF objects were changed.

## Verified vertical slice

The main validator, derived bypass objects, native installer/dataplane/controller,
SDK payload upload and recovery manifest now include overlay support. The package
contained 10RSC+JSON at that milestone, including optional VPN egress; the current
standard has 11RSC+JSON. Core cleanup preserves the overlay namespace for module-owned
reconciliation. Initial peer activation happens after outer pinning/NAT/firewall.
A real failed installation restored the encrypted pre-overlay configuration and
removed the formerly absent ninth library. The corrected installation is active
on hub and both sites. Fresh counters are normalized before comparison: RouterOS
nil done-tests before the first Netwatch run otherwise prevents recovery forever.
Native /31 membership also needs a canonical subnet rather than a host-bit prefix.

The four real-TCP acceptance checks cover initial OSPF forwarding, data reception
on the SAME conntrack ID after WAN1 failure, preferred-path failback and all-down
blackhole. Native API blackhole is an empty flag value, not the text true.
The original hardening list covered partial config/peer/endpoint changes and scoped outer
UDP conntrack cleanup, strict native health/key bounds and foreign OSPF/interface
list protection, default-off/disable/re-enable/full rollback, further diagnostics and
new container parity. Subsequent targeted gates are tracked in
[current status](CURRENT-STATUS.en.md); smoke/flow checks alone do not establish release acceptance.


## Windows access to the existing CHR lab

Hyper-V/WSL can reserve Windows TCP ports in the 55728range. Existing Linux/QEMU
API endpoints55728..55732 remain available. For the Windows GUI use the added
loopback aliases45728hub,45729siteA,45730siteB,45731NATA,45732NATB. On a running
fabric, `python3 tools/overlay_lab.py windows-api --project-root PRIVATE_ROOT`
adds/reuses those forwards on the existing NICs. It does not restart guests or
create another fabric. New launches include the aliases automatically.

The isolated QEMU TCP socket links can introduce delayed packet delivery even
with KVM and healthy physical probes. The functional lab explicitly uses a
250 ms inner jitter budget; the product default remains 50 ms. A 90-second
baseline observation with the default budget recorded transient OSPF withdrawals
on all three native routers, including the untouched second branch; Netwatch
reported zero packet loss but jitter above 50 ms. Functional routing tests use
the declared lab budget; strict SLA rejection is tested separately. This does
not justify widening an operator's SLA on a real network.

Outer transport geometry is now tracked in bounded RouterOS RAM. A changed
learned endpoint, parent address/gateway or configured peer/listener retires
only that listener's previous remote UDP tuple in either conntrack direction.
A snapshot of local IPv4 addresses accounts for WireGuard caching another WAN's
socket source before NAT. Stable geometry retains conntrack; inner TCP is never
included in this cleanup. The CHR CGNAT port-change test observed retirement
within 1.444 seconds while the old tuple still had 2m59 s remaining, preserving
another branch's UDP and the same ordinary/private TCP streams. A separate
forced geometry test exercises standby cached-source handling; it is not a
substitute for an actual DHCP change. See [DNS bootstrap](DNS-BOOTSTRAP.en.md) for
hostname endpoints when the ordinary default policy is closed.

### Incomplete address snapshots

An isolated 7.24.5 regression found an existing incoming standby UDP tuple whose
local WAN address was absent from the cached address snapshot. The cached WAN
source was correct; a fresh inventory contained the missing address. The old
retirement helper returned zero. This identifies the failed membership check;
it does not establish when the earlier snapshot became incomplete.

Retirement now combines the previous socket-address snapshot, the previous
resolved WAN source and currently valid local addresses. Previous addresses are
retained when a lease/address has disappeared. Current address flags are read
directly from returned rows; disabled/invalid rows are excluded. Both inventories
are bounded at1024 rows. Unknown geometry, wrong endpoint/ports, invalid cache
types or oversized inventories refuse deletion. The existing exact UDP endpoint
and listener-port filters, including both conntrack directions, remain in place.
The additional inventory read occurs only during retirement; stable transport
geometry performs no extra polling or flash writes. Overlay library revision2
also refreshes the runtime loader after an update.

Run the actual old/new function regression on the owned five-CHR fixture:

```sh
python3 tests/overlay_retirement_cache_acceptance.py \
  --lab-root /srv/sdwan/private/project \
  --previous-source /srv/sdwan/private/previous/native/sdwan-overlay.rsc
```

Fifteen checks pass: the old function reproduces zero removal, the new function
retires the real standby tuple, cache/WAN-hint/current-inventory combinations and
flag/bound checks hold, and primary/SiteB UDP plus ordinary/private TCP survive.
Inventory fault cases replace the function's read expression only; they do not
remove router addresses. The live controller cache/configuration is retained.
The initial test-driver attempt read an unfinished result marker and failed;
the driver now waits for a complete JSON result. Its failed report is retained.
These checks are separate from the native DHCP/PPPoE/rollback/cold-boot suite and
the still-required source-matching long soak.
