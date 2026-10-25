# Strict probes, WAN maintenance and branch overlay

This iteration adds points 2, 3 and 7 accepted by the owner, plus an isolated
long CHR soak. v0.2.0 remains the last completed release. Production RouterOS
and private exports are never used as test targets or publication inputs.
Runtime control stays on RouterOS/Rust inside MikroTik; no external controller.

## Delivery order and acceptance

1. Extend probe JSON/GUI with explicit HTTP codes, expected DNS A answers and
   bounded expected HTTP body/path. Preserve old defaults and HTTPS certificate
   validation. DNS/code checks reuse Netwatch. Body fetch must run separately
   from SLA/control, with bounded concurrency, timeouts and RAM-only results;
   pin requests to each WAN and reject redirects/oversize/truncated responses.
   Compare cached evidence with link/config generations. Add read-only MTU/MSS
   diagnostics for PPPoE/VPN; do not silently rewrite user queues or TCP rules.
   Verify wrong DNS, captive portal, TLS error, hangs and WAN-isolation on CHR.
2. WAN `admin_state=enabled|drain|down`, default enabled. Drain excludes WAN
   from new admission but preserves healthy marked old sessions using existing
   per-WAN tables, including strict-policy flows. Optional bounded drain deadline;
   physical/SLA failure and forced down retire exact owned outbound marks.
   Account for retained marks after policy moved to another WAN, late cleanup,
   controller restart, disabled/native fallback and dynamic address changes.
   Existing ingress/management symmetry and probe traffic remain independent.
   Implement identical Rust selection and RouterOS enforcement; stale intent
   cannot override administrative exclusion. Live TCP tests prove old-flow
   survival/new-flow selection and exact timeout/emergency cleanup.
3. Overlay is a first-class part of this iteration, not deferred behind PCC/QoS.
   Owner specifically requires CGNAT at both ends and has no final addressing.
   Support site-to-site through a reachable public CHR/MikroTik hub: each site
   initiates independent WireGuard paths over its WANs, with keepalives. A direct
   CGNAT-to-CGNAT path is not assumed. Public infrastructure is emulated on CHR;
   no VPS purchase/provisioning and no real router changes are authorized here.
   Each router keeps local control; the hub terminates/transits tunnels.
4. A separate 5-node CHR fabric: hub, site A/B, NAT ISP A/B; both sites have two
   CGNAT WANs, no direct inbound port mapping. Isolated disks/loopback ports;
   existing native/container fabrics stay intact. Check host capacity/ports
   first and never create duplicate running fabrics/tests.
5. One WireGuard interface/peer per path, distinct ports/link networks. Generate
   private keys on router, keep them out of JSON/repo; exchange public keys.
   Preparation is separate from protected route install, with explicit image/
   filesystem rollback limits documented as for the container backend.
6. Pin outer UDP by owned local listen port before generic output routing;
   source NAT and reply path match each WAN, including dynamic WAN bindings.
   Probe each inner link via dedicated lookup-only table + blackhole, never
   through an alternate tunnel. Inner data/OSPF probes bypass Internet policies.
7. Optional isolated OSPFv2 instance/area, explicit local prefix export only,
   default origination disabled. Export filter rejects all other connected
   networks. Protect every remote site prefix with a main-table blackhole at
   high distance to avoid default-WAN leaks when all tunnels are withdrawn.
   Overlay SLA controls owned OSPF templates/costs; failed paths withdraw rather
   than staying usable with high cost. No mutation/migration of existing OSPF.
   Prefer tunnels based on inner SLA + physical readiness, independently of
   general Internet target availability. Configurable conservative tunnel MTU;
   explicit optional MSS clamp restricted to owned WG paths.
8. GUI/JSON model, plan/inspection, node-local rollback, diagnostics and bounded
   web telemetry for admission/drain/overlay. Show required public hub/addressing
   rather than pretending CGNAT traversal is guaranteed. Validate collisions,
   prefix overlap, existing marks, template ownership and secret handling.
