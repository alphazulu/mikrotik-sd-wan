# JSON configuration

[Русский](CONFIGURATION.md) | English

One JSON describes WANs, SLAs, policies and backend. The standard bundle contains
11 RSC files and JSON. Generation does not create PPPoE/APN credentials or replace
initial interface, NAT or baseline firewall setup.

## Top level

| Field | Purpose |
|---|---|
| `schema_version` | Integer `1` |
| `revision` | Nonempty string up to 80 characters for status/deployment confirmation |
| `health` | Intervals, timeouts, quorum and state windows |
| `sla_profiles` | Named RTT, jitter and loss limits |
| `wans` | 1–16 WANs |
| `local_networks` | Internal IPv4 prefixes bypassing Internet classification |
| `policies` | 1–64 policies with exactly one default |
| `takeover_route_comments` | Comments of original default routes eligible for adoption |
| `takeover_rule` | Original routing rule; empty `src-address`/`table` if absent |
| `takeover_routes` | Optional exact selectors for inspected main/default routes |
| `disable_fasttrack` | Optional exact selectors for FastTrack conflicting with policy routing |
| `groups` | Optional address groups for selectors |
| `controller_backend` | Default `routeros`, or `container` |
| `container` | Public local-container settings, without passwords |
| `container.telemetry` | Optional RAM/web module, disabled by default; [settings](STATISTICS.en.md) |
| `maintenance` | Optional `backup_keep` (1–20), pruning completed groups after commit; absent means disabled |
| `overlay` | Optional owned branch paths; [wizard](OVERLAY-GUI.en.md) |
| `vpn_egress` | Legacy-input compatibility; new VPNs are `kind=vpn` in `wans`, without another policy layer; [guide](VPN-EGRESS.en.md) |

Obtain takeover/FastTrack fields with the API wizard, which checks inspected
objects are unchanged. Do not copy their IDs between devices.

## SLA and measurements

```json
{
  "health": {
    "interval_seconds": 5,
    "timeout_ms": 700,
    "packet_count": 20,
    "packet_interval_ms": 25,
    "quorum": 2,
    "fail_windows": 3,
    "recover_windows": 6,
    "hold_down_seconds": 60,
    "stale_seconds": 15
  },
  "sla_profiles": {
    "default": {"rtt_ms": 150, "jitter_ms": 30, "loss_percent": 2},
    "voice": {"rtt_ms": 80, "jitter_ms": 15, "loss_percent": 1}
  }
}
```

This is a fragment, not complete installer input. ICMP train plus timeout must
fit the interval; `stale_seconds` covers at least two intervals. Quorum cannot
exceed distinct targets per WAN. Select independent targets reachable through
the WAN being checked. Dynamic WANs stay closed until address and fresh SLA exist.

## WANs

Common fields: `name`, `interface`, unique `sdwan-*` `probe_table`, IPv4
`icmp_target`, and `probes`. Static WANs add `address` without prefix length and
`gateway`; omitted `kind` means static for compatibility.

DHCP/PPPoE use an existing logical interface, without lease snapshots in
`address/gateway`. LTE also needs `apn_profile`, using the current session address
and an interface-bound gateway. See [dynamic WANs](DYNAMIC-WAN.en.md) and
[LTE](LTE.en.md).

VPN WANs use an existing client, `vpn_type`, endpoint and ordered physical
`underlays`: [VPN guide](VPN-EGRESS.en.md). That guide also covers common
`admin_state`, `drain_timeout_seconds`, `masquerade` and `allow_selected_forward`;
the last two permissions default to disabled.

Probes support `http-get`, `https-get`, `tcp-conn` with `host/port`, and `dns` with
`host/dns_server`. Names allow dots, hyphens and underscores. Duplicating a target
does not increase quorum. Probes are pinned to their WAN and must not silently
escape through a backup provider.

## Policies

Default uses `source=""`, `table="main"`, without extra selectors. Private policies
use their own `sdwan-*` table. A destination-only rule uses `source="0.0.0.0/0"`;
specific clients use an IPv4/subnet or Address List. Common fields are `name`,
`profile`, `mode`, ordered `wans`, and `allow_degraded`.

- `prefer` selects the first eligible WAN in its list.
- `strict` permits exactly one WAN and closes when it is unavailable.
- `allow_degraded` explicitly permits SLA-violating WANs when none is healthy.

Groups, destination, L3 interface, protocol, ports, priorities and intersections:
[policies](POLICIES.en.md), [example](../config/examples/clients-applications.json).

Unchanged reapply retains flows. Changing classifier/groups/order reclassifies
owned outbound connections. WAN changes remove affected owned conntrack entries;
incoming WAN traffic and probes have separate exemptions.

## Examples and validation

- [sdwan.json](../config/sdwan.json): complete CHR lab configuration.
- [clients-applications.json](../config/examples/clients-applications.json): groups/composite policies.
- [container.json](../config/examples/container.json): local Rust mode/management bypass.

```sh
python3 sdwan.py --config config/sdwan.json validate
python3 sdwan.py --config config/sdwan.json bundle --output build/native
```

Names/keys are strict; unknown fields are rejected. Exact contracts:
[config.py](../sdwan/config.py), [policies.py](../sdwan/policies.py),
[container_config.py](../sdwan/container_config.py). Store actual credentials and
discovered configurations locally according to [secret handling](../SECURITY.en.md).
