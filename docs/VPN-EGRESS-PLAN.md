# Optional external VPN egress in the existing SD-WAN engine

Status: newly requested by the owner; implementation pending. This extends the
active probes/drain/branch-overlay iteration; it does not cancel that work.
Confirmed protocols: WireGuard and PPP VPN clients (L2TP, SSTP, OpenVPN).
The feature must be disabled by default. Existing configurations keep their
current behavior. No controller or VPN client is added outside MikroTik.

## Required behavior

A policy references an existing MikroTik destination Address List by name.
When a new connection's destination belongs to that list, the policy selects
its first healthy eligible channel: typically VPN1, then another VPN or physical
WAN in the explicitly configured order. Use the existing SLA windows, priorities,
hold-down, per-policy connection marks, per-channel tables and exact conntrack
cleanup. A running interface or a completed handshake alone is insufficient:
probes must verify Internet/representative target-resource access THROUGH that VPN.
After confirmed failure, remove only affected policy/channel conntrack so clients
reconnect through the selected backup. After recovery/hold-down, return to the
preferred VPN. Other policies and private branch-overlay flows must survive.

Address List membership belongs to RouterOS, including dynamic DNS/TTL entries.
Do not copy it into an owned static group, clear its entries or enumerate it on
every control tick. Classify with native dst-address-list matching. An empty list
matches no new sessions; it must not broaden to all traffic. Membership updates
apply to new sessions; established marked sessions retain their binding until
normal expiry or an actual SD-WAN selection change. A policy reference change
participates in the existing selector signature/reclassification mechanism.

Proposed policy selector: `destination_list`, distinct from the current static
`destination_group`. Those two cannot occupy the same mangle dst-address-list
field simultaneously. Existing source/destination CIDR/port/interface conditions
remain conjunctions. Dynamic-list overlap cannot be inferred offline; require
explicit rule priorities where selectors may overlap. The flow explainer must
use a current bounded membership snapshot or report unknown membership, never
pretend an opaque list matches everything. GUI offers existing list names and
allows a future/temporarily empty list reference without creating fake entries.

## Integration constraints

- Use already configured VPN interfaces and existing remote servers. Read only
  the public link/endpoint/routing metadata needed for selection. Never read or
  rewrite VPN passwords, private keys, certificates, server authentication or
  unrelated VPN settings. Provision emulated servers only on CHR for tests.
- Add an opt-in VPN egress model and resolver support without pretending a VPN
  is a static Ethernet gateway. PPP local/peer addresses are live session data;
  do not save lease/session snapshots in user JSON. WireGuard uses its assigned
  IPv4 address and an unambiguous exit peer/allowed-address configuration.
- External full-tunnel exits differ from branch WireGuard links: the latter
  accept only explicit site/link prefixes. Do not silently repurpose an owned
  branch interface as an Internet exit or create recursive parent dependencies.
- Suppress/adopt automatic PPP default routes only with the same captured,
  protected baseline/identity checks used for existing provider clients. They
  must not install an uncontrolled default route around SLA selection.
- Outer transport must stay on physical WANs and cannot recurse into the VPN
  selected for destination traffic. Generic WAN source-pinning can otherwise
  trap a cached WireGuard socket on a failed provider. Reuse the native transport
  pinning/masquerade approach, not a second independent controller. WireGuard
  can match its unique local UDP listen port; PPP transport needs its actual
  remote endpoint/protocol, including L2TP/IPsec IKE/NAT-T when applicable.
- RouterOS-owned DNS Address Lists can maintain transport endpoint FQDNs in RAM;
  do not introduce blocking DNS/HTTP requests into the one-second controller.
  Validate the actual 7.24.5 API/properties and packet flow before choosing the
  final endpoint/route implementation. Avoid claiming dynamic DNS pinning until
  it is tested, including initial lookup when main has no usable default.
- Account for source NAT and existing forward firewall policy on an exit VPN;
  being routable alone does not make client traffic pass. Any owned integration
  must be explicit, narrowly scoped to SD-WAN-selected VPN traffic and previewed;
  preserve unrelated firewall rules. Do not silently override LAN restrictions.
- Existing source-bound probe isolation rejects duplicate local WAN addresses.
  VPN providers may assign identical private addresses to multiple tunnels.
  Investigate/test a scoped VRF option before claiming support; ambiguous probes
  must fail closed rather than escape into another VPN. Avoid silently moving
  active user interfaces to a VRF. RouterOS WG socket VRF and inner routing are
  separate concerns. State actual limitations if such support is not feasible.
- Rust selection remains based on the same native health/admission records;
  native fallback and stale-intent validation must enforce the same decisions.
- No periodic storage writes for health/statistics. Apply configuration once,
  keep live metrics in bounded RAM and change route/rule state only on transitions.

## Acceptance before release

1. Validator/GUI/JSON defaults off, existing configs and static groups unchanged.
2. Use a real existing Address List with static CIDRs plus changing dynamic/TTL
   entries. Matched new flows prefer VPN; unmatched flows use original policy.
3. Per-protocol live CHR tests: WireGuard, L2TP, SSTP and OpenVPN; availability,
   PPP reconnect/address change, provider failover, endpoint changes and recovery.
4. Keep interface/handshake up while blackholing target-resource traffic beyond
   the exit; SLA must switch to the next declared channel and later fail back.
5. Real NAT TCP flows prove only affected policy/channel conntrack is retired;
   unrelated Internet and branch-overlay connections remain established.
6. Outer-packet capture/counters prove physical WAN pinning and no recursive or
   cross-channel health probe escape. All declared backups down must fail closed.
7. Protected scheduler deployment/rollback, ownership collisions, native/Rust
   parity, bounded GUI/optional web diagnostics and resource/flash-write checks.
8. Fold this feature into the final single48–72h soak; do not start an earlier
   version's soak and then treat it as validation of the new VPN code.

Use the existing isolated five-node CGNAT overlay fabric where possible: emulate
an additional external VPN server/Internet exit on the hub using distinct owned
test interfaces/ports/addresses and private runtime credentials. Do not modify
production or existing branch peers. The standalone container lab remains an
independent parity target; never create a duplicate fabric or long-running test.
