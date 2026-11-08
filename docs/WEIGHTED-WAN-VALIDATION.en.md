# Weighted WAN validation

[Русский](WEIGHTED-WAN-VALIDATION.md) | English

The optional [weighted-policy extension](WEIGHTED-WAN.en.md) passed the bounded
checks below on RouterOS **7.24.5**. The production router was not accessed.
This is separate from the original v0.3.0 48-hour and 150-measurement acceptance.

## Functional evidence

| Check | Result and scope |
|---|---|
| SDK / external tools / GUI | 414 / 88 unit tests; 7 actual Tk balance-editor checks |
| Actual RSC functions | 40 cases each on x86 L6 and fresh CHR: all 25 subsets of 2–4 members, 10 invalid policies, 5 admission guards/lifecycle cases |
| Two active WANs, `3:1:0` | 400 TCP echoes: 294/106/0; 160 UDP echoes: 120/40/0 |
| Three active WANs, `3:2:1` | 120 TCP echoes: 61/39/20; 120 UDP echoes: 57/41/22 |
| WAN1 lost from that pool | Remaining `2:1` subset: TCP 0/61/19, UDP 0/58/22; all 160 echoes returned |
| Runtime health changes | Primary and secondary loss/return; exact excluded marks retired, healthy TCP/UDP IDs and tuples retained with advancing receive counters |
| Drain / reserves / closure | New flows leave a draining member; eligible sessions survive until deadline; zero-weight reserve works; all-SLA loss closes admission |
| Policies | Source IP AND destination Address List; source Address List AND destination IP; live list changes, excluded-client default and separate pinned policy |
| Affinity | `both-addresses` and `src-address`: 80 new TCP/UDP connections each stayed on one WAN with a stable pool |
| Symmetry | Actual DNAT responses used each of WAN1/WAN2/WAN3 while outbound policy was balanced |
| Container / fallback | Exact existing scratch web image; weighted forwarding, loss/return, container stop/native fallback and restart retained healthy sessions |
| DHCP | Real lease loss and a different leased address: fresh flows, source pin and healthy WAN2 sessions checked |
| Lifecycle | Failed old 11-module → 12-module upgrade restored old files and removed the previously absent module; successful upgrade and cold reboot passed |
| Uninstall | All owned RAM admissions/rules removed, foreign static/dynamic lists kept; original addresses/routes/rules/NAT matched using explicit flag getters before and after |
| Steady optional web | Composite weighted policy with traffic: 21 authenticated requests over 7 cycles, zero errors |

The four-member cases test functions/layouts, not four real WAN links. Full traffic
checks used virtual x86 L6 with three WAN peers; CHR checks cover native functions
and rollback. Existing VPN/LTE transport code is unchanged; this phase does not
repeat the complete per-protocol or physical-modem acceptance.

## Bounded resource cost

Same candidate, native mode, **1 vCPU / 1024 MiB / virtio**, four policies.
The default policy was alternately ordered or weighted `3:1:0`; the 128 generator
sources matched that policy. Client-specific policy weights would not exercise
this workload. The order was A–B–B–A, with 10 seconds warmup and 30 measured.
Each window completed all **40,000** fresh connections, including warmup, with
matching client/server echo counts and zero endpoint errors. Tuple and destination
reservations were disjoint. The system TIME_WAIT settings were not changed.

| Window | Default policy | Mean RouterOS CPU | Observed CPS |
|---|---|---:|---:|
| 1 | Ordered | 79.07% | 1000.03 |
| 2 | Weighted | 85.37% | 1000.03 |
| 3 | Weighted | 84.23% | 1000.00 |
| 4 | Ordered | 79.17% | 1000.00 |

Averages: **79.12% ordered, 84.80% weighted**, an observed **5.68 percentage-point**
cost. Paired costs were 6.30 and 5.07 points. Each measured window had 30 resource
samples and 29 current-state samples; anchor, membership and pinned policy stayed
stable. Receiver counts, CPU means and state samples were independently recomputed.
Two pairs do not establish a confidence interval, maximum capacity, a comparison
with the old optimization's differently instrumented windows, or hardware advice.
The weighted CPU p95 reached 97% in one window; do not assume spare capacity on
another device from the mean alone.

