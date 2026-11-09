# Applying configuration while preserving unaffected connections

[Русский](LIVE-CONFIGURATION.md) | English

The standard GUI/CLI retain protected installation with backup, scheduler and a
RouterOS watchdog. The new `sdwan-config-state.rsc` module identifies affected
WANs, probes, SLA profiles and connections. Decisions remain on MikroTik; no
external controller is required.

## Preserved state

A successful update retains SLA state and counters for unaffected profile/WAN
pairs. Unchanged Netwatch probes keep their IDs and completed-test counters.
Reapplying the same configuration also repairs a disabled owned probe. Identical
Netwatch setters retain counters on the tested RouterOS version. An uninstall,
missing controller or disabled controller scheduler starts fresh SLA admission;
old RAM state cannot qualify a reinstall.

Revision changes, WAN JSON ordering and administrative-state changes do not
restart the health warm-up of every channel.

SLA limits are compared at the controller's actual precision: microseconds for
RTT/jitter and hundredths of a percent for loss. For example, `150` and `150.0`
are the same limit and do not require a new profile warm-up.

An established connection survives when the new configuration still admits its
previous policy and path. This also applies to marked VPN-WAN flows; transport
support and initial tunnel setup are unchanged.

## Changes requiring revalidation

- WAN kind, address, gateway, interface or transport parameters: affected
  bindings and that WAN's probe generation are revalidated. A new source needs
  fresh tests; connections on other WANs remain intact.
- Probe membership, targets or expectations: an old result cannot establish
  access to a new resource. Other channels retain their current evidence.
- A specific SLA profile's limits: only that profile's state changes. Shared
  measurement or hysteresis settings affect every WAN using them.
- Policy selectors, groups or order: conntrack is reconsidered using original
  connection tuples. IPs/prefixes, Address Lists, protocol and ports are checked;
  flows needing different classification are retired. Disjoint clients and
  still-eligible default-policy flows are preserved.

Changing an external Address List's membership alone affects new-flow
classification. Existing marked flows retain affinity; a later unrelated
policy edit must not silently cancel that behavior.

Conntrack does not expose every original packet property. When an edited input-
interface condition cannot be proved from its existing admission, potentially
affected flows are handled conservatively. Foreign marks, ingress replies and
service probes are not included in a blanket client-flow reset. Ordinary
retirement of connections on an unavailable WAN still applies.

## HTTP evidence and upgrades

Async HTTP jobs and results are tied to the exact probe parameters, source,
gateway, Netwatch ID and job token. Changed jobs are cancelled; unchanged jobs
retain their next-run deadlines. A late old response cannot qualify a new probe.

On upgrade, legacy evidence is adopted before replacing live callbacks, only
when the full old configuration signature and original source, gateway,
generation and probe-ID checks agree. A finishing old worker is supported too.
Insufficient proof requires fresh evidence. Results and bookkeeping remain in
RAM; no periodic flash writes were added for this state.

## Installation and limits

Use the complete new package: **13 RSC files and JSON**. GUI/CLI archive the new
module, or record its prior absence, before payload upload. A failed update
restores the previous package. Do not mix module versions.

Protected configuration rollback retains the existing recovery mechanism and
may require rebooting. Session retention during a successful update does not
promise survival through that rollback. Changed NAT addresses or excluded paths
also do not transfer an existing session to a different public IP.

Rule application is not a system-wide atomic operation. Session preservation
requires the same conntrack IDs/tuples and advancing TCP/UDP exchanges; `selected`
alone is insufficient. This does not promise zero packet loss or a universal
reconfiguration-time bound.

[Validation](LIVE-CONFIGURATION-VALIDATION.en.md) ·
[Protected deployment](DEPLOYMENT.en.md) · [Policies](POLICIES.en.md)

Official references: [Netwatch](https://manual.mikrotik.com/docs/diagnostics-monitoring-and-troubleshooting/netwatch/),
[script identifiers and types](https://manual.mikrotik.com/docs/developer-guides/scripting/scripting-tips-and-tricks/).
The current manual describes 7.26; project behavior is checked separately on 7.24.5.
