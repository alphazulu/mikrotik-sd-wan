# Client, group and application policies

[Русский](POLICIES.md) | English

WAN selection combines source IPv4/subnet, groups, destinations, ingress
interface/VLAN, protocol and ports. RouterOS handles SLA/switching; GUI edits
declarative JSON and protected worker/watchdog installs it. Published-version
results are [historical](POLICIES-VALIDATION.en.md). This branch adds source and
destination Address Lists and common physical/VPN WANs; full branch acceptance
is still running.

## GUI setup

1. Inspect a device and generate configuration, or open JSON.
2. On address groups, enter a name and comma-separated IPv4 addresses/subnets,
   for clients or service destinations.
3. On clients/applications, use the IP/Address List → WAN rule action. Choose
   source/destination types independently, SLA and ordered physical/VPN WANs.
   Use the general editor for extra selectors: name, source, own `sdwan-*`
   table, SLA, prefer/strict and WAN order, plus group/application fields.
4. For all clients use source `0.0.0.0/0`. Empty source is reserved for default
   with `main`. Source IP/subnet plus group means intersection, not union.
5. Give overlapping rules explicit priorities: smaller is earlier. Up/Down
   reorders and assigns priorities to all private policies; default stays last.
6. Validate and preview. Ambiguous overlaps are rejected; explicitly ordered
   intersections and complete shadowing by one earlier rule are reported.

Rule conditions combine with **AND**; members within one address group use **OR**.
First match wins. WAN failure does not fall through to another policy; backup
comes only from that policy's WAN list. Strict allows exactly one WAN.

Group/selector/order changes recreate owned outbound client sessions for new
classification. Incoming WAN management/probes remain. Identical reapply preserves
sessions; normal SLA failover/failback cleans only affected policy/WAN marks.

## JSON

Optional top-level groups:

```json
"groups": {
  "phones": ["192.168.50.101/32", "192.168.50.102/32"],
  "voice-services": ["203.0.113.0/24"]
}
```

Additional policy:

```json
{
  "name": "voice-app",
  "source": "0.0.0.0/0",
  "source_group": "phones",
  "destination_group": "voice-services",
  "in_interface": "vlan-voice",
  "protocol": "udp",
  "dst_ports": "5060,10000-20000",
  "priority": 10,
  "table": "sdwan-voice-app",
  "profile": "voice",
  "mode": "prefer",
  "wans": ["wan1", "wan2"],
  "allow_degraded": false
}
```

These are fragments. VLANs, addresses, NAT and needed firewall allowances must
already exist. `in_interface` is actual RouterOS L3 ingress, not VLAN number or
a physical bridge port. `wans` uses JSON WAN names, such as wan1, not interface names.

| Policy field | Meaning |
|---|---|
| source | IPv4/subnet; `0.0.0.0/0` matches any source; empty only for default |
| source_group / destination_group | Declared group name; empty means unrestricted |
| destination | Destination IPv4/subnet, intersected with destination_group |
| source_list / destination_list | Existing/future MikroTik Address List; empty unrestricted. A side cannot use both group and external list |
| in_interface | Existing logical interface, including VLAN; empty any client ingress |
| protocol | any / tcp / udp / icmp, omitted means any |
| src_ports / dst_ports | Ports/ranges such as `80,443,10000-20000`; TCP/UDP only |
| priority | Unique integer 1..999999, smaller first; required for all overlapping private rules |

Limits: 64 policies, 64 groups, 256 nonoverlapping members per group, 15
nonoverlapping entries per port list in 1..65535. Source/destination selectors
are IPv4, not FQDN or nested groups. Old JSON remains compatible; prior disjoint
source policies retain order.

## RouterOS and limits

Groups become owned `sdwan-group-*` lists. Classifier and fail-closed guard use
the same selectors. Composite policies have no broad source-only routing rule
that could bypass port/destination restrictions. Policy tables have blackhole
default distance254 so closed paths cannot escape through main/default. Editing
removes old matcher constraints.

Application names are administrator descriptions, not DPI. Classification uses
addresses/protocols/ports, not detection inside encrypted HTTPS. Administrators
maintain service address sets.

Rules classify outbound client flows. Incoming WAN/DNAT, related replies, health
probes and `local_networks` retain exemptions. Existing [OSPF/VPN](OSPF.en.md)
requires review; foreign-mark guards remain. Internet policies do not automatically
protect unknown branch prefixes.

Runtime reports, credentials and device snapshots stay private.
[Reproduction](TESTING.en.md).

## IP and Address Lists in one policy

An IP without prefix length, such as `192.168.50.101`, is saved as `/32`. Source
and destination independently support IPv4/subnet or Address List:

```json
{
  "name": "selected-users-services",
  "source": "0.0.0.0/0",
  "source_list": "Selected users",
  "destination_list": "Selected services",
  "priority": 10,
  "table": "sdwan-selected-services",
  "profile": "default",
  "mode": "prefer",
  "wans": ["vpn1", "wan2", "wan1"],
  "allow_degraded": false
}
```

This requires source in `Selected users` AND destination in `Selected services`.
Omit `destination_list` for source-only rules. For a destination list and one
client, put its IP in `source` instead of `source_list`. Firewall reads lists
directly, including DNS/temporary entries. Controller does not manage membership;
empty lists match nothing. Membership changes affect new connections; marked
sessions retain their route until switching/end. Diagnostics without a membership
snapshot reports an unknown match.

Each policy has one selector `jump` in `sdwan-pre`. Its `sdwan-p-<name>` target
contains WAN classifiers and a terminal `drop` for unmarked flows, making policy
order readable without repeating selectors on every WAN.