A separate matched A–B–B–A experiment checked the global admission change with
**both versions unbalanced**: old main `e1b612d` versus new RAM admission. CPU means
were 78.93 / 76.97 / 79.55 / 76.90%; variant averages 77.92% old and 78.26% new,
a 0.34-point observed difference. Paired differences had opposite signs (−1.97
and +2.65 points); two pairs do not establish equivalence or a speedup. Every
window completed another 40,000 fresh client/server echoes without errors.
This control is separate from both the PCC comparison above and the historical
native-cycle optimization. Raw counts, actual controller hashes, state samples,
CPU means, parent-image integrity and cleanup were independently verified.

Minimum free memory and logical write-sector deltas are in the machine-readable
results. They are sampled whole-router observations. They do not isolate PCC
memory, measure NAND erase cycles or establish zero flash writes. The admission
entry itself is dynamic and is reconstructed from fresh SLA after reboot.

[JSON with qualified product hashes](benchmarks/weighted-wan-2026-11-08.json) ·
[CSV windows](benchmarks/weighted-wan-2026-11-08.csv)

## Observations and retained failures

API `selected` and enabled/active flags are configuration observations. Baseline
DHCP diagnostics first captured primary traffic near 0.98 seconds; a RAM-admission
probe still captured the previous WAN for two flows, first target near 0.12 s.
The new bounded recovery checks captured all 30 flows on primary from their first
samples, at about 0.085 and 0.090 s. Sampling is not an atomic-cutover guarantee.

Preparation failures remain failed. They include a helper syntax correction,
string versus numeric named arguments, an empty RAM-result polling race, late
capture-buffer draining, kernel capture drops, a wrong container-stop parameter,
an overlapping-policy priority guard and a duplicate log label. Successful
components from those runs were independently reread and reused; successful load
windows were not rerun merely to obtain a cleaner report.

Two material limits were retained: changing WAN kind explicitly reset shared SLA
warm-up and interrupted sessions; one optional-web poll cycle (3/30 requests)
timed out during protected selector reconfiguration. Runtime DHCP renewal and
steady post-apply web were subsequently checked separately. A real uninstall
regression left RAM entries behind; the fix explicitly removes only admission
comments before existing static-list cleanup. Foreign dynamic entries survive.
Raw API omission of an unset `disabled` field was distinguished from an explicit
`false` using actual getters, rather than ignoring a true flag difference.

All owned processes, namespaces, ports and leases were released; both x86 backing
images and the original CHR image remained unchanged. Raw exports, credentials,
licensed images and private traces are not public artifacts.

## Reproduction

- Run SDK tests with `python3 -m unittest discover -s tests -p 'test_*.py'`.
  Run external-tool unit tests from `labtools/` and real Tk checks with
  `python3 tests/gui_balance_smoke.py` (Xvfb on headless Linux).
- On a disposable RouterOS guest with no policy named `nativebalancetest`, upload
  canonical `native/sdwan-admission.rsc`, and
  [native_balance_cases.rsc](../tests/native_balance_cases.rsc) plus its
  [JSON cases](../tests/native_balance_cases.json). Preserve their basenames.
  Import the case script through a temporary self-disabling scheduler with
  `read,write,policy,test,sensitive`; read `sdwanBalanceSelfTestJSON` from
  `/system/script/environment`. Require `pass=true`, `checks=40`, then remove
  temporary files/jobs. This does not test live forwarding.
- The traffic/resource matrix used the existing
  [owned-DUT adapter](../labtools/DUT-ADAPTER.en.md), isolated peers, real echo
  endpoints and private orchestration. Primitives and native cases are public;
  the whole reported matrix is not a single public one-command test.

Neither the original long run nor these short tests certify physical ARM/ARM64,
real LTE modems, the maximum 1024-rule budget or unrelated future functionality.
