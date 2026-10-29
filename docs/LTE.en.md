# LTE WAN with an existing APN

[Русский](LTE.md) | English

Native LTE is supported by RouterOS controller, installer and GUI. The original
milestone passed 109 units, 105 CHR checks, Windows GUI and clean-state audit:
[historical results](LTE-VALIDATION.en.md). Each WAN uses one routed IPv4 APN.
For RNDIS/HiLink, RouterOS also creates an internal dynamic DHCP client; SD-WAN
reads its gateway while still managing automatic-default settings through APN.

## GUI setup

1. Start `Configure-SD-WAN.cmd`, connect to API and read settings.
2. Select primary and LTE interfaces, for example `wan-primary` priority 1 and
   `lte-backup` priority 2.
3. The wizard displays LTE type, assigned APN and current IP. APN/runtime addresses
   are read-only there; use RouterOS tools to change provider profiles. The editor
   references the already assigned profile so later replacement can be detected.
4. Set targets, SLA and client policies. Preview shows that installation saves
   original APN routing flags and disables automatic default for SLA routing.
5. Run protected installation. Standard bundle is JSON plus 11 RSC files; the
   external GUI is no longer required afterward.

LTE interface/APN and required NAT must already exist. The configurator does not
create provider credentials or change PIN, SIM, operator or radio mode. Temporarily
absent data sessions are allowed; WAN remains unavailable until IPv4 and fresh SLA exist.

**DNS before installation.** RouterOS 7.24.5 returns `Can't use DNS without route!`
when disabling APN automatic default with `use-peer-dns=yes`. Configure explicit
router DNS and disable selected APN peer DNS with RouterOS tools first, then
read settings again. Configurator/native installer check this before adoption.
They do not silently disable DNS or persist dynamic DNS addresses. Unknown peer-DNS
flag also blocks installation.

**Existing OSPF/VPN needs migration review.** Foreign connection/routing-mark
guards remain; LTE support does not bypass [compatibility checks](OSPF.en.md).

## JSON fields

LTE uses common name/probe-table/ICMP/application targets plus:

```json
{
  "kind": "lte",
  "interface": "lte1",
  "apn_profile": "default"
}
```

This is a WAN fragment, not complete JSON. Omit `address`/`gateway`; LTE snapshots
are rejected. `apn_profile` is the assigned profile name, not provider APN text
or password, and must match the interface assignment.

## Routes and reconnection

- Source is assigned dynamic IPv4. Raw-IP uses LTE interface gateway; RNDIS/HiLink
  uses current internal bound-DHCP gateway pinned as `IP%interface@main`. Probes
  and replies use that WAN table. Missing/ambiguous leases close the WAN rather
  than guessing a gateway. This reflects the [interface-gateway limitation](https://help.mikrotik.com/docs/spaces/ROS/pages/328084/IP+Routing):
  on a broadcast link it ARPs for the destination itself and suits only directly
  connected destinations. APN behavior is in [LTE/5G](https://manual.mikrotik.com/docs/mobile-networking/lte-5g/).
  Peer-DNS/default conflict above was checked separately on 7.24.5 x86.
- APN `add-default-route` is disabled so main cannot bypass SLA. WAN priority is
  policy order, not rewritten APN distance.
- Installer saves APN baseline before mutation; already-disabled default avoids
  a setter. Reapply preserves original baseline rather than adopting managed state.
- Disconnect/new-IP updates source bindings/routes and removes affected sessions,
  then waits for fresh probe generation, recovery and hold-down. Other policies
  and inbound API through healthy WANs remain.
- Unexpected APN replacement or automatic-default return closes LTE. Controller
  does not start changing another profile without coordinated redeployment.
- LTE is backup when later in prefer order; each client can have its own order
  or strict LTE.

RouterOS hides distance while default is off, including native get, but retains
its internal value. Code does not write distance back; CHR checked 77→no→yes→77.

## Shared profiles and rollback

One shared profile among selected LTE interfaces has one baseline. Any unselected
user, even disabled, blocks installation because changing it affects another WAN.
Use a separate profile or include all its users in coordinated configuration.

Baseline rollback restores only the modified routing flag with matching identity
and managed value. Manual edits/new unmanaged shared-profile users are preserved.
Retired profiles keep automatic default disabled until explicit baseline rollback.
Emergency worker/watchdog restores full encrypted binary backup/files and reboots,
including APN configuration.

## Limits

- Native routed IPv4 and one APN per logical LTE interface. Old multi-APN and
  passthrough are rejected to avoid arbitrary source selection.
- An external modem presented as ordinary Ethernet is DHCP WAN. USB RNDIS shown
  under `/interface/lte` remains LTE; its internal dynamic DHCP client is not
  edited. User-created static DHCP on the same LTE interface is a conflict.
- Inbound connections require actual provider reachability. SD-WAN does not
  remove CGNAT or open firewall ports.
- Internet WAN switching does not move GRE/IPIP/EoIP with a fixed primary-provider IP to LTE.
  Branch tunnel backup requires coordinated overlay design.

Original CHR checks used actual APN/data plane with a test-only PPP point-to-point
LTE inventory adapter. USB RNDIS was subsequently checked on x86. Neither proves
SIM/radio/firmware behavior or a specific physical modem. Production has no test
mode. [Current candidate status](CURRENT-STATUS.en.md).

## MikroTik documentation

- [LTE/5G](https://manual.mikrotik.com/docs/mobile-networking/lte-5g/): APN routing/profiles, routed/passthrough.
- [Default configurations](https://manual.mikrotik.com/docs/getting-started/configuration-management/default-configurations/): LTE gateway lte1.
- [IP route](https://manual.mikrotik.com/docs/cli-reference/ip/route/): dynamic modem route flag.

Runtime reports, credentials and device snapshots remain private.
[Reproduction](TESTING.en.md).
