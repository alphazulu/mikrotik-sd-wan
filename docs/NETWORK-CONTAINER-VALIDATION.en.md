# Local scratch controller network integration: historical checkpoint

[Русский](NETWORK-CONTAINER-VALIDATION.md) | English

Historical integration of the development image below, not current release
acceptance. See [current candidate status](CURRENT-STATUS.en.md).

Target: existing overlay site-A CHR 7.24.5; the original released container fabric
and production router were untouched. No extra VMs or external runtime controller.
The pinned container package/device mode were enabled on that same CHR, retaining
its existing WireGuard keys, active JSON and both private OSPF paths.

The exact newly built amd64 web scratch image was imported:
`138afec27af41a9c08e7a7effa02ed29770de4cdc8494700407caba7c7945add`.
Its sole filesystem entry is the 803024-byte static binary, running as 65532:65532.
These development archives retain the unreleased build's package version 0.2.0;
they do not replace published release assets.

The new integration wrapper passed **6 checks**, including the separate **7-case
two-VPN matrix**: actual local API control, preserved container isolation after
protected overlay/VPN installation, authenticated bounded web rows, VPN priority/
physical backup/all-down/private TCP survival, stable intent-file bytes, and warm
RouterOS fallback after stopping the container. Temporary localhost DNAT/forward
access was removed, native configuration restored and the container left stopped.

Corrections verified during integration:

- Native overlay/VPN forward accepts now use an anchor below the prepared
  container isolation block. The existing API security gate remains strict.
- Web WAN ACLs are prepared for the complete physical/logical interface set while
  the container is stopped; adding WANs can require that preparation step.
- The traffic fixture permits its two public response source addresses on both
  legitimate OSPF return legs and restores every original peer ACL afterward.
- A logical VPN whose running/address event precedes usable FIB bindings fails
  closed locally. Pending checks poll RAM/readiness without repeatedly rebuilding
  rules, and other WAN processing continues. A changed/reverted geometry must
  clear the pending state and go through fresh probe barriers.

The measured 12-second steady interval kept RouterOS intent-file bytes identical.
Container process `write_bytes` is unavailable on this CHR kernel and is explicitly
reported as unknown; it is not presented as a measured zero. Optional statistics
remain in bounded RAM structures. Source and tests cover the absence of periodic
intent writes, rather than claiming a hardware NAND lifetime measurement.

The preferred path and all standby channels have separate recovery observations.
Existing PPP negotiation/retry timers are preserved; complete standby recovery has
an explicit 180-second test bound. One observed standby SSTP negotiation took about
113 seconds before retry; a later matrix recovered preferred VPN in 10.6 seconds and
all channels in 14.6 seconds. These lab observations are not universal SLA guarantees.

Reports and logs are private runtime files. Repeatable tools:

```text
python3 tools/overlay_container.py package --project-root PRIVATE_ROOT
python3 tools/overlay_container.py prepare --project-root PRIVATE_ROOT
python3 tests/network_container_acceptance.py --lab-root PRIVATE_ROOT
python3 tests/vpn_binding_pending_acceptance.py --lab-root PRIVATE_ROOT
```

The latter is a focused deferred-binding/geometry-reversion regression. Read its
current private report before repeating it; all tools share the fabric lock.
At this early checkpoint, 35 of 44 native contract cases mismatched. Those
historical findings were subsequently addressed by expanded schema/ownership
and lifecycle checks; see [native hardening](OVERLAY-NATIVE-HARDENING.en.md)
and [current status](CURRENT-STATUS.en.md). Matching long acceptance remains
unfinished. This report is not a release claim.