9. Tests: parser/unit + actual RSC import, native/container parity, OSPF neighbors,
   path-bound capture, CGNAT endpoint changes, WAN failures/recovery/all down,
   stable inner TCP while outer path changes, MTU and unrelated-route isolation.
   Then 48–72h soak with bounded RAM/logging and incremental private report;
   only one running soak, restart safely after quota/continuation checkpoints.
10. Update documentation/roadmap, audit publication (including all history and
    image layers), CI/release and sync reviewed source to project root. Physical
    ARM/LTE is a separate acceptance constraint, not fabricated by CHR tests.

At 95% live Codex quota: checkpoint docs/HANDOFF.md and progress.json, arm only
the existing SD-WAN continuation; preserve unrelated owner-paused schedules.

## Implementation checkpoint (2026-10-25)

- 247 Python tests and 13 Rust base /30 Rust web tests pass. Drain has six real-CHR TCP
  acceptance cases plus3 single-WAN closure cases: existing/new flows, strict policy, cancellation, emergency
  retirement after selection moved, deadline, and subsequent channel failure.
- Strict HTTP uses two RAM-only Fetch workers with separate deadline guards.
  RouterOS 7.24.5 exposes execute/script frames as separate job records; owned
  job cancellation matches complete trace components. A dribbling endpoint is
  cancelled while API reads remain responsive (observed maximum 15 ms).
- Native Netwatch supports expected DNS A addresses and custom status codes.
  Fetch body/path verification supports 2xx responses only; configure native
  Netwatch for an expected non-2xx code. Redirects are never followed. TLS trust
  validation applies only to HTTPS, because RouterOS rejects that option on HTTP.
- A separate five-node overlay fixture now exists: one single-WAN public hub,
  two dual-WAN sites and two shared CGNAT routers. NAT-A also routes the emulated
  public Internet subnet of NAT-B; it does not translate NAT-B's public source.
  Both sites can reach the same hub IPv4 address through either provider. There
  are no inbound mappings through the CGNAT routers. Only CHR is provisioned.
- Overlay schema/key/prefix/MTU checks are implemented in an isolated module;
  native overlay install/reconciliation and GUI integration are still pending.
  See OVERLAY-DESIGN.md for the concrete contract, integration and fixture notes.
- Protected SDK deployments now use independent temporary staging directories,
  preventing concurrent configuration of different routers from sharing payloads.

## Additional accepted scope

The owner requests existing WireGuard, L2TP, SSTP and OpenVPN exits as ordinary
optional VPN WANs. Source/destination independently accept IPv4/CIDR or existing
MikroTik Address Lists, with AND across axes. The same policies order physical
and VPN WANs, including the general Internet default. No separate feature switch
or routing engine. The GUI edits ordinary WANs and policies; legacy JSON migrates
on output. Current unified checks:256 Python,88 live-list contract,18 VPN contract,
6 real-CHR TCP/routing checks,5 offline and4 read-only live GUI checks. Further
full-branch acceptance is still pending. See VPN-EGRESS-VALIDATION.md.

The first native overlay slice is now active on all3 lab routers: four healthy
tunnels,8 Full neighbor entries, real inner TCP survival across failure/failback
and exact remote-prefix blackhole with both underlays down. Additional hardening,
GUI/project workflow, external VPN egress and the final long soak remain pending.

Current GUI checkpoint: per-router topology editing, local disabled WireGuard key
preparation and public-only exchange,5offline+4live Windows/Tk checks. Native/API
full-default guard5checks, DHCP/PPPoE parent changes2each, active VPN cold restart3,
WireGuard hostname rotation2 PASS. Bounded current drain/VPN/overlay web rows have
30 Rust web tests and3offline Chromium checks; six scratch archives are built.
Actual new-image CHR parity and native overlay hardening remain before the final soak.
