# Optional VPN egress: development checkpoint

Target: isolated CHR **7.24.5**, existing five-node CGNAT/branch fabric. No
production router was accessed or changed. The controller stays on RouterOS;
the external Python/Tk utility configures and observes it through the API.
This is a development checkpoint, not completed release acceptance.

| Checks | Result |
| --- | --- |
| Python unit suite | 265 PASS |
| Existing Address List, static membership, removal, timed membership and retained TCP | 4 PASS |
| Python/native VPN contract | 18 PASS, including rejection of L2TP FastPath |
| Native/Python list types, explicit null, control bytes, UTF-8 byte limit | 44 PASS |
| WireGuard real SLA / TCP / scoped conntrack / physical failover | 8 PASS |
| L2TP/IPsec plus protected reapply | 9 PASS |
| SSTP real SLA / TCP / scoped conntrack / physical failover | 8 PASS |
| OpenVPN TCP real SLA / TCP / scoped conntrack / physical failover | 8 PASS |
| OpenVPN protected reapply | PASS; all three stream IDs retained, data resumed within20s |
| VPN1 → VPN2 → physical → all-down, recovery with main closed | 7 PASS |
| Full encrypted rollback after real VPN routing/dataplane mutation | 3 PASS |
| Real server-pushed def1 rejection and protected adoption | 3 PASS |
| Duplicate VPN source IPv4 | Both exits rejected; physical WANs remained ready |
| Cold restart with active WireGuard egress | 3 PASS; unchanged public identity, fresh SLA, two OSPF neighbors Full |
| WireGuard hostname and real DNS address rotation | 2 PASS; old server blocked, hostname retained, fresh VPN TCP and unrelated streams preserved |
| Public-only key preparation against actual CHR API | 2 PASS; disabled local identity and idempotent public readback |
| DHCP and PPPoE parent address change with VPN and private OSPF | 2 PASS per protocol; live leases, scoped transport cleanup and retained branch TCP |
| API/native full-default route boundary | 5 PASS; enabled inactive defaults rejected, exact adoption validated |
| Windows GUI offline | 4 PASS |
| Windows GUI against live CHR API | 3 PASS; router configuration unchanged |

The tunnel-up flag is insufficient: a forward filter beyond a running exit
blocks representative resource probes. The shared SLA engine then chooses the
next declared channel. Real forwarded TCP proves only old policy/channel marks
are retired; unrelated Internet and private OSPF streams retain their connection
IDs and keep receiving data. A separate matrix tests two VPN exits before
physical backups, a policy blackhole with every exit unavailable, VPN recovery
while generic main Internet is still SLA-closed, and loss of all physical parents.

Fixtures use existing WireGuard, L2TP/IPsec, SSTP and OpenVPN clients on a branch,
with servers on the emulated hub. Authentication is private runtime data. The
OpenVPN certificate and private keys are generated on CHR. No private keys are
exported to configuration JSON, GUI inventory or public source.

Rollback validation deliberately fails after original OpenVPN automatic-default
and pull options have been changed and classifiers installed. The local watchdog
restores the encrypted full backup, all ten RSC files and JSON/baseline files,
original client options and disabled state. Native SLA and both private overlay
legs recover after reboot.

The pushed-route test uses an actual OpenVPN server with `redirect-gateway=def1`
and a fresh client with automatic default enabled. API preflight and the native
installer independently reject unadopted split defaults. After explicit adoption,
automatic and pushed routes disappear, original options are captured, and the
existing tunnel becomes eligible through normal resource SLA.

Observed7.24.5 details relevant to tests:

- Dynamic RIB routes can be omitted by `where disabled=no` even though `get
  disabled` returns false. Native split-default validation filters that flag after
  finding the route prefix. The real pushed-route test covers this behavior.
- API values report a VPN next-hop IP plus `immediate-gw`/`vrf-interface`, rather
  than always putting the logical interface name in `gateway`.
