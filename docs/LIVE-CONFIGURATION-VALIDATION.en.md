# Live configuration validation

[Русский](LIVE-CONFIGURATION-VALIDATION.md) | English

Bounded checks ran on RouterOS **7.24.5**: disposable x86 L6, 1 vCPU/1024 MiB,
three virtual WANs and real TCP/UDP echo clients. A separate fresh CHR checked
native language/helpers and complete rollback. The production router was untouched.
This is separate qualification, not a repeat of v0.3.0's 48 hours or 150 measurements.

## Source and evidence

[Sanitized machine-readable results](benchmarks/live-configuration.json) contain
source trees, executable hashes, private-report hashes, captures and retained-session
counts. Raw configuration, credentials and licensed images are excluded.

The final executable candidate tree is
`6345fe7db806f544e1b5543a426142861de3f4fc` (477 files). Compared with the matrix
candidate `d5d1719684dce4c7455e935762c38d709045cd12`, only
`native/sdwan-install.rsc` changed: repair owned probes on reapply and require fresh
SLA after cold reinstall. Final-source runs 145, 146 and 148 qualify those paths.
Earlier results retain their original source identity; they are not relabelled
as whole-system executions of the final candidate.

Rust/JS/bridge code and all six catalog images are unchanged. Container source:
`0772c14a13574b95c77faef9347bdaeb09e34afb835c73ec19aa0e11ca60db9d`.
The shared derived RSC controller carries the new behavior. Publishing still
requires CI coverage for Rust base/web/main and browser JS, plus exact image checks.

## Actual checks

| Run | Result and bounded scope |
|---|---|
| 134/135 | Negative control reproduced unrelated session loss on selector/WAN-kind edits. Candidate135 passed 52 native helper cases and 15 forwarding/state checks: revision/equivalent selector, selective reclassification and static→DHCP edit. Healthy WAN2 and pinned sessions survived. |
| 140 | 71 native helper cases and 17 checks: real old 12→new 13-module upgrade with nine strict HTTP probes, exact healthy-session retention, changed HTTP body rejected, recovery, profile-specific reset and equivalent numeric limits. A 35-second slow-HTTP window retained a ≥9-second request gap for a 10-second interval. |
| 141 | 25 checks: failed upgrade restores old files and prior module absence; TCP/UDP selector edits, actual Address List matching/membership change, static source-address edit, exact local Rust image, native fallback and container restart. |
| 145 | Six checks on final source: same-value setters retain counters; disabled owned probe is repaired; all 36 held TCP/UDP sessions retain exact conntrack IDs/tuples and advancing exchanges. Four WAN2 probes retain IDs and positive counters. Cold reinstall first admitted healthy at epoch5, with four fresh windows required; the old bug admitted at epoch2. |
| 146 | Fresh CHR: 71 actual scope/health/flow/range/strict-evidence cases; complete empty-baseline rollback removes owned RAM/static entries and preserves foreign static/dynamic Address Lists. |
| 148 | Six final-source checks, including 71 helper cases and actual old 12→new 13 upgrade: healthy WAN1/WAN2 TCP/UDP sessions and positive probe counters survive; strict results carry exact signatures. |
| Host | 416 SDK units, 88 external-lab units, seven weighted-policy Tk checks and wizard/telemetry/VPN/overlay GUI regressions passed. |

Session checks compare original conntrack IDs, original/reply tuples, marks and
packet counters with advancing echo counters and zero observed TCP disconnects.
Fresh-connection batches are checked against actual WAN captures, with no kernel
capture drops. `selected` alone does not establish successful forwarding.

Independent verification reread 11 reports, frozen sources, raw session/probe/packet
evidence and cleanup journals. Three parent disks retained their hashes; owned
processes/namespaces were gone, ports released and the global lab lease free.
Original baseline/candidate135 evidence has a separate independent verification.

## Retained failures

Run139 exposed a real upgrade regression: live callbacks could discard unsigned
legacy evidence before adoption, transiently losing healthy quorum and sessions.
Adoption order and late-worker fences were fixed; run140 passed. Diagnostic143
then exposed disabled-probe repair and cached-SLA reinstall defects, fixed in the
final installer and verified in145. These diagnostics are not counted as feature PASS.

Run136 stopped on the old controller's 1.2-second delayed HTTP response: actual
fetch time was about 2 seconds, leaving no worker overhead inside the unchanged
2-second budget. Diagnostic138 measured twelve fetches; later tests use a measured
0.6-second body delay, still spanning scheduler ticks. No timeout was relaxed.
Run137 failed on test JSON escaping before measurements. Run144 accidentally
changed a strict probe's type while asserting a no-op; corrected145 retains the
real type/start-delay. Run142 was blocked before guest creation by the active lab
lease; fresh146 ran sequentially. Original failures remain retained.

## Limits

No zero-loss, atomic cutover, maximum-rule/conntrack capacity or universal update-time
claim is made. This run does not requalify a full VPN/OSPF topology, physical ARM/ARM64
or real LTE hardware. Changed NAT source addresses do not migrate sessions to a new
public IP. Protected rollback can reboot and does not guarantee session survival.
The known optional web polling limitation during protected reconfiguration remains;
steady web behavior has its own earlier evidence.

[Behavior and configuration](LIVE-CONFIGURATION.en.md) · [Deployment](DEPLOYMENT.en.md)
