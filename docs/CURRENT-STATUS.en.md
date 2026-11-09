# Current candidate status

[Русский](CURRENT-STATUS.md) | English

A direct cold container installation exposed an additional, intermittent reverse
conntrack source problem. The revised candidate handles both directions and
rearms source checks during recovery; final-source qualification is running.
The preceding candidate passed 136 Internet flows; the DNAT guard passed eight
targeted tuple cases. Its full matrix is rerunning. Earlier results keep their own sources.
[Evidence, retained failures and limits](CGNAT-VALIDATION.en.md).

Power interruption recovery passed bounded x86/CHR acceptance: both controller
modes, initial installation, update and empty active with differing staging.
Independent replay checked 56 flows and 69 coherent file snapshots.
[Mechanism](POWER-LOSS-RECOVERY.en.md) · [Results and limits](POWER-LOSS-VALIDATION.en.md).

Earlier mixed WAN/LTE/VPN/OSPF and orderly-restart validation retains its own
results. [Source and checks](MIXED-WAN-VALIDATION.en.md).

The preceding core update scopes configuration invalidation by WAN, SLA profile
and connection. [Contract](LIVE-CONFIGURATION.en.md) and [validation](LIVE-CONFIGURATION-VALIDATION.en.md)
record source-specific checks, retained failures and cold-reinstall behavior.
It does not inherit the original 48-hour or 150-run acceptance.

**Current main:** optional [weighted WAN policies](WEIGHTED-WAN.en.md) passed
bounded x86/CHR checks and four native resource windows. [Evidence, source hashes
and limits](WEIGHTED-WAN-VALIDATION.en.md). This is not a new 48-hour acceptance.

The preceding [native-cycle optimization](NATIVE-CYCLE-OPTIMIZATION.en.md) measured
88.76% → 68.62% CPU on its own source/instrumentation. The weighted extension has
a different bounded comparison: 79.12% ordered versus 84.80% weighted. Do not mix
these baselines. The 48-hour and 150-run results below belong to original v0.3.0.

Historical v0.3.0 snapshot dated **7 November 2026**, after verifying completed 48-hour acceptance. The native cold-start correction is tested at
`4015285b6a4ad651ef3be3cfe55765c14c804868`. Scenario preparation is strengthened in
`57708b6a5c1aa50e860ee9a16cc018f0ba3fec62`; its executable controller, container
and SDK code is unchanged from `4015285`. The preceding long run was bound to
`37a68a943d16ef597da48fabda217e5e61e5226e`. The public edition may have another
commit because it includes the RU/EN documentation. The actual execution commits
are recorded below. Uninterrupted long acceptance passed; the performance
comparison completed with 150/150 PASS. Results concern the virtual lab.


## Confirmed

| Check | Result and scope |
|---|---|
| SDK and test preparation | 398 unit tests at `57708b6`, including seven route-readiness checks; the earlier 391 passed at `37a68a9`/`4015285` |
| Builds and coverage | Six scratch images; 100% executable line/function coverage for Rust base/web, `main`, browser JS; branches reported separately |
| UDP retirement fix | 15 targeted old/current-function CHR checks at `b75f56a`; unrelated UDP/TCP retained |
| Native scenarios | 21 checks: transport 4, DHCP 2, PPPoE 2, lifecycle 6, cold start 3, post-start transport 4; executed at `b75f56a` |
| Exact CI web image | Four actual CHR checks, HTML/JS/CSS byte equality, 12 fresh snapshots with four WANs and two healthy overlay paths; cleanup verified |
| Forced switching | 600 seconds at `57708b6`, VPN failure/return in both RSC and container; 57 samples, no failures; independent restoration verified |
| Catalog | Six exact CI pins; stale catalog rejected; hardware recommendation profiles empty |
| Cold-start NAT | At `4015285`: six WireGuard/PPP/DNS cases with empty/existing NAT tables; the previous code failed all six |
| VPN cold start | At `4015285`: three real WireGuard, fresh SLA and both OSPF adjacency recovery checks; independent restoration passed |
| Cold DNS/DoH | Both strengthened scenarios passed at `57708b6`, including real VPN TCP with main closed, the no-leak guard, recovery and independent restoration |
| Uninterrupted acceptance | 172,800 seconds at `57708b6`: 24 hours RSC and 24 hours container, 5,621 samples without failures; independent restoration passed |

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

## Completed 48-hour acceptance

Measurements at `57708b6` ran from **4 November 12:34 UTC** to **6 November
12:34 UTC**, followed by restoration and independent verification. The result is
`passed`, `pass=true`, 172,800 seconds and 5,621 samples: 2,818 RSC and 2,803
container, with no failures. The plan allocates 24 hours each to RSC and container;
snapshot counts depend on check duration and the backend transition. Earlier
failed or interrupted hours are not included.

Independent checks verified the original three configurations/native files,
eight Full OSPF adjacencies, active routes to remote networks and healthy overlay
paths. The container is stopped, temporary rules removed, process exited and
locks released. Frozen source and parent disks remained unchanged. A source-bound
completion attestation was created on the original host for the comparison gate.

Final report SHA256:
`a46bd64bb24bf611d1b71d9c7e17a2ca60540c4bf8490a10a215a1a3aa6c0334`.
Raw reports remain private. Execution used the CI image `4e3cf126` and covered
source `7af650e6` identified above.

Under this workload, container RSS was 610,304–704,512 bytes (596–688 KiB), with
maximum container memory of 864,256 bytes (844 KiB). This scenario reached
12 history points; it is not a maximum-history capacity test. Process I/O counters
were unavailable, so this report does not establish zero flash writes.
These observations concern the virtual lab, not physical ARM/ARM64 capacity.

## Load comparison and limits

All 150 measurements and three failure/recovery checks completed on 7 November.
Pinned flows were preserved; independent checks of cleanup, processes, source
and parent disks passed. Baseline drift was no greater than 0.000342%.
Five stages × six workloads × five repeats, each with 120 s warmup and 60 s
measurement. [Tables, JSON/CSV and limits](PERFORMANCE-COMPARISON.en.md).

This is a fixed offered load on x86 L6 with 1 vCPU/1024 MiB, not peak capacity.
At 1000 CPS, SD-WAN mean CPU is 87–92%; UDP p95 reaches 100% in baseline too.
Physical ARM/ARM64 performance remains unproven, so automatic hardware
recommendations are absent. Archive availability is checked for the exact tag
in [Releases](https://github.com/alphazulu/mikrotik-sd-wan/releases).

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

Documentation edition `f17bc57` changed Markdown and catalog pins while retaining
its executable code. Later native NAT changes retain the same container Rust/JS. Because the container source digest includes README, this edition has its own
Rust base/web and JS coverage: 100% lines/functions; branches separately. Its digest
is `0772c14a13574b95c77faef9347bdaeb09e34afb835c73ec19aa0e11ca60db9d`. This does not replace the 7af source digest of the
executed CHR checks or claim that those checks execute this documentation edition.
Check edition build/CI results against its actual commit.
