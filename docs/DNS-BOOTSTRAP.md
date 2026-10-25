# DNS bootstrap for VPN and overlay WANs

A configured VPN or site overlay may use a hostname for its remote endpoint.
The local RouterOS controller keeps resolving it even when ordinary Internet
SLA closes the default policy, provided at least one declared physical underlay
is administratively enabled and has a usable address/session.

This is a shared control-plane helper in `native/sdwan-dns.rsc`, driven by the
existing controller tick. It does not run another scheduler, external resolver,
or independent client routing policy. Numeric-only VPN/overlay configurations
need no DNS bootstrap routes.

The helper reads existing static and DHCP/PPP-provided IPv4 DNS servers. It
also observes the existing resolver's A/CNAME cache for a configured HTTPS DoH
endpoint, with a bounded alias chain. It keeps the configured DNS servers, DoH
URL, certificates and credentials unchanged. Explicit `@vrf` and IPv6 resolvers
retain operator routing; this IPv4 helper does not create or move VRFs.
Resolvers inside declared local/branch/link networks and the router's own IPv4
addresses retain their normal local routing. A custom forwarder's other upstream
servers require their existing routes; the helper does not discover or rewrite
arbitrary forwarder policies.

At most 32 external IPv4 destinations receive owned, low-priority main-table
`/32` routes (distance 250). Output rules pin ordinary resolver UDP/TCP port 53
and the configured DoH TCP port to a ready physical underlay. Source-bound SLA
probes, incoming replies and PPP transport rules take precedence. Narrow owned
source NAT handles a resolver socket retaining an older local source. Healthy
physical paths are preferred; a ready declared path may bootstrap resolution
while its general Internet targets fail SLA. Drained/down underlays are excluded.

The initial host route is necessary: RouterOS performs the first lookup before
output mangle and routing adjustment. A route mark alone cannot recover a DNS
socket with no initial main route. See the official
[packet flow documentation](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/packet-flow-in-routeros/)
and [DNS resolver documentation](https://manual.mikrotik.com/docs/network-management/dns/).
The implementation is tested against RouterOS 7.24.5; current manuals can describe
newer releases.

A policy's terminal guard drops matching unmarked client packets when no WAN
classifier admits them. Therefore a DNS bootstrap host route cannot reopen a
closed client policy. Router-local destinations, multicast routing protocols
and broadcast control traffic bypass Internet classification before WAN marks;
OSPF and DHCP must continue during a general Internet outage.

The helper stores its geometry signature in RAM and compares owned object
counts. Unchanged geometry performs no configuration/file writes. Configuration,
resolver address/cache, admission or parent changes reconcile only the exact
`sdwan:v1:dns-bootstrap` objects. Disable/removal and protected rollback include
this module and remove its routes, mangle and NAT rules. An oversized source
module is rejected before SDK deployment; split modules stay below the
conservative 60000-byte file-contents budget checked by the bundle builder.

The CHR acceptance `tests/vpn_cold_dns_acceptance.py` withholds external DNS
answers through a real cold reboot, closes ordinary Internet probes, then
allows uncached DNS. It checks VPN resource SLA, actual TCP, OSPF convergence,
blocked client access through a DNS host route and recovery. All five plain-DNS checks pass on CHR. The first cold TCP handshake took
20.388 seconds, within an explicit 60-second cold-start test bound; earlier
20-second test attempts stopped before it completed. This is a measured CHR
result, not a production latency guarantee or a changed SLA threshold. A
passive per-hop trace records SYN retransmissions and eventual established
state. All six DoH-specific CHR checks also pass with a hostname and custom HTTPS
port. Last observed DoH addresses are held in bounded RAM for at most 60 seconds
across short DNS-cache TTL gaps; fresh A data replaces them and a URL change
clears them. The verified DoH run established its first cold TCP in 0.832 s.
The self-signed fixture temporarily disables certificate verification and
restores the original setting; the controller does not change this setting.
