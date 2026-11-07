# Local Rust controller in a container

[Русский](CONTAINER.md) | English

The controller runs **on MikroTik itself**, in a `FROM scratch` image containing
one static Rust/musl executable. There is no distribution, shell, database,
shared library or SDK. Base also has no web server; optional RAM statistics use
a separate [web image](STATISTICS.en.md). Two read-only directories supply settings
and password.

Rust selects WANs by readiness, SLA and policy order. RouterOS measures links,
supports DHCP/PPPoE/LTE/APN, marks connections, validates decisions and applies
routes/NAT. The same single RouterOS script/scheduler retains warm native fallback:
container/API loss returns selection to the native algorithm. SD-WAN needs no
external runtime service.

## Configurator workflow

1. Prepare RouterOS **7.24.5** and its matching `container` package. Enable
   `container=yes` in device-mode with required physical confirmation; GUI does
   not bypass that confirmation.
2. Select arm64, armv5 or amd64 for the corresponding platform. GUI preparation
   can verify/transfer a pinned archive automatically. Unpublished 0.3.0 needs
   its matching local CI archive. Manual `.tar.gz`/`.tar` upload through WinBox
   Files also works. ARM cross-build is not physical hardware acceptance.
3. Run `Configure-SD-WAN.cmd`, connect, select WANs and generate configuration.
   Select local Rust container on the controller tab.
4. Choose an unused private `/30`, storage directory and archive filename. GUI
   adds the subnet to `local_networks` so API replies reach veth through `main`.
   Preparation rejects overlap with existing addresses/main routes, including
   branch aggregates.
5. Prepare container infrastructure: bridge/veth, access rules, dedicated API
   user, files and mounts. Import leaves it stopped; this action does not install
   SD-WAN policies.
6. Review the plan, then install. Local worker creates an encrypted backup,
   applies the package and starts the container. Watchdog requires a live
   container lease and fresh API confirmation. Failure/timeout restores old
   configuration/files and reboots RouterOS.
7. Diagnostics shows the actual actor: container or fallback script. A stale
   snapshot does not establish container operation. WAN/SLA/groups/policies use
   the same configuration mechanisms as RSC.

Native mode is independent: select RouterOS script and deploy. After confirmed
backend change, SDK stops its container and disables autostart; storage is retained.

## Storage readiness

Directory choices use actual disk `mount-point`. Slot `usb1` can differ from
the `/file` directory: a disk mounted as `data` can use `data/sdwan-container`.

Before download, SDK requires a mounted writable ext4/btrfs disk with at least
16 MiB free. `mount-filesystem=yes` alone does not establish mount success;
actual `mounted` is needed, or a `/file` entry of type `disk` for older API
projections without that field.

Disabled, disconnected or read-only disks do not fall back to internal free-space
checks. Unknown disk/file inventory leaves readiness unconfirmed. Readiness
reports the issue and preparation stops before image download/transfer/import.
Disks are never formatted automatically.

