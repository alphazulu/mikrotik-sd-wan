# Container–RouterOS exchange in RAM

[Русский](RAM-CONTROL.md) | English

In 0.4.0 the container communicates selected WANs through a dynamic Address List
entry. Current decisions no longer use `sdwan-container-intent.json`. The controller
remains on MikroTik; shared RSC logic measures SLAs, validates selection, applies
routes and retires the relevant conntrack entries.

## Contract

One inbox: `list=sdwan-container-intent`, `address=127.0.0.1`, `dynamic=yes`.
Its comment contains JSON bounded to 32768 UTF-8 bytes. Creation requires an
observed RAM heartbeat. Updating an existing ID requires the exact list/address,
a dynamic entry and no duplicates. Static or ambiguous entries are not overwritten.

Protocol 2 retains boot/configuration/revision, instance/sequence, observation-age
and six-second heartbeat fences. A new process cannot displace a different live
owner. RouterOS revalidates the requested WAN against current SLA and priority;
a stale intent cannot retain a healthy backup after primary recovery.

Stable selection does not update the inbox. Missing or malformed inbox structure
relinquishes ownership. Invalid JSON, old generations and foreign commands do not
replace an accepted plan. Invalid structure also removes write permission from
published metadata: the process waits on its existing API session instead of
reconnecting every poll. Heartbeat expiry returns selection to native logic.

Reboot removes the dynamic entry. After fresh SLA observations the container gets
a new boot fence and recreates its inbox. Intermediate decisions need no flash
checkpoint. Dynamic entries are not configuration-persistent and disappear after
reboot according to the [MikroTik manual](https://manual.mikrotik.com/docs/firewall-and-quality-of-service/firewall/address-lists/).
Tests additionally exercise the actual lab RouterOS version.

## Upgrading from protocol 1

The 0.4.0 image and its RSC adapter form one protocol version. With mismatched
versions, the process waits without heartbeat or intent writes while native
selection retains availability. This is a safe intermediate state, not successful
activation of the new container. The watchdog cannot confirm deployment without
an accepted live lease.

Use a separate maintenance stage for image replacement:

1. Save configuration and backup, then use the normal protected transaction to
   switch the same SD-WAN configuration to `controller_backend=routeros`.
2. Stop the old managed container. Retain its archive, directory and configuration
   for recovery. Preparing an existing container does not replace its rootfs.
3. Reimport with a new archive filename and storage directory. Remove only the old
   stopped owned container record and its two readonly mounts in `sdwan-controller`.
   Leave unrelated objects to their owner: the SDK deliberately refuses occupied
   or ambiguous reserved names.
4. Use matching 0.4.0 SDK, SHA256 catalog and images. Prepare the container, then
   apply `controller_backend=container` through the usual protected transaction.
   Confirmation requires current SLA and a live accepted protocol-2 lease.

Retain the legacy intent file until the upgrade is confirmed: an older
image/adapter may need it during version rollback. It can then be removed.
This change does not add automatic rootfs replacement or atomic image rollback;
network-configuration deployment and rollback retain the existing watchdog.

## Remaining persistent writes

The RAM inbox removes intent-file updates. JSON changes, backup/installation,
static-route changes, disk logging, swap and RouterOS housekeeping remain separate
possible writes. New API logins can also cause housekeeping writes; keep a single
persistent session and separate login controls from NAND measurements. Sector
counters include delayed writes, rather than identifying only the command running
when the counter is read.

Eliminating static-route switching is a separate investigation:
[permanent routes and RAM admission](RAM-ROUTE-DESIGN.en.md). It is not enabled in
the 0.4.0 production dataplane.
