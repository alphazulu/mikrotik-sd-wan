# Deployment, observation and recovery

[Русский](OPERATIONS.md) | English

A practical workflow for candidate 0.3.0. Check [acceptance status](CURRENT-STATUS.en.md)
before applying and use documentation matching your version. The controller runs
on MikroTik; an external application handles configuration.

## Before installation

1. Read configuration with the wizard. Check identity, RouterOS 7.24.5, API access
   and permissions. Retain the original configuration and a recovery access path.
2. Select WANs, probe targets, internal/branch prefixes and policies. DHCP/PPPoE/LTE
   store type/interface, not temporary provider addresses.
3. Review foreign mangle using the [migration workflow](MIGRATION.en.md). A draft
   can be saved but cannot be installed until conflicts are resolved.
4. For container mode, check packages, device-mode, memory and selected storage.
   Preparation does not format disks. Device-mode flags can require physical
   confirmation; ordinary reboot is not confirmation.
5. Review the change plan. Prevent concurrent device editing during deployment,
   because binary rollback restores the whole snapshot.

## Installation and validation

Use protected GUI/CLI deployment: preparation and backup → local worker → state
checks → confirmation over a fresh API connection → committed. Keep the configurator
open until confirmation. A surviving old connection does not prove that a new
connection can reach the router after routing changes.

After commit, check each policy's selected WAN, fresh probes and SLA. From a
separate client, test ordinary Internet access, a VPN-policy destination and branch
reachability where configured. Check required inbound WAN access and reply symmetry.
The test source must match the policy being tested. The configurator can then close.

The web interface displays RAM snapshots/history; it does not replace a real
client-flow check. Rounded CPU usage, container RSS and whole-router RAM are
different measurements. An unavailable write counter is not a proven zero.

## Expected events

| Event | Expected behavior and check |
|---|---|
| One WAN fails | SLA windows select the next eligible WAN and affected owned connections are removed. Applications reconnect; seamless TCP migration is not promised |
| All permitted WANs fail | The policy closes; return requires fresh probes, recovery windows and hold-down |
| Container stops | RSC fallback continues decisions; web may be unavailable. Inspect API state rather than relying on the page alone |
| GUI closes after commit | Controller operation continues. Closing before ACK can trigger deployment recovery |
| LTE/PPPoE lease or IP changes | Address/gateway are read again and SLA warms up. For LTE inspect APN and dynamic DHCP rather than adding a substitute static address |
| Old web page or API error | Data are stale; the previous healthy result is not current evidence |
| Unavailable/read-only storage | Container preparation is blocked; actual mount, availability and space must be checked |

## Two meanings of rollback

Emergency deployment recovery restores the binary snapshot taken before the last
change and reboots the router. A local watchdog handles errors or missing timely
confirmation. It also undoes unrelated changes made after the backup.

`rollback` / the return-to-baseline action removes project objects and restores
saved baseline flags. It is a different operation, also protected by deployment
recovery. `disable` only freezes the last selection; it is not rollback.
See [deployment and limits](DEPLOYMENT.en.md).

## Export and maintenance

Save diagnostic JSON on the computer. Do not publish real addresses, recovery keys,
backups or credentials. Reboot/configuration changes clear history. Deployment
archives are pruned only by an explicitly enabled policy or maintenance command;
review the dry-run before executing deletion. [Diagnostics](DIAGNOSTICS.en.md) ·
[Archives](MAINTENANCE.en.md) · [Secrets](../SECURITY.en.md).
