# Current candidate status

[Русский](CURRENT-STATUS.md) | English

Snapshot dated **4 November 2026**. The native cold-start correction is tested at
`4015285b6a4ad651ef3be3cfe55765c14c804868`. Scenario preparation is strengthened in
`57708b6a5c1aa50e860ee9a16cc018f0ba3fec62`; its executable controller, container
and SDK code is unchanged from `4015285`. The preceding long run was bound to
`37a68a943d16ef597da48fabda217e5e61e5226e`. The public edition may have another
commit because it includes the RU/EN documentation. The actual execution commits
are recorded below. Long acceptance has not passed.

## Confirmed

| Check | Result and scope |
|---|---|
| SDK and test preparation | 398 unit tests at `57708b6`, including seven route-readiness checks; the earlier 391 passed at `37a68a9`/`4015285` |
| Builds and coverage | Six scratch images; 100% executable line/function coverage for Rust base/web, `main`, browser JS; branches reported separately |
| UDP retirement fix | 15 targeted old/current-function CHR checks at `b75f56a`; unrelated UDP/TCP retained |
| Native scenarios | 21 checks: transport 4, DHCP 2, PPPoE 2, lifecycle 6, cold start 3, post-start transport 4; executed at `b75f56a` |
| Exact CI web image | Four actual CHR checks, HTML/JS/CSS byte equality, 12 fresh snapshots with four WANs and two healthy overlay paths; cleanup verified |
| Forced switching | 600 seconds at `959495c`, VPN failure/return in both RSC and container; independent restoration verified |
| Catalog | Six exact CI pins; stale catalog rejected; hardware recommendation profiles empty |
| Cold-start NAT | At `4015285`: six WireGuard/PPP/DNS cases with empty/existing NAT tables; the previous code failed all six |
| VPN cold start | At `4015285`: three real WireGuard, fresh SLA and both OSPF adjacency recovery checks; independent restoration passed |

After the initial native acceptance, commits `959495c` and `37a68a9` changed packaging/catalog
metadata rather than executable logic. Equivalence is recorded explicitly; a
check is not claimed to have executed at a commit on which it never ran.

Container source digest used in the listed CHR checks:
`7af650e6b49c6aaa925c7be72836b01255a60478be52f5ceafde245d322e0ead`.
Accepted CI web amd64 image ID:
`4e3cf126836c0242f37d7b2e1411c2dfe476dbc5924e190368bf586f44d91fcd`.

Historical public checks at `37a68a9`:
[main CI](https://github.com/alphazulu/mikrotik-sd-wan/actions/runs/40857122851),
[external tools](https://github.com/alphazulu/mikrotik-sd-wan/actions/runs/40857122807).
Raw local reports remain private because they can contain lab-specific settings.

## Still pending

- A fresh 48-hour run (24 hours RSC, then 24 hours container) has not started.
  The preliminary cold-DNS check stopped at client TCP forwarding: VPN SLA was
  available while the ordinary policy remained closed, but TCP did not connect.
  Subsequent diagnosis captured `Full` before an active OSPF return route existed.
  Preparation at `57708b6` requires both adjacencies and active routes to all expected
  remote prefixes. DNS/DoH and switching gates are running; the old failure remains
  retained. After those pass, a complete long report and independent restoration
  are still required.
- The prepared 150-measurement comparison has not executed.
- Physical ARM/ARM64 capacity is unproven; cross-compilation does not replace
  hardware acceptance. There are no automatic hardware recommendations.
- Candidate 0.3.0 is not a published release. Previous Releases and their reports
  describe their own versions and do not establish acceptance of this candidate.

## Retained failures

The `37a68a9` run started on 29 October was interrupted by a confirmed power loss
at 47,657.359 seconds and 1,525 samples (about 13.24 hours). This is an infrastructure
interruption, not PASS. Lab restoration was independently verified; the old disks
and reports are retained. Interrupted hours are not added to the fresh run.

The following short check exposed native `place-before=0` in VPN NAT rules.
RouterOS 7.24.5 rejected it from the scheduler. Correction `4015285` obtains a current
internal ID with `find`, omitting `place-before` for an empty NAT table. The same
path is corrected in DNS bootstrap, and loaded-function versions are updated.
See [MikroTik guidance on item IDs](https://manual.mikrotik.com/docs/developer-guides/scripting/scripting-tips-and-tricks/).
The six targeted cases use real NAT commands while isolating VPN binding/restart
and conntrack. They do not replace actual tunnel and TCP acceptance checks.

After real WireGuard cold-start checks passed at `4015285`, the DNS-recovery TCP
check stopped as described above. Configuration, controller files, healthy overlay
paths and eight OSPF adjacencies were restored and independently verified. Later
stages stopped; there was no automatic retry.
Diagnosis of the same post-reboot startup path showed SYN-ACK at SiteA while a
blackhole still won for the remote client network. An OSPF route appeared later
and the transfer worked. This exposed an insufficient test-preparation condition;
there is no exact packet snapshot of the original failure. Neighbor exchange and
route calculation are separate [OSPF steps](https://manual.mikrotik.com/docs/user-guides/routing-and-networking-protocols/unicast/ospf/neighbour-relationship/).
Only the readiness predicate is strengthened at `57708b6`. Preparation and TCP
timeouts are unchanged, and no retries of the qualifying transfer are added.

The previous `c3e1880` run failed after 148,171.464 seconds (about 41.16 hours).
Its old wrapper did not retain the exact location of an empty assertion, so the
cause of that run is unknown. Independent restoration passed. An incomplete
UDP-retirement address cache was separately reproduced and fixed; it is not a
proven explanation of the old run. The old report remains failed.

Historical counts in `*-VALIDATION.md` describe individual milestones. Do not add
them as unique tests or substitute them for current release gates.

[Testing order](TESTING.en.md) · [Long acceptance](NETWORK-SOAK.en.md) ·
[Comparison plan](PERFORMANCE-PLAN.en.md) · [Roadmap](../ROADMAP.en.md)

## Documentation edition

The RU/EN edition changes Markdown and catalog source pins while retaining executable
code. Because the container source digest includes README, this edition has its own
Rust base/web and JS coverage: 100% lines/functions; branches separately. Its digest
is `0772c14a13574b95c77faef9347bdaeb09e34afb835c73ec19aa0e11ca60db9d`. This does not replace the 7af source digest of the
executed CHR checks or claim that those checks execute this documentation edition.
Check edition build/CI results against its actual commit.
