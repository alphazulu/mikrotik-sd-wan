# Branches behind carrier NAT

[Русский](CGNAT-VALIDATION.md) | English

Qualification of the revised source correction is in progress. A direct cold
container installation exposed a second, intermittent conntrack direction gap
after the earlier bounded tests. Those historical results remain valid only
for their recorded sources and scopes; they do not qualify the new candidate.

## Topology and source

Two branches each have WAN1 and WAN2 behind separate outbound-only carrier
NATs. Both initiate WireGuard to one reachable hub, which learns authenticated
source endpoints. A reachable hub is required; arbitrary direct connectivity
between two symmetric NATs is outside this design.

Site A is x86 with a level-6 license; site B and the hub are CHR. All run
RouterOS 7.24.5. Five owned Linux namespaces emulate the two carriers,
Internet health/echo targets and two LANs. The targets use reserved lab addresses;
the fabric does not use a real ISP uplink. Each carrier rejects the other
carrier's private source range. There is no inbound DNAT or private underlay
route between the branches.

Each site has two WireGuard/OSPF paths. WAN1 is preferred for ordinary Internet
traffic; a source-specific policy strictly selects WAN2. Private site prefixes
bypass Internet marking and NAT. Checks require Full neighbors **and installed
routes**: two neighbors per branch, four on the hub.

Historical traces 231, 233 and 236 use frozen tree
e111b0bcd359684cf084046156606438a52ef87f. Public runtime commit
[48b0742](https://github.com/alphazulu/mikrotik-sd-wan/commit/48b074272d775f5f78c5ec00b0a5f92f664eff73)
has exactly that tree. The revised candidate is frozen separately at tree
71afaa5bf64ca159e8057b8beaee38e2418d67dc. Its fresh fault matrix is in progress;
no final-source PASS is claimed yet.

## Cold secondary-WAN source correction

The initial fabric exposed an outbound UDP connection with WAN1's local source
on WAN2 and no source NAT. The carrier correctly rejected that source. Removing
only the exact observed transport tuple restored the secondary paths; that was
a deliberate diagnostic intervention, not autonomous acceptance.

Later, direct cold installation of the local container failed with the reverse
case: an original inbound connection had a reply source belonging to WAN1 while
the tunnel was pinned to WAN2. The old check covered only outbound originals and
stopped after the first matching tuple. Run 239 remains failed. Another fresh
old-source run, 240, established all four paths and did not reproduce that tuple;
its planned manual deletion was never performed. The startup issue is intermittent.

The revised RouterOS helper checks both directions of the exact owned UDP
listener/remote-address/remote-port tuple. For outbound originals it inspects
reply-dst-address; for inbound originals it inspects reply-src-address. Original
local source or destination ownership is required. It retires a tuple only when
the post-NAT source is another known local interface's address. Valid masquerade,
chosen-WAN aliases and unknown external sources are retained. Responders, inner
TCP/UDP, other ports and other remote endpoints are outside the adoption check.

The check no longer ends on the first observed tuple. It runs while the inner
peer probe is down and for 30 seconds after the last down observation. WAN return,
transport geometry change and older in-memory module state start a new window.
Once the peer stays healthy and the window expires, unchanged geometry skips the
inventory and conntrack scan. Address inventory is capped at 1024 entries.
State remains in RAM; no periodic storage writes are added. This is not a
zero-writes claim for RouterOS as a whole.

Actual RouterOS import and all 21 native source/recovery-window cases passed on
the revised frozen source. The new direct-container/native fault matrix and its
final independent replay are still pending.

## Independently replayed results

| Trace and qualified scope | Fresh Internet TCP/UDP flows with bidirectional packet proof | Private preservation |
|---|---:|---|
| 231: native WAN1 loss at A, return, loss at B, loss at both, return; NAT port change | 48 | Four held paths, 12 conntrack rows, 222 unique snapshots |
| 233: native NAT address/port and Internet-SLA failure/return; native-to-container transition; five container WAN loss/return cases | 56 | Four held paths, 12 rows, 462 unique snapshots |
| 236: native and container orderly reboot; remaining container NAT/SLA cases | 40 | Two fresh post-reboot cohorts, four held paths and 12 rows per cohort, 397 snapshots |

These historical results total **144 fresh Internet flows across three separate fabrics**;
they do not qualify the revised candidate or the failed cold-install case.
Snapshot counts are deduplicated within each run. Flows and conntrack IDs are
not claimed to persist between fabrics or through reboot.

The checks also established:

- Four automatically established WireGuard paths with OSPF routes; private
  traffic remains unmarked and without NAT.
- Existing private TCP/UDP and their conntrack rows survive WAN switching,
  authenticated endpoint changes and conversion to the local container.
- The hub learns NAT port and address/port changes without host API edits to
  peer endpoints. Old outer tuples are retired while unrelated tunnels remain.
- When both Internet SLAs at A fail with physical WANs still up, four new
  TCP/UDP attempts are blocked. Private WireGuard/OSPF traffic remains usable;
  recovery restores the preferred Internet WAN.
- Native and local-container guest reboots reset uptime, retain the level-6
  license, collect fresh SLA samples and restore all four paths and new flows.
  Pre-reboot test sessions are deliberately stopped.
- Nine native source-predicate cases passed. The source/image of the local
  scratch container is unchanged and retains its 100% executable line/function
  unit-coverage pin; CI includes base, web, main and browser JavaScript.
- Owned processes, namespaces and nine management ports were released.
  Original x86/CHR image hashes were independently checked after cleanup.

## Retained failures and observer corrections

Full reports 231 and 233 remain failed; the table uses their independently
verified successful subsets. In 231, an immediate old-tuple assertion ran before
retirement was observed. A scoped successor with the same controller recorded
retirement after 1.36 s and 0.86 s in two native cases, within a ten-second
observation limit. These are observations, not hardware timing guarantees.

The later 233 timeout came from a test assumption: RouterOS had translated the
active source port from 51821 to 17875 while the test targeted a stale 51821
carrier entry. Conntrack, carrier NAT and the authenticated hub endpoint
identified the active port. Seven selector tests and replay of that real trace
qualified the corrected read-only selection. In live run 236, the selected
wire port was 65463; carrier rotations to ports 60001 and 60002 preserved the
active RouterOS tuple, three other WireGuard tuples and private connections.
Both directions of the UDP packet path were captured.

Earlier fixture, parser and result-observer failures are retained separately.
A successful API response to an import dry run was insufficient to detect a
known-bad library. The lab instead observed actual library imports through
RouterOS onerror, requiring rejection of the bad control, acceptance of the
current library and unchanged configured forwarding. A duplicate child-log
label stopped run 235 before reboot; scoped run 236 corrected that label.

## Limits and references

These tests establish neither physical LTE/RF behavior, ARM capacity, direct
symmetric-NAT traversal nor hardware flash durability. Earlier mixed-WAN,
power-recovery and 48-hour results retain their own sources and scopes.

Official [WireGuard peer documentation](https://manual.mikrotik.com/docs/cli-reference/interface/wireguard/peers/)
describes authenticated endpoint learning and keepalive.
[Connection fields](https://manual.mikrotik.com/docs/cli-reference/ip/firewall/connection/)
defines the original/reply tuple fields used for correlation.
[Configuration management](https://manual.mikrotik.com/docs/getting-started/configuration-management/)
documents import diagnostics. The current NAT topic was unavailable during the
review; the older official [NAT reference](https://help.mikrotik.com/docs/spaces/ROS/pages/3211299/NAT)
explains connection tracking's retained first-packet NAT decision.
The manual currently displays 7.26; the tested RouterOS version remains 7.24.5.
