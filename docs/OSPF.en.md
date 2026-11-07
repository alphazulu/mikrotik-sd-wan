# OSPF and VPN compatibility

[Русский](OSPF.md) | English

SD-WAN selects Internet WANs and manages its own tables/marks. It does not
automatically migrate arbitrary existing OSPF neighbors, VPN tunnels,
redistribution or remote branches. The optional [branch overlay](OVERLAY-GUI.en.md)
creates its own WireGuard/OSPF objects and must be explicitly enabled. Universal
automatic migration of existing routing is not implemented.

## Internal and branch networks

List every internal prefix that must bypass Internet classification in
`local_networks`: LANs, branches, VPNs and the container network. Synthetic example:

```json
{"local_networks": ["10.10.0.0/16", "10.20.0.0/16", "172.31.255.0/30"]}
```

The field does not create routes or establish reachability. OSPF/static routes
must exist in the required table. Exemption before marking lets ordinary internal
traffic use `main`. Do not enter `0.0.0.0/0` or assume automatic updates from OSPF.

## Third-party marks and tables

The wizard rejects conflicting foreign `mark-connection`, `mark-routing` and
`notrack` configuration. This protects existing flows against takeover by new
rules. Do not remove the guard to bypass an error: review exemptions, mangle
order and tables separately, then reproduce the topology on CHR.

VRFs, overlapping WAN subnets and custom policy routing need separate design.
`lookup-only-in-table` and strict-policy blackholes must not block necessary
branch networks. Those need a classification bypass or an explicitly designed route.

## Default routes and tunnels

Default redistribution into OSPF, originate-default and its cost are not
automatically synchronized with SD-WAN. Define what branches receive after total
WAN failure and when hub reachability changes.

A tunnel with a fixed source IP does not move to another WAN merely because the
default route changes. Suitable endpoints, NAT/firewall and tunnel recovery are
required. LTE behind CGNAT can provide outbound access while inbound remains
unavailable.

Before installation, test a copy of the topology: branch reachability with normal
and client policies, reply symmetry, tunnel recovery, OSPF adjacency and total WAN
failure. A binary backup does not replace migration design.
