# LTE/APN implementation

[Русский](LTE-IMPLEMENTATION.md) | English

Controller, installer, rollback, API discovery and GUI support `kind=lte`.
See the [user guide](LTE.en.md). Production MikroTik was unchanged; existing
OSPF/VPN needs [separate review](OSPF.en.md).

## Contract and API

`sdwan/wan.py` and `sdwan/config.py` accept static/dhcp/pppoe/lte. LTE requires
logical interface and already assigned `apn_profile`; address/gateway snapshots
are rejected. Discovery reads only allowed interface/APN fields, without
credentials, PIN or SIM identifiers. GUI displays current address/profile;
export stores only the profile reference. Enabled, unregistered LTE can be selected.

`sdwan/lte.py` requires one routed IPv4 APN, matching profile and no passthrough.
Shared profiles require all users, including disabled interfaces, to be managed
together. Unknown routing flags or denied reads are not treated as safe defaults.

## RouterOS

Functions live in existing `native/sdwan-links.rsc`; original LTE used library
revision 4. The current standard bundle has 11 RSC files and JSON. The production
reader first checks target 7.24.5 `apn-profiles`, then newer singular `apn-profile`.
`sdwanLTENormalizeProfiles` preserves native arrays and normalizes names/IDs.

Resolver requires enabled/running LTE, correct APN without automatic default and
one assigned dynamic IPv4. Source is the current address. Raw-IP uses LTE interface
gateway; RNDIS/HiLink uses the interface-pinned gateway from its internal bound
DHCP lease. Disconnect/new-IP reconciles bindings, source pins, routes and
Netwatch. Old metrics cannot reopen WAN; return needs fresh probe generations,
recovery windows and hold-down. Conntrack cleanup stays scoped to affected marks.

Installer treats LTE separately from DHCP/PPPoE. `sdwanLTEAPNCapture` checks
ownership and saves routing metadata without credentials. `backup.lte_apns` has
one original record per profile; baseline is persisted before `sdwanLTEAPNApply`.
Mutation requires exact identity/current flag. Already-disabled automatic default
avoids a setter. Reapply preserves original baseline. Retired APNs keep default
disabled until explicit baseline rollback.

`sdwanLTEAPNRestore` restores only owned `add-default-route`, checking identity,
managed value and absence of new unselected users. Manual changes are warned
and skipped. Distance, DNS, provider APN, authentication, SIM and credentials
are unchanged. RouterOS hides distance while automatic default is off; its stored
value is retained without writing a guessed distance. Emergency watchdog uses
full binary restore/reboot: [deployment](DEPLOYMENT.en.md).

## Validation

`tests/lte_apn_acceptance.py` uses the actual CHR APN menu. Original tests
`tests/lte_native_acceptance.py`, `tests/lte_acceptance.py` and
`tests/lte_protection_acceptance.py` cover resolver, traffic, SLA failover,
reconnection, baseline and emergency restore. Only that fixture replaces LTE
inventory reads; a real PPP point-to-point data plane and actual APN/RouterOS
controller execute. USB RNDIS was subsequently checked separately on x86.
There is no production test mode. Physical modem/SIM/radio registration needs
hardware acceptance.

Original sequential LTE regression passed 109 units and 105 CHR checks:
[historical report](LTE-VALIDATION.en.md), private `runtime/lte-final-validation.json`
and `runtime/lte-regression-suites.json`. [Current status](CURRENT-STATUS.en.md)
is separate. Detailed private logs/device snapshots are not distributed.

## References

- [LTE/5G](https://manual.mikrotik.com/docs/mobile-networking/lte-5g/): APN routing, routed/passthrough.
- [APN CLI](https://manual.mikrotik.com/docs/cli-reference/interface/lte/apn/): routing options menu.
- [LTE CLI](https://manual.mikrotik.com/docs/cli-reference/interface/lte/): newer profile fields; target 7.24.5 checked separately.
- [Default configurations](https://manual.mikrotik.com/docs/getting-started/configuration-management/default-configurations/): LTE interface gateway.

Local runtime reports, credentials and device snapshots remain private.
[Reproduction](TESTING.en.md).
