# Branch overlay implementation notes

Status: the first native overlay slice is installed on three CHRs. All four
tunnels and eight OSPF neighbor entries are healthy. A real inner TCP stream
survives WAN failure and failback; all-down activates a remote-LAN blackhole.
The per-router GUI/key workflow is implemented and verified with5offline and4live
Windows/Tk checks; see OVERLAY-GUI.md. Further ownership/rollback hardening and
full acceptance remain in progress. This is an unreleased implementation checkpoint.

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

- hub: API55728, management10.78.0.15, public198.18.100.1/30, WAN ether2.
- sitea: API55729, management10.78.1.15, WANs100.64.10.2/30 and100.65.10.2/30,
  LAN10.201.1.1/24 on ether4.
- siteb: API55730, management10.78.2.15, WANs100.64.20.2/30 and100.65.20.2/30,
  LAN10.201.2.1/24 on ether4.
- nata: API55731, management10.78.3.15; shared public198.18.100.2 on ether2,
  inside gateways on ether3/4, Internet transit198.18.200.1 on ether5.
- natb: API55732, management10.78.4.15; shared public198.18.200.2 on ether2,
  inside gateways on ether3/4, default through198.18.200.1.

NAT-A translates only100.64.0.0/16 and routes NAT-B's public source unchanged.
NAT-B translates100.65.0.0/16. There are no inbound mappings into the branches.
Both providers reach the same hub IPv4; this was verified from all four WANs.
Probe HTTP services58081..58083 are test endpoints, not decision controllers.
NAT-A/B loopback probe IPs198.19.100.1 and198.19.200.1 DNAT to their QEMU host
service addresses. Host LAN endpoints behind each branch are10.201.N.2.

## Configuration and keys

`sdwan/overlay.py` validates the optional overlay block through the main
JSON validator and native installer. Roles are site
and hub; defaults: MTU1380, optional MSS clamp off, bounded inner SLA timings.
Each tunnel declares name, underlay WAN, unique local listen port, /30 or /31
local address, peer address, local/peer PUBLIC keys, peer prefixes and OSPF cost.
Sites additionally require endpoint and endpoint_port, with keepalive25s.
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
Site local listen ports51821/22; hub ports51821/22 for A and51823/24 for B.
Use distinct10.203.N.0/31 link networks, local site .0 and hub .1, unique stable
router IDs in10.202.0.0/24. Exchange keys from prepared interfaces; never invent
keys or publish router exports. Both branches' peer prefixes cover remote branch
LANs; each hub peer accepts only its corresponding branch LAN and inner peer IP.
Include224.0.0.5/32 in allowed-address for OSPF multicast on each separate interface.

## Native integration and remaining hardening

The ninth RSC library `native/sdwan-overlay.rsc` now exists; links.rsc is ~50KB.
Add it to FILES/bundle, SDK payload upload allowlist and native recovery archive.
A new file absent from a legacy installation must be archived as absent, so
recovery removes it. Review hardcoded package size/minimum manifest checks and
GUI tests (currently9 files =8RSC+JSON). An updated package becomes10 files.
Avoid importing optional overlay helpers on every tick when the feature is off.
Controller and native installer must use the same effective bypass prefixes.

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
templates only on owned WG interfaces, typeptp, hello1s/dead4s, configured costs.
Disable failed templates instead of merely raising their cost: all-bad paths
must withdraw. Modify properties only on actual state transitions, not every tick.
Protect each remote LAN prefix with a high-distance main blackhole; site prefixes
bypass Internet classifiers. Stable inner addressing and conntrack must survive
an outer WAN/OSPF path switch. MSS clamp, when enabled, affects only owned WG
forward TCP SYN traffic and derives from the explicit IPv4 tunnel MTU.

## Required checks and remaining work

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
combinations and3 real single-WAN CHR drain/down/re-enable cases pass, in addition
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
contains10RSC+JSON including optional VPN egress. Core cleanup preserves the overlay namespace for module-owned
reconciliation. Initial peer activation happens after outer pinning/NAT/firewall.
A real failed installation restored the encrypted pre-overlay configuration and
removed the formerly absent ninth library. The corrected installation is active
on hub and both sites. Fresh counters are normalized before comparison: RouterOS
nil done-tests before the first Netwatch run otherwise prevents recovery forever.
Native /31 membership also needs a canonical subnet rather than a host-bit prefix.

The four real-TCP acceptance checks cover initial OSPF forwarding, data reception
on the SAME conntrack ID after WAN1 failure, preferred-path failback and all-down
blackhole. Native API blackhole is an empty flag value, not the text true.
Further required hardening: partial config/peer/endpoint changes and scoped outer
UDP conntrack cleanup, strict native health/key bounds and foreign OSPF/interface
list protection, default-off/disable/re-enable/full rollback, further diagnostics and
new container parity. Do not treat the smoke/flow checks as full release acceptance.


## Windows access to the existing CHR lab

Hyper-V/WSL can reserve Windows TCP ports in the55728range. Existing Linux/QEMU
API endpoints55728..55732 remain available. For the Windows GUI use the added
loopback aliases45728hub,45729siteA,45730siteB,45731NATA,45732NATB. On a running
fabric, `python tools/overlay_lab.py windows-api --project-root PRIVATE_ROOT`
adds/reuses those forwards on the existing NICs. It does not restart guests or
create another fabric. New launches include the aliases automatically.
