# Power interruption recovery validation

[Русский](POWER-LOSS-VALIDATION.md) | English

**Bounded validation passed.** RouterOS 7.24.5 recovered confirmed configuration
and rolled back unfinished installations/updates in both RSC and local Rust
scratch-container modes. The production MikroTik was excluded.

## Lab and source

A disposable x86 L6 with 1 vCPU and 1024 MiB, a CHR on the same version and external
Linux clients. Static WAN, actual USB RNDIS `lte1` with DHCP controlled through APN
and a 60-second lease, an existing WireGuard VPN and two WireGuard/OSPF paths.
Policies cover default traffic, an LTE-pinned client, source IP combined with a
destination Address List, and unmarked private traffic without NAT.

A cut is `SIGKILL` of the test-owned QEMU process only. The next boot uses a new
child overlay backed by the stopped disk. This differs from `/system/reboot` and
does not remove power from the storage host. The x86 IDE attachment retains
`format=qcow2,bus=0,unit=0,media=disk`.

Executable files were qualified at tree
`ab1c7342a1899f182a29880769d6c938f81cb61f`. The published change contains the same
code; subsequent edits concern documentation. Rust and browser code are unchanged;
their digest is `0772c14a13574b95c77faef9347bdaeb09e34afb835c73ec19aa0e11ca60db9d`.
Earlier long-duration and resource tests were not repeated.

## Results

| Scenario | RSC | Local container |
| --- | --- | --- |
| Initial installation interrupted before ACK | Baseline restored; no confirmed copy published | Same |
| Successful installation and fresh traffic | Fresh SLA and correct TCP/UDP paths | Same, with the local container active |
| Empty active, staging with another revision, then cut | Exact confirmed copy restored; staging never activated | Same |
| Unconfirmed preference change VPN → WAN1, then cut | Full rollback and fresh flows through the previous paths | Same |
| 60 seconds after recovery | Checkpoint files and metadata unchanged | Same |

A separate preparation cut occurred after journal pointer publication but before
enabling the periodic watchdog or creating backup. Only a delay was added to the
test bootstrap to reach that window. On boot the one-shot entry aborted preparation:
baseline remained intact, with no controller or new confirmation record. This is
a separate preparation check, not an additional full container series.

Independent replay confirmed:

- 56 TCP/UDP flow correlations with conntrack, NAT and packet captures;
- 69 coherent actual-byte snapshots, including 64 after rollback;
- 36 snapshots showing differing staging remaining inactive;
- 26 observations in two one-minute windows and the exact previous confirmation record;
- unchanged source and parent images, with resources released for both modes.

Private traffic required Full OSPF, an installed route and actual exchange; a
neighbor entry alone was insufficient. Fresh SLA windows were required after
restart. Conntrack survival across reboot is not claimed.

## Retained failures and limits

The original main left active empty. A repeated-copy write retained seven
intermediate bytes instead of the last version; checksum validation refused it.
An early rollback candidate received `file much too short` while loading backup.
These failed runs remain in the evidence. They led to a separate file write and
storage barriers; their results were not retrospectively relabeled PASS.

Run 203 passed the initial native checks, then its observer stopped on an old
controller message immediately after `rolled-back`. Scoped repeat 207 waited up
to 10 seconds only for that expected message to clear; another or persistent
error failed validation. It took 5 snapshots for RSC and 3 for the container,
followed by fresh SLA and traffic checks. Overall run 203 remains failed; its
successful components are identified separately.

The device write counter increased by 40 sectors in each one-minute window.
In RSC this was a single step followed by a flat value. An unchanged checkpoint
is not a claim of zero writes across RouterOS or a flash-lifetime measurement.

This result does not qualify physical storage-host power loss, a particular
NAND/ARM platform, LTE radio/SIM, or recovery when both active and its selected
copy are corrupt. That last case closes admission and requires verified recovery;
arbitrary staging or another slot is not automatically selected.

[Recovery mechanism](POWER-LOSS-RECOVERY.en.md) · [Deployment](DEPLOYMENT.en.md) ·
[Earlier mixed scenarios and orderly restarts](MIXED-WAN-VALIDATION.en.md).
