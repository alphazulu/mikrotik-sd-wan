# Optional Internet egress through an existing VPN

[Русский](VPN-EGRESS.md)

A VPN is an optional ordinary WAN (`kind=vpn`). The controller runs on MikroTik:
RouterOS RSC or a local Rust container with native SLA and routing. A VPN uses
the same failure/recovery windows, priorities, drain and conntrack cleanup as
other SD-WAN channels. There is no separate controller.

This guide describes the current development branch. Targeted native and container
checks passed within their documented scope; final long-duration acceptance is
still pending. Published v0.2.0 does not include this feature. [Current status](CURRENT-STATUS.en.md)
separates completed checks from pending gates. Original requirements and stages:
[VPN-EGRESS-PLAN.md](VPN-EGRESS-PLAN.en.md).

## GUI setup

1. Configure an existing WireGuard, L2TP, SSTP or OpenVPN client in IP mode.
   Passwords, certificates and keys remain in that MikroTik client.
2. Connect through the API, read settings and configure the physical WANs.
3. In the WAN table choose **Add / configure VPN WAN**. Select an existing client,
   a channel name and the physical WAN order for reaching its server. Adding a
   channel preserves existing policies.
4. Optionally enable NAT and permission for selected forwarded connections on this
   WAN. These options are available for any WAN and default to disabled.
5. Review channel probe targets: they must check representative resources **through
   the VPN**, rather than only its server or handshake. The wizard initially copies
   the first physical WAN's targets; editing preserves the VPN's previous targets.
6. Choose **IP / Address List rule → WAN**. Source and destination independently
   accept any address, IPv4/prefix or a MikroTik Address List. Conditions combine
   with AND. Set SLA, rule priority and the WAN queue, for example
   VPN1 → VPN2 → WAN1 → WAN2. Ports/VLAN selectors are available in the editor.
   The general Internet policy can also prefer a VPN.
7. Review the plan and use protected deployment. Creating or saving JSON in the
   GUI alone does not change router settings.

Rule priority is explicit: lower values are evaluated first. If all its WANs are
unavailable, that policy fails closed; the next policy is not its backup. Declare
backups in the policy's own WAN queue. Changing selectors or rule order recreates
managed outgoing connections; the plan shows this beforehand. Ordinary SLA
switching removes only the previous WAN's affected marks for the relevant policy.

With the container backend, RouterOS checks intent against the current tick's SLA
and priorities. Cached intent selecting a still-healthy backup cannot delay return
to an admitted preferred WAN. Stale `none` cannot close a policy if an eligible
channel exists. Until intent agrees with the current native choice, that native
choice remains effective.

VPN support is optional: omit `kind=vpn` if it is unnecessary. There is no separate
feature switch or policy layer. Use common `admin_state=drain/down` for maintenance.
To remove a channel, first remove policy queue references, then delete the WAN.
The underlying client's settings are retained. Adopted automatic routes remain
suppressed until explicit rollback to the baseline configuration.

The physical-WAN wizard retains existing VPNs and policies when preserving existing
policies and VPN WANs is enabled. Dynamic addresses do not become local subnets or
static lease snapshots. A general policy that already prefers VPN retains its
queue. Removing a physical WAN required by a policy is rejected with an explanation.

## Configuration file

Add these objects to ordinary JSON; referenced WANs and profiles must exist:

```json
{
  "wans": [{
    "name": "vpn1",
    "kind": "vpn",
    "interface": "sstp-existing",
    "vpn_type": "sstp",
    "vpn_endpoint": "exit.example.test",
    "underlays": ["wan1", "wan2"],
    "masquerade": false,
    "allow_selected_forward": false,
    "probe_table": "sdwan-probe-vpn1",
    "icmp_target": "203.0.113.10",
    "probes": [
      {"name": "a", "type": "https-get", "host": "203.0.113.10", "port": 443},
      {"name": "b", "type": "tcp-conn", "host": "198.51.100.10", "port": 443}
    ]
  }],
  "policies": [{
    "name": "vpn-targets",
    "source": "0.0.0.0/0",
    "source_list": "VPN users",
    "destination_list": "VPN destinations",
    "priority": 10,
    "table": "sdwan-vpn-targets",
    "profile": "default",
    "mode": "prefer",
    "wans": ["vpn1", "wan1", "wan2"],
    "allow_degraded": false
  }]
}
```

This fragment is not a standalone configuration. Merge its objects into the
physical WANs and general policy. For L2TP/OpenVPN use `vpn_type` values `l2tp` or
`openvpn`. WireGuard additionally requires the exit peer's public key
`vpn_peer_public_key` and a unique local UDP port `vpn_listen_port`. It must have
exactly one enabled peer allowing `0.0.0.0/0`; a branch peer allowing private
prefixes cannot serve as an Internet exit.