- Address List timeout can display0s before the object is retired. Acceptance waits
  for actual retirement and checks a new real connection; it does not create a
  second list-expiry mechanism or assume zero means immediate kernel removal.
- Live TCP after protected reapply can wait for retransmission backoff. The test
  requires the same conntrack IDs and renewed data within a bounded20s check.
- Windows can reserve55728range ports through Hyper-V. Loopback aliases45728..32
  reach the same existing CHRs without restarting them or creating another fabric.

Private runtime reports remain outside the publication tree. Repeatable tools:

```text
python tests/address_list_acceptance.py --lab-root PRIVATE_ROOT
python tests/address_list_contract_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_contract_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_egress_acceptance.py --protocol wireguard --traffic --lab-root PRIVATE_ROOT
python tests/vpn_egress_acceptance.py --protocol l2tp --traffic --reapply --lab-root PRIVATE_ROOT
python tests/vpn_egress_acceptance.py --protocol sstp --traffic --lab-root PRIVATE_ROOT
python tests/vpn_egress_acceptance.py --protocol openvpn --traffic --lab-root PRIVATE_ROOT
python tests/vpn_priority_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_protection_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_pushed_defaults_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_duplicate_source_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_restart_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_dns_acceptance.py --lab-root PRIVATE_ROOT
python tests/overlay_key_acceptance.py --lab-root PRIVATE_ROOT
python tests/vpn_dynamic_underlay_acceptance.py --kind dhcp --lab-root PRIVATE_ROOT
python tests/vpn_dynamic_underlay_acceptance.py --kind pppoe --lab-root PRIVATE_ROOT
python tests/default_route_guard_acceptance.py --lab-root PRIVATE_ROOT
```

Tests use nonblocking ownership locks and restore their configuration/fixtures.
Check existing processes and reports before running; never duplicate the fabric
or a long soak. Do not run live GUI assertions during a test that temporarily
changes fixture clients.

The captured repeated-handshake failure exposed a test-fixture ACL boundary:
the server reply followed OSPF's second return leg, but the temporary public
source prefixes were authorized only on the first WireGuard peer. The fixture
now authorizes both legitimate return legs and restores all original ACLs.
The subsequent Rust/two-VPN matrix passed all7cases. Additional sustained
fault/reapply repeatability still belongs to the final acceptance and soak.

Current 0.3.0 container acceptance passes all four protocols (8 checks each),
plus the two-VPN priority matrix (7), authenticated web/fallback/steady intent
checks (6) and the short same-configuration resource sample. Plain cold external
DNS has 5 checks and hostname/custom-port HTTPS DoH has 6. The new DNS module's
absent-file encrypted rollback has 2 checks. See [current gates](NEXT-NETWORK-PLAN.md)
for the completed dynamic/lifecycle batch and the remaining single 48–72h final soak.
Duplicate source addresses require an independently validated VRF layout; VRF
support is not claimed here. The emulated SSTP fixture does not replace testing
an operator's TLS/certificate configuration.

## Unified WAN steering (current development branch)

VPN exits now belong only to `wans`; all selection is in ordinary `policies`.
The GUI no longer creates a feature switch or an implicit destination policy.
Legacy configurations remain readable and migrate on SDK/GUI output.

Verified after this change:265 Python tests;88 native/Python source/destination
Address List contract cases;18 VPN native/Python cases;5 offline and4 read-only
live Windows GUI checks;6 real-CHR checks in
`tests/unified_wan_acceptance.py`. The CHR checks cover source IP, destination IP,
source list, both lists with AND, mixed VPN/physical queues, source-list updates,
per-policy SLA failover/failback with scoped conntrack cleanup, readable per-policy
jump chains, independent branch/Internet TCP survival, and VPN as the general
Internet default with physical tunnel transport pinning.

Overlay native schema/ownership gates pass 123/24 cases. The final native batch
passes DHCP (2), PPPoE (2), outer-UDP retirement (4) and lifecycle/complete-package
rollback (6). The unit suite now has 269 tests including observer safety checks.
The full-branch soak, CI and publication remain open.
