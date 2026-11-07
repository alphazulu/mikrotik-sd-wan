# LTE/APN acceptance

[Русский](LTE-VALIDATION.md)

Historical LTE results follow. Groups/applications and diagnostics were added
later; their regression is [POLICIES-VALIDATION.md](POLICIES-VALIDATION.en.md).
Current gates: [CURRENT-STATUS.md](CURRENT-STATUS.en.md). File counts and cleanup
state below describe their respective historical runs.

Iteration completed: **109 units, 105 CHR checks and four Windows GUI suites PASS**.
Summary: `runtime/lte-final-validation.json`; audit:
`runtime/lte-final-clean-state.json`. All 13 sequential suites exited 0.
UTC: 2026-10-23T18:44:57.324800+00:00.

## Fixture and scope

Five CHR RouterOS 7.24.5 nodes: edge, three ISPs and client. Local RouterOS
scripts/scheduler control routing; Python performs deployment, GUI and tests.
Production MikroTik was neither connected nor changed.

The APN menu/settings are real. CHR has no LTE radio. The LTE test package replaces
only the LTE inventory reader, using data from a real PPP point-to-point link.
Routes, probes, marks, NAT, API and controller run on CHR. The production reader
is restored afterwards; there is no production test mode. This does not validate
SIM, radio registration, driver/firmware or compatibility with a particular modem.

## LTE checks

| Suite | Checks | Scope |
|---|---:|---|
| LTE APN | 6 | Read-only capture, disable automatic default, preserve distance/DNS/authentication, baseline rollback, original add=no, manual drift, deleted profile |
| Native LTE resolver | 7 | APN name/ID arrays, live dynamic IPv4/interface gateway, APN drift, default adoption, disconnect/new-IP, shared disabled unselected modem |
| LTE lifecycle | 10 | Install without data session, reapply, ingress/DNAT, three TCP/NAT streams, silent failover/failback, scoped CT, new-IP/fresh SLA, APN drift, reboot, baseline |
| LTE protection | 4 | One baseline for shared APN, reapply, original add=yes/distance, injected worker failure after APN mutation and full binary restore/reboot |

Reports: `runtime/lte-apn-acceptance.json`, `runtime/lte-native-acceptance.json`,
`runtime/lte-acceptance.json`, `runtime/lte-protection-acceptance.json`.
109 units passed, including previous static/DHCP/PPP and new LTE contracts.

## General regression and GUI

The general matrix includes mixed static/DHCP/PPP lifecycle, provider protection,
resolver/reconciler, protected deployment, deployment/legacy, native SLA faults,
connections, wizard and 14 base checks. Fault suites run sequentially, without
parallel fixture mutation. Execution summary: `runtime/lte-regression-suites.json`.

Windows GUI is checked separately: LTE with APN and nine-file export on saved CHR
inventory with an LTE adapter; mixed WAN through real native API; static wizard
through API; six offline Create configuration cases on saved inventory without
accessing production.

The first two mixed-lifecycle runs stopped on DHCP-stream preservation during
PPP reconnect. The observer captured an independent voice jitter SLA violation:
20–48 ms against a 15 ms threshold, then normal client102 switching and conntrack
cleanup. This does not prove removal of unrelated marks. The session-lifecycle
test config uses 100 ms jitter to isolate that scenario. `config/sdwan.json`, the
production controller and separate native SLA fault tests retain original strict
thresholds. Evidence: `runtime/lte-mixed-failure-evidence.json` and two preserved
observer files.

## Open scope at that stage

Migrating existing OSPF/VPN policies and protecting branch prefixes need
[separate review](OSPF.en.md). Foreign-mark guards remain; current draft/deployment
handling is described in [MIGRATION.md](MIGRATION.en.md). LTE Internet failover alone
does not establish failover for fixed-source GRE/IPIP/EoIP, WireGuard endpoints
or reachability through CGNAT. Hardware, load and long-duration acceptance are
separate project stages.

## Additional USB RNDIS acceptance, 26 October 2026

A separate x86 L6 RouterOS 7.24.5 ran 12 checks from
`tests/lte_rndis_acceptance.py --lab-root <private-lab-root> --phase all`.
USB RNDIS through usbredir provides a real `/interface/lte`, with no inventory
substitution. Radio and SIM remain emulated; this is not a mobile operator's modem
qualification.

Both local controllers were tested: RSC and exact CI base-amd64 scratch image
`a98ff28196c2ac187d89a285c511f99faa128c3279fe0fd6ef06d219231e677e`.
RNDIS uses its live internal DHCP gateway; automatic default is controlled through
APN. Lease address/gateway are not persisted in config.

- Actual TCP/NAT streams fail over after confirmed emulator frame blocking and
  return to LTE after fresh SLA measurements.
- Incoming API is checked through both WAN IPs, with reply counters on the matching
  physical interfaces while outgoing traffic prefers LTE.
- Original TCP/HTTP from a client pinned to backup and the original incoming API
  session through backup survive LTE failure/recovery. Full original/reply tuples
  and increasing bytes are verified; API connection IDs do not define identity.
- Protected rollback restores APN automatic default and distance. Temporary rules,
  server ports and fixture settings are removed; x86 L6 license is retained.

The test waits for new conntrack publication and confirms fixture-rule readiness
before connecting. Earlier failed attempts are not counted as successes. The
private final report binds all 11 RSC SHA256 values and the named CI image ID.
This does not replace comparative benchmarks or the long soak.

Separately, 44 native firewall-guard checks ran on CHR/x86 for root and candidate
sources: active foreign mangle/RAW notrack and undeclared FastTrack are rejected;
disabled/managed rules are accepted. The `disabled` flag is read directly because
`find where disabled=no` omitted enabled rules on tested 7.24.5.
[Migration draft preparation](MIGRATION.en.md).

## Original LTE iteration's final audit

All eight RSC installed in that original run matched native source; the production
LTE reader contained no adapter. Five CHRs had no temporary APN/PPP/VLAN, test rules
or background TCP fetch jobs. Test host forwards were removed; baseline contained
no provider_clients/lte_apns fixtures. Proxy had no impairments; `lab-v1` healthy:
default/client101 WAN1, client102 WAN2, strict103 WAN3. Continuation for that
completed historical iteration was disabled; this says nothing about the current
project's continuation state.

Local `runtime/` reports, credentials and device snapshots are excluded from the
repository. Repeatable verification: [TESTING.md](TESTING.en.md).
