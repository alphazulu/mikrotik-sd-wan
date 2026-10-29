# Device preparation and local controller selection

[Русский](CONFIGURATOR-PROVISIONING.md) | English

Development branch 0.3.0. SD-WAN decisions still execute inside MikroTik: RSC or
a local Rust scratch container. The configurator handles preparation.

## Platform inspection

Connection reads model/architecture, CPU/core count, RAM, disks, packages and
device-mode restrictions. Passwords, keys and serial numbers are not requested
for this assessment. Unavailable fields are unknown rather than successful.

Mode recommendations use `config/platform-benchmarks.json`. A profile needs a
passing hashed report, matching model/CPU/RAM/RouterOS version, controller-source
binding, traffic conditions and no smaller WAN/policy/probe/tunnel workload.
There are currently no complete comparison profiles. The configurator reports
no matching measurements, suggests RSC as an initial choice without capacity
promises and permits manual mode selection.

A functional LTE check or short soak is not throughput measurement. A QEMU result
cannot be transferred to physical ARM/ARM64 based only on an architecture name.

## Packages and features

On the controller tab:

1. Check readiness to inspect packages, permissions, free RAM and storage.
2. Prepare packages/features to download the official `container` package for
   exact RouterOS 7.24.5/device architecture where needed, transfer with SHA256
   verification, reboot normally and recheck identity and active package version.
3. Only required device-mode flags change: scheduler/fetch, container for container
   mode and l2tp for the corresponding WAN. Traffic generator, bandwidth test and
   other optional tools are not enabled automatically.
4. If Fetch is forbidden, request that feature first, before package transfer.
   Device-mode requires physical confirmation using reset/mode or power cycling;
   ordinary reboot is not a substitute. Instructions appear before starting the
   background request. Check again after confirming.

Device-mode intent is saved locally **before** sending. API loss neither establishes
readiness nor triggers a blind retry: another update can cancel an existing pending
request. Read actual flags to establish readiness. Routers with `flagged=yes` are
not automatically repaired.

A temporary script and RouterOS `:execute` run the request in the background;
native API is not held for the entire five-minute confirmation interval. The
launcher is removed by unique name/comment. A named worker remains until completion
is checked, letting readback inspect the real job even if cancellation left an
old RAM marker. Completed workers are removed at recheck. Markers stay in RAM,
without periodic flash writes. Recheck reads markers and actual flags. Failed,
cancelled or expired requests require another explicit action, not an automatic
update. Unknown/transport-lost state is not readiness. Physical confirmation
cannot be replaced by the configurator; ordinary reboot cancels the request.

## Storage and image

Available external ext4/btrfs storage and an internal persistent directory are
offered, including `flash/` when the rest of root is RAM. Availability/free space
are shown. A 16 MiB installation reserve is **not** a performance estimate.
Preparation does not format disks, enable swap or write statistics to flash.

Container preparation chooses base/web and amd64/armv5/arm64 using architecture
and telemetry settings. `config/container-images.json` pins archive SHA256/size,
image ID and exact covered-source digest. A verified local `dist/container` archive
is used first; otherwise the fixed release HTTPS URL is downloaded. **Release
0.3.0 is not published yet**, so automatic GitHub download can return 404. There is
no silent fallback to 0.2.0 or arbitrary latest. Acceptance used exact CI archives.

Transfer uses Fetch and a temporary configurator HTTP endpoint serving one archive
at a random URL to a restricted source, without directory listing. Native API
reads the transferred bytes in chunks and verifies SHA256; binary data are not
decoded as UTF-8. MikroTik must reach the computer, or download that same pinned
public image over HTTPS directly. Verification uses `api://` or `apis://`.
An existing different file at the destination is preserved.

SDK creates a separate local network, API user, read-only mounts and memory limit.
The imported image ID must equal the pinned CI image. Preparation leaves it
stopped; a separate protected deployment applies routing. A matching running
container is not rewritten. Image replacement requires controlled upgrade of
a stopped instance, not a silent filesystem swap.

## Lab validation

- Windows Tk GUI: hardware inspection, missing package/flag visibility, manual
  mode selection, base/web image and directory selection.
- x86 7.24.5 L6: 128 KiB binary roundtrip/SHA256 and no-write repeat transfer;
  official container NPK install, normal reboot and confirmation through a
  separate VM cold boot, with L6 retained.
- Separate x86 7.24.5 L6: background SDK request with actual `fetch=no` returned
  in 65 ms; recheck after API loss took 24 ms without another update. Cold boot
  enabled Fetch; final flags/L6 verified, temporary script and local pending
  file removed. This checks a separate VM, not the owner's physical button.
- Exact scratch CI image transfer/import; SDK `check_ready` verified network,
  user, mounts and stopped state.
- Rust base/web and browser JS coverage measured again: 100% executable lines
  and functions, branches separately, with unchanged measured source digest.

Production MikroTik was not changed. After this milestone, a separate x86 L6
validated three WANs plus USB RNDIS LTE, full switching cycles and real HTTPS
downloads through SD-WAN. These are functional checks, not maximum capacity.
The prepared 150-measurement comparison has not executed; new 48-hour acceptance
is running. [Current status](CURRENT-STATUS.en.md).

[Performance plan](PERFORMANCE-PLAN.en.md) ·
[LTE MBIM/AT field design](../lte-rndis-emu/MODEM-CONTROL-PLAN.en.md) ·
[RouterOS device-mode](https://manual.mikrotik.com/docs/system-information-and-utilities/device-mode/) ·
[RouterOS containers](https://manual.mikrotik.com/docs/containers/).
