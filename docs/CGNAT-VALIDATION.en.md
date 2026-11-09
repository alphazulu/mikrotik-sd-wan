# Branches behind carrier NAT

[Русский](CGNAT-VALIDATION.md) | English

Candidate qualification is in progress. This document does not declare the
fault matrix or local-container parity passed.

The controller remains on each MikroTik: native RouterOS, or the local
unprivileged Rust scratch container. Branches initiate WireGuard to a reachable
hub; the hub learns the source address and port of authenticated packets.
This topology requires a reachable hub. It does not provide direct connectivity
between arbitrary symmetric NATs.

## Fresh isolated fabric

Two branches each have WAN1 and WAN2, with separate outbound-only carrier NATs.
Site A is licensed x86 level 6, while site B and the hub are CHR; all run
RouterOS 7.24.5. Five owned Linux namespaces emulate the carriers, Internet and
two LANs. Carrier forwarding rejects the other carrier's private source range.
There is no inbound DNAT or private underlay route between sites.

Each branch has two WireGuard tunnels and OSPF paths. WAN1 is preferred for
ordinary Internet traffic; a separate source policy strictly selects WAN2.
Private site prefixes bypass Internet marking and NAT. Checks require both
Full neighbors and installed routes before traffic starts.

## Cold secondary-WAN defect

The initial fabric exposed an existing UDP connection with WAN1's local source
on WAN2 and no source NAT. The correct masquerade rule was present but had not
processed that connection's first packet. The carrier correctly rejected it.

Deleting only the observed listener/remote-address/remote-port tuple restored
both secondary paths. Independent replay verified 53 snapshots of 12 private
conntrack rows and eight fresh Internet wire correlations. That deliberate
diagnostic intervention is evidence of the cause, not autonomous acceptance.

The candidate adds a bounded first-source check for initiating overlay peers.
It compares the post-NAT source with enabled local addresses on the chosen WAN.
Only a known local source belonging to another interface is retired, and only
for the owned UDP listener and exact remote address/port. Valid masquerade,
chosen-WAN aliases and unknown external source addresses are preserved.
Responder peers and inner TCP/UDP sessions are outside this check.

The scan runs in RAM for at most 30 seconds after the WAN becomes ready,
finishing earlier once a matching local tuple is observed. It does not add
periodic storage writes. Stable checked geometry skips the scan. Nine native
predicate cases cover incorrect, valid, alias, external, absent and invalid
sources; real traffic tests qualify actual retirement and preservation.

## Evidence and limits

The original carrier-forwarding fixture failures and the candidate syntax
failure remain failed. The protected installer rolled back the syntax failure;
resources were released and parent-image hashes were retained. A later harness
import mismatch was rejected by source hashes before any DUT was created.

The API returned success for the import dry run of a known-bad library.
Consequently a successful API response to dry run is not used as the parser
gate. The fresh-DUT fixture observes an actual import through RouterOS
onerror, requires rejection of the bad control and acceptance of the current
library, and checks that forwarding configuration is unchanged.

The tested controller source is unchanged since the 7efadbe candidate;
the c18330214a0a06abc339e7a7fd884545264d7c5c snapshot only corrects the
native acceptance harness. Its tree is
e111b0bcd359684cf084046156606438a52ef87f. Nine predicate cases and the actual
import error observer passed independently on a fresh x86 DUT.

The subsequent full run remains failed at its immediate stale-tuple assertion
after a NAT address/port change. Independently replayed earlier checks from
that same run confirmed 48 bidirectional Internet wire correlations, four held
private paths and 222 snapshots of 12 private conntrack rows. Five native WAN
failure/return cases and a NAT port-only change passed. These are bounded
partial results, not a full-run PASS.

A scoped successor confirmed native NAT port and address/port changes, Internet-only
SLA failure and recovery, and retention of private traffic. Independent replay
checked 16 additional Internet flows and 83 snapshots of 12 private conntrack
rows. The observed old-tuple retirement windows were 1.36 s and 0.86 s in these
two cases; the observer has a ten-second limit. These are observations, not a
hardware timing guarantee.

The same successor installed the local Rust container while retaining private
connections. Five container WAN failure/return cases then passed. Independent
replay covered 56 Internet flows in that run, 462 unique private snapshots and
11 preservation phases, including its native portion.

That full run remains failed at a later NAT test. RouterOS had legitimately
translated the active WireGuard source port from 51821 to 17875; the test
incorrectly tried to rotate a stale carrier tuple still using 51821. RouterOS
conntrack, the carrier table and the authenticated hub endpoint independently
identified 17875 as the active port. Seven selector tests and replay of this
real trace cover the correction. The scoped remaining test selects the active
post-masquerade tuple before changing only that carrier connection.

Pending: remaining container NAT/SLA checks and orderly native/container guest
restart with fresh SLA and new sessions. Completed physical-WAN matrices are
not repeated. A virtual test cannot establish physical LTE radio behavior,
ARM capacity or hardware flash durability.

## Official references

Current [WireGuard peers](https://manual.mikrotik.com/docs/cli-reference/interface/wireguard/peers/)
documents authenticated endpoint learning and persistent keepalive.
[Configuration management](https://manual.mikrotik.com/docs/getting-started/configuration-management/)
describes the import dry run. Both were checked against the 7.24.5 target.
The current manual's NAT topic was unavailable during this review; the older
official [NAT reference](https://help.mikrotik.com/docs/spaces/ROS/pages/3211299/NAT)
explains that a connection retains the NAT decision made for its first packet.

The current [connection-tracking reference](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/connection-tracking/)
defines the original and reply address/port fields used for the wire-tuple
correlation. The tested target remains RouterOS 7.24.5.
