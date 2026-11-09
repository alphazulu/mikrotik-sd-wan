# Recovery after a power interruption

[Русский](POWER-LOSS-RECOVERY.md) | English

**Bounded x86 RouterOS 7.24.5 acceptance passed:** initial installation,
update, confirmed-copy recovery and fresh traffic were checked in RSC and local
container modes. [Method, results and limits](POWER-LOSS-VALIDATION.en.md).
This is not a guarantee of atomic writes under every power failure.

## Data sources

| Object | Purpose |
| --- | --- |
| `sdwan-config.json` | Staging for the next import; its presence does not confirm a configuration |
| `sdwan-active.json` | Applied configuration, including a candidate in an unfinished transaction |
| `sdwan-confirmed-a.json`, `sdwan-confirmed-b.json` | Alternating storage for the confirmed copy |
| `sdwan-confirmed-record` under `/system/script` | Small record containing token, identity, revision, size, checksum and selected copy name |
| `sdwan-txn-<token>.json` and encrypted backup | Deployment journal and complete device configuration rollback |

The `sdwan-confirmed-record` source starts with `#` and is read as JSON data.
It is never executed. A second file is not automatically an eligible recovery
source: the selected copy must match the record. MD5 detects accidental
corruption; it does not authenticate data.

## Installation and confirmation

RouterOS owns every runtime decision and recovery action. The configurator
prepares files, observes and confirms using a fresh API connection.

1. Bootstrap archives old files and creates an encrypted backup. The watchdog
   waits 45 seconds before allowing the next stage.
2. The client seals the journal with the full archive map, including previous
   recovery framework files. Another 45 seconds separate this write from package replacement.
3. The worker applies rules. Once the controller is ready, the watchdog writes
   the configuration to the unselected copy and waits 45 seconds.
4. Only then does the configurator verify the result through a fresh API
   connection and send ACK. The watchdog publishes the small confirmation record
   and marks the transaction committed.

The three barriers reserve 135 seconds in addition to the transaction deadline
(120 seconds by default). Storage waits do not require a long API call.
Closing the configurator does not automatically start the next stage.

## After restart

The dynamic `sdwan-deployment-boot` entry disappears on reboot. New-boot detection
therefore does not depend solely on comparing uptime. The one-shot
`sdwan-deploy-startup` job runs the watchdog even if preparation was interrupted
before its periodic scheduler was enabled.

An unfinished transaction is not automatically confirmed after restart. The
controller closes admission for new Internet connections while the watchdog
restores previous files and configuration. If backup was not ready and no network
package replacement had started, preparation files are restored. Following a
full backup restore, files receive 45 seconds before rollback completes.
SLA then warms up again; conntrack survival across reboot is not claimed.

For a completed transaction, a corrupt or empty `sdwan-active.json` is recovered
only from the copy selected by the confirmation record. Identity, revision, size
and checksum must match. Staging is never used for this recovery. If both active
and the selected copy are corrupt, admission closes and an error is reported;
the system does not guess which remaining file to activate.

An older manual installation without a confirmation record does not seed a copy
from staging. The next successful protected apply creates it.

## Storage writes and validation limits

Copies and metadata are written during explicit configuration deployment or
recovery. Normal SLA polling does not rewrite them. The settling timer is held
in RAM; each watchdog tick does not restart the copy write.

The official [Files documentation](https://manual.mikrotik.com/docs/system-information-and-utilities/files/)
describes up to 40 seconds of write-back caching on some NAND devices. Persistent
files use `flash/` when that directory exists. The 45-second barrier provides a
margin over that description; it is not a system `fsync`.
[Scripting](https://manual.mikrotik.com/docs/developer-guides/scripting/)
documents `:convert ... transform=md5`; execution was checked on 7.24.5.
The current manual describes 7.26, so version claims remain separate.

The x86 checks observed lost contents after immediate cuts following
`/file/add contents=...` and a repeated file write. The checksum detected
intermediate contents. A copy that passed the 45-second barrier survived a
forced QEMU termination and restored active while staging differed. This does
not validate ARM/NAND behavior or physical power controllers.

Interrupted installation, update and confirmed operation were checked in both
modes, with fresh TCP/UDP traffic, LTE, VPN, OSPF, parent integrity and cleanup.
The failed early-backup run remains a separately failed result.

See [protected deployment](DEPLOYMENT.en.md) and
[previous WAN/LTE/VPN/OSPF functional validation](MIXED-WAN-VALIDATION.en.md).