VPN addresses/gateways are not saved in JSON: RouterOS resolves them from the live
session. A VPN references physical underlay WANs only. Cyclic dependencies and a
VPN used as a branch-overlay underlay are rejected.

Existing WireGuard over GRE or another VPN cannot be automatically adopted as a
direct exit over a physical WAN. Nested transports, recursive routes and fixed
source addresses need separate adaptation and validation; this layout is currently
unsupported. Do not bypass validation by declaring a VPN as a static WAN or
removing transport routes.

Legacy `vpn_egress` input remains readable. GUI save or SDK package creation moves
its NAT/firewall flags onto VPN WANs and removes that obsolete block. Explicit WAN
flags take precedence. New files use ordinary `wans` and `policies` only.

## Behavior and limits

New connections use native `src-address-list` and `dst-address-list` matching.
An IP/prefix on one side can combine with a list on the other. Selectors live on
the `jump` into a shared chain for that policy; connection marking and the terminal
`action=drop` for still-unmarked connections live inside it. Static, DNS and timed
entries remain owned by the existing Address List. The controller neither copies
nor refreshes membership in its SLA loop. An empty list does not capture sessions.
RouterOS publishes list changes into the dataplane asynchronously; acceptance
allows short convergence after a membership change.

Membership changes affect new connections. Established connections keep their
mark until ordinary expiry or a policy switch. Failure/recovery removes only
the previous channel's conntrack marks for that policy.

Outer transport is pinned to a physical WAN. WireGuard uses its unique local UDP
port; PPP uses the actual endpoint/protocol. The PPP service rule follows probe
classification so another WAN's probes cannot escape through that underlay.
L2TP accounts for dynamic UDP ports and IPsec ESP/NAT-T. Changing the physical
path reconnects an enabled PPP client.

PPP adoption captures original `add-default-route`; OpenVPN also uses
`route-nopull=yes` so server routes cannot bypass SLA. API preflight and the native
installer reject unadopted dynamic OpenVPN def1 routes (`0.0.0.0/1`, `128.0.0.0/1`);
this exception does not adopt routes from other protocols. Explicit baseline
rollback restores original options after client identity and external-change
checks. Removing a WAN from SD-WAN leaves automatic routes suppressed until that
rollback. Existing authentication settings are unchanged.

Current support targets IPv4 clients in ordinary `main`. Identical local IPv4
addresses on different channels need VRF and are unsupported: probes must fail
closed rather than escape through another channel. L2TP requires
`allow-fast-path=no` before adoption because FastPath bypasses marking, firewall
and connection tracking. The wizard and local validator reject an enabled
FastPath client without changing it automatically. See the official
[FastPath description](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/packet-flow-in-routeros/).
Direct SSTP is supported; HTTP proxy is explicitly rejected. VRF clients and
initial endpoint DNS bootstrap with fully closed `main` need separate acceptance;
support is not claimed.

CHR 7.24.5 validation changed an existing WireGuard endpoint's A record. RouterOS
updated the DNS Address List and current peer address; the shared controller
updated its service route and confirmed resource access. The client's configured
hostname was retained. This establishes no universal DNS refresh interval:
TTL, resolver and client behavior affect it. The [WireGuard reference](https://manual.mikrotik.com/docs/cli-reference/interface/wireguard/peers/)
accepts hostnames but promises no fixed refresh time.

Live states and transport signatures stay in RAM. Normal control ticks do not
write statistics to storage. A bounded Address List snapshot is read only for
wizard name selection or explicit flow explanation. Automatic diagnostics refresh
does not enumerate its members. Exceeding the snapshot budget produces unknown
membership, rather than assuming a match against everything.

## RouterOS documentation

Existing-client semantics and properties are checked against official
[WireGuard](https://manual.mikrotik.com/docs/virtual-private-networks/wireguard/),
[L2TP](https://manual.mikrotik.com/docs/virtual-private-networks/l2tp/),
[SSTP](https://help.mikrotik.com/docs/spaces/ROS/pages/2031645/SSTP) and
[OpenVPN client](https://manual.mikrotik.com/docs/cli-reference/interface/ovpn-client/) documentation.
The online CLI reference describes a newer version; actual acceptance for this
branch targets CHR **7.24.5**.

Validated cases and remaining limits: [VPN-EGRESS-VALIDATION.md](VPN-EGRESS-VALIDATION.en.md).
