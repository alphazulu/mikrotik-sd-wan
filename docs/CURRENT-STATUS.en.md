# Current candidate status

[Русский](CURRENT-STATUS.md) | English

Snapshot dated **29 October 2026**, for tested commit
`37a68a943d16ef597da48fabda217e5e61e5226e`. Documentation revisions may have another
commit; they do not change the sources under test. Update this page before release
from completed reports, retaining the commits on which checks actually ran.

## Confirmed

| Check | Result and scope |
|---|---|
| SDK | 391 unit tests, current candidate CI |
| Builds and coverage | Six scratch images; 100% executable line/function coverage for Rust base/web, `main`, browser JS; branches reported separately |
| UDP retirement fix | 15 targeted old/current-function CHR checks at `b75f56a`; unrelated UDP/TCP retained |
| Native scenarios | 21 checks: transport 4, DHCP 2, PPPoE 2, lifecycle 6, cold start 3, post-start transport 4; executed at `b75f56a` |
| Exact CI web image | Four actual CHR checks, HTML/JS/CSS byte equality, 12 fresh snapshots with four WANs and two healthy overlay paths; cleanup verified |
| Forced switching | 600 seconds at `959495c`, VPN failure/return in both RSC and container; independent restoration verified |
| Catalog | Six exact CI pins; stale catalog rejected; hardware recommendation profiles empty |

After native acceptance, commits `959495c` and `37a68a9` changed packaging/catalog
metadata rather than executable logic. Equivalence is recorded explicitly; a
check is not claimed to have executed at a commit on which it never ran.

Exact container source digest:
`7af650e6b49c6aaa925c7be72836b01255a60478be52f5ceafde245d322e0ead`.
Accepted CI web amd64 image ID:
`4e3cf126836c0242f37d7b2e1411c2dfe476dbc5924e190368bf586f44d91fcd`.

Public checks:
[main CI](https://github.com/alphazulu/mikrotik-sd-wan/actions/runs/40857122851),
[external tools](https://github.com/alphazulu/mikrotik-sd-wan/actions/runs/40857122807).
Raw local reports remain private because they can contain lab-specific settings.

## Still pending

- Current 48-hour run: 24 hours RSC, then 24 hours container. Started on 29 October;
  there is no PASS result yet. A complete report and independent restoration are required.
- The prepared 150-measurement comparison has not executed.
- Physical ARM/ARM64 capacity is unproven; cross-compilation does not replace
  hardware acceptance. There are no automatic hardware recommendations.
- Candidate 0.3.0 is not a published release. Previous Releases and their reports
  describe their own versions and do not establish acceptance of this candidate.

## Retained failures

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
is `0772c14a13574b95c77faef9347bdaeb09e34afb835c73ec19aa0e11ca60db9d`. This does not replace the current
long test's 7af source digest or claim that the test executes this edition.
Check edition build/CI results against its actual commit.