See primary MikroTik [Disks](https://manual.mikrotik.com/docs/hardware/disks/)
and [`/disk`](https://manual.mikrotik.com/docs/cli-reference/disk/) references.
They also describe newer releases. RouterOS 7.24.5 retains slot-name fallback
without `mount-point` and `/file` confirmation without `mounted`.

## JSON and CLI

Add this fragment to the existing configuration; WAN/SLA/policies remain in the
same file. No password is included:

```json
{
  "controller_backend": "container",
  "container": {
    "subnet": "172.31.255.0/30",
    "storage": "disk1/sdwan-container",
    "image_file": "disk1/sdwan-controller-arm64.tar.gz",
    "poll_ms": 1000,
    "memory_max_bytes": 16777216
  }
}
```

Explicitly include the container subnet in `local_networks`. Polling accepts
500–2000 ms; memory limit accepts 8–64 MiB. A 16 MiB limit is not preallocated RAM.
The complete separate-CHR example is `config/examples/container.json`.

```sh
python3 sdwan.py --config config/examples/container.json --url api://127.0.0.1:38728 --credentials runtime/container-lab/project/runtime/credentials.json --expect-identity sdwan-container-edge container-prepare
python3 sdwan.py --config config/examples/container.json --url api://127.0.0.1:38728 --credentials runtime/container-lab/project/runtime/credentials.json --expect-identity sdwan-container-edge plan
python3 sdwan.py --config config/examples/container.json --url api://127.0.0.1:38728 --credentials runtime/container-lab/project/runtime/credentials.json --expect-identity sdwan-container-edge apply
```

These connection paths belong to the project's isolated lab. Use your device's
URL, identity and separate credentials file. Production MikroTik was not used
for this validation.

Preparation checks ownership and existing permissions. It does not overwrite
foreign bridge/veth/container/mount-list objects with reserved names. The API user
is restricted to the container address and explicit `read,write,policy,test,sensitive,api`
permissions; other permissions are disabled. RouterOS 7.24.5 needs these to read
public globals and write intent. API-service prefixes are read from `available-from`
or legacy `address`. Existing management prefixes are preserved, adding only
the container `/32` when needed; readiness verifies access again.

RouterOS API permissions are broad, not per-path ACLs. Native API is used inside
closed veth networking, whose forwarding is blocked. Explicit web enablement
adds exact LAN/source/port allowances and established replies, keeping WAN closed.
The container needs no Internet or DNS requests.

## WAN selection and recovery

The standard package has 11 RSC files and JSON. Container mode derives controller,
installer and watchdog variants; there is no second route writer. Shared
dataplane handles inbound connections from every WAN and replies through their
corresponding tables. Switching removes only affected owned conntrack entries.

Intent contains boot fence, configuration generation, revision, random process
nonce and increasing sequence. The adapter rejects missing/invalid fields,
old generations and foreign owners. A requested WAN is checked against **current**
SLA before application. Configuration change advances generation even with the
same revision; reboot changes boot fence.

Heartbeat uses a separate rule and a dynamic RouterOS address list with a six-second
timeout: RAM, without periodic flash writes. The process confirms heartbeat first,
then writes intent. Stable selection does not rewrite the file; unavailable
heartbeat does not cause writes every poll. Lease expiry returns selection to
native logic; actual time also depends on scheduler/load. Ownership change with
the same route does not reset client connections.

New image versions require reimport of the stopped owned container; preparing an
existing root directory does not replace its contents. WAN/SLA/policies use normal
JSON deployment without rebuilding. Infrastructure preparation is separate; a
failed deployment restores its immediately preceding state. Return-to-baseline
restores original SD-WAN network state and stops the owned container, retaining files.

## Minimal image build

See [pinned SDK and release archives](BUILD.en.md).

```sh
python3 container-controller/build.py
```

The script uses the local Rust SDK, `Cargo.lock`, LTO, stripping and static musl.
It checks ELF architecture and absence of PT_INTERP/PT_DYNAMIC, creates Docker-save
tar/gzip without a Docker daemon, and records sizes/SHA256 in
`dist/container/build-report.json`. Docker contexts are generated under
`dist/container/{amd64,arm64,armv5}/`, for example:

```sh
docker build --platform linux/arm64 -t sdwan-controller:arm64 dist/container/arm64
```

Contexts contain only the executable, Dockerfile and `.dockerignore`. No settings,
passwords, source, toolchain or caches are included in the image.

## Validation and limits

See [current status](CURRENT-STATUS.en.md) and [initial acceptance](CONTAINER-VALIDATION.en.md).
Static/DHCP/PPPoE/LTE/APN use shared native resolver/dataplane; their earlier full
matrix is in [policy validation](POLICIES-VALIDATION.en.md). CHR does not replace
physical ARM/LTE or long hardware/load checks. IPv6, DPI and automatic migration
of existing OSPF/VPN rules were not added; foreign-mark guards remain.

Manufacturer references: [Containers](https://manual.mikrotik.com/docs/containers/),
[Device-mode](https://manual.mikrotik.com/docs/system-information-and-utilities/device-mode/),
[API](https://manual.mikrotik.com/docs/developer-guides/api/). Current manuals describe
7.26; project execution is pinned to 7.24.5.

Runtime reports, credentials and device snapshots stay private.
[Test reproduction](TESTING.en.md).
