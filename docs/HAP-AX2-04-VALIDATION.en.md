# Container 0.4.0 acceptance on hAP ax2

[Русский](HAP-AX2-04-VALIDATION.md) | English

On November 13, 2026, the published **ARM64 base image 0.4.0** passed functional
acceptance on a dedicated hAP ax2, model C52iG-5HaxD2HaxD, running RouterOS 7.25.1.
The controller ran locally in an unprivileged scratch container as UID
65532:65532. RouterOS performed SLA checks and native fallback decisions.

The container package was already installed. This validates installation from a
stopped prepared state, rather than upgrading an active production 0.3 controller.
RouterOS 7.25.1 used the SDK's explicit lab opt-in; this does not authorize arbitrary
RouterOS versions. See the [contract and coordinated upgrade guide](RAM-CONTROL.en.md).

| Check | Confirmed result |
|---|---|
| Functional run | 26 checks |
| Independent replay | 72 unique TCP/UDP flows across nine phases; echo replies, full conntrack tuples, marks, NAT and both directions on the external capture |
| Policies | Default WAN1 with WAN2 reserve; a client pinned to WAN2; source IP combined with a MikroTik destination Address List |
| Failure | Unreachable probe resources with the WAN link up, and virtual-interface loss; failover and return |
| Connections | Old WAN1 bindings retired by full tuple; unaffected WAN2 TCP/UDP retained across six phases without reconnecting TCP |
| Fallback | Stopping the container returns control to RouterOS; starting it restores accepted Rust decisions |
| Reboot | Actual physical hAP reboot, new boot fence and fresh TCP/UDP replies |
| Configuration | Same-revision priority update advances generation and changes the selected WAN |
| Restoration | The encrypted original backup was actually loaded; original files, ten static-configuration groups and the stopped previous container were verified |
| Cleanup | Temporary interfaces/processes removed; namespace ownership journal clean |

## Fixture and limits

The hAP has one physical uplink. Two virtual WANs and a LAN were carried over
local Linux namespaces, VXLAN and WireGuard from a computer on the same switch.
Generators and responding servers ran outside the MikroTik. Image transfer also
used the private fixture network and was SHA256-verified on the router.

WSL's MTU was 1280. The initial virtual-tunnel MTU of 1370 lost large packets;
diagnostics retained successful small and failed large probes. Changing only
owned temporary interfaces to WG MTU 1200 and inner MTU 1140 allowed both clients
to pass TCP/UDP and DF pings at that chosen MTU. Host MTU, routes and firewall were
unchanged. This is not a maximum path-MTU measurement.

These are virtual WANs sharing one physical transport. The result does not qualify
two independent ISPs, LTE radio/SIM, every VPN protocol, raw Ethernet capacity or a
long 0.4.0 soak. This run used two static WANs and lab SLA thresholds of RTT 500 ms,
jitter 250 ms and loss 5%.

The initial [load and storage-write comparison](HAP-AX2-04-PERFORMANCE.en.md) has 19 usable steady-path windows out of 27; eight negative UDP stress windows remain recorded. The earlier
[RAM versus file control](RAM-CONTROL-VALIDATION.en.md) validates that particular
intent transport: 0 versus 24 sectors for six updates. It does not imply zero
RouterOS writes overall or measure flash erase cycles.

## Result pins

SDK source: `048604048a2427b415680820b7a35d13c3b3beb8`.
Exact container source digest with 100% executable line/function coverage:
`40bdb3f9e3e1bf0747fe835f35556cba3c05fbc9eff56a7877ee1ae1d86ff37e`.
Published ARM64 base gzip archive SHA256:
`932b49fd6d6ef377c44b126439048309e607907afedd57367638a2e6858e7db2`.
Imported image ID:
`1ac43fa631b9c1e6542eb0701c97eca9f530ee833fc2962efba6f4d80ee1b100`.
Functional-run report SHA256:
`f085d4da553543b99802cf5db8c197e80d3cc2ec3300dec9a91c70244c896e8d`.

Raw captures, management addresses, credentials, backups and keys remain private.
Restore used the same device and RouterOS version, following the
[MikroTik backup guide](https://manual.mikrotik.com/docs/getting-started/configuration-management/backup/).
Original files were saved separately from the binary backup. The previous rootfs
was retained; atomic rootfs rollback is not claimed.
