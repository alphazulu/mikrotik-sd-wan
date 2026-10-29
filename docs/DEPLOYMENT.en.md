# Protected deployment on RouterOS

[Русский](DEPLOYMENT.md) | English

GUI and CLI `apply` delegate execution to a local RouterOS scheduler. API prepares
files, observes progress and confirms success. The watchdog runs on the router;
closing the configurator does not disable recovery.

## MikroTik documentation basis

The original review was on 23 October 2026 against the current manual (version
7.26 on the site); execution is checked separately on target CHR **7.24.5**.

[Configuration Management](https://manual.mikrotik.com/docs/getting-started/configuration-management/)
describes sequential import, stopping on errors and Safe Mode. WinBox or terminal
Ctrl+X/F4 enables Safe Mode; other sessions' changes also enter its history. The
approximately 100-action history limit can automatically release Safe Mode and
end automatic undo, so it is not a guarantee for a large SD-WAN package. The
[CLI reference](https://manual.mikrotik.com/docs/cli-reference/safe-mode/) documents
reading its state, not a public API setter for enabling it.

[Backup](https://manual.mikrotik.com/docs/getting-started/configuration-management/backup/)
stores binary configuration including sensitive values. Deployment uses a password,
`aes-sha256` and `dont-encrypt=no`. Restore belongs on the same device and RouterOS
version; `load` reboots and scripts need the explicit password. Dude/User Manager
databases are not included. Arbitrary project files are archived separately.

[Files](https://help.mikrotik.com/docs/spaces/ROS/pages/2555971/Files) requires persistent
files under `flash` when that directory exists. Some devices delay writes up to
40 seconds; sudden power loss can leave empty files. This implementation does
not promise power-loss atomicity.

[Scripting](https://manual.mikrotik.com/docs/developer-guides/scripting/) explains
permissions: an ordinary scheduler `/system/script/run` inherits scheduler policy.
Both jobs receive explicit required permissions; `dont-require-permissions` is not used.

## Sequence

1. Check identity, version, interfaces, conflicts, `read,write,policy,test,sensitive,reboot`
   permissions and absence of another unfinished deployment. Exit active Safe Mode first.
2. Save a local `runtime/pre-native-*.json` diagnostic snapshot. Upload a uniquely
   tokenized request and three helper RSC files; this stage does not change routing.
3. Bootstrap archives previous JSON/RSC, registers worker/watchdog and creates
   encrypted `sdwan-before-<token>.backup`. The client verifies watchdog heartbeat
   before uploading the new network package.
4. Upload/read back new JSON and eight core RSC files. Send the arm token only
   after verification. Watchdog launches the worker with a separate scheduler.
5. Worker imports the installer locally. Caught errors fail the transaction.
   Watchdog checks fresh status, revision and the new controller's heartbeat.
6. The configurator opens a **new API connection**, checks identity/revision and
   a working selected default WAN, then sends the tokenized ACK. A surviving old
   TCP session is not proof of fresh reachability.
7. Watchdog commits the transaction and disables both helper schedulers.
   SD-WAN continues independently.

Default confirmation deadline is 120 seconds from preparation. The Python CLI
API permits 30–600 seconds for testing. Controller warmup and API reconnection
must finish within that interval. If all WANs fail SLA, deployment is not
automatically confirmed.

## Emergency recovery

Worker/controller failure, abort, missing timely ACK or reboot before confirmation
makes the watchdog stop the worker/controller, restore previous files and execute
`/system/backup/load`. Binary restore reboots the router. After boot the watchdog
restores files again, marks rolled-back and disables itself. Recovery does not
require installing the previous package through an external API client.

Restore also undoes unrelated changes made **after** the backup. Prevent concurrent
editing during deployment. Reboot disconnects sessions; seamless operation is not
promised. Disk failure, manually disabled watchdog, resource exhaustion and
RouterOS failure are outside this recovery guarantee.

SDK archives previous bootstrap/worker/watchdog before overwriting them, then adds
verified archives to the prepared journal's previous manifest before payload/arm.
Recovery restores eight core RSC files, three deployment RSC files and staging/
active/baseline JSON; previously absent files are removed. Current recovery jobs
remain the recovery mechanism; journal and backup support diagnosis. The binary
snapshot is taken after registering those jobs and before network changes.

`sdwan-deploy-current.json` points to `sdwan-txn-<token>.json`. The journal contains
phase, deadline, recovery reason and backup password. Restrict file/`sensitive`
access. Local `runtime/recovery-<token>.json` is excluded from Git; Windows ACLs
govern NTFS access. Passwords are not printed. Actual CHR checks showed that
`/file add contents=...` logs content, so files are created empty and filled by
a separate `set contents`; that operation avoids logging the password.

Without `maintenance`, archives/backups are not pruned automatically. Optional
`maintenance.backup_keep` performs safe cleanup once after commit. A separate
dry-run/execute CLI exists. The current transaction, recovery points and their
dependencies are protected. See [maintenance](MAINTENANCE.en.md). Local recovery
keys are not deleted automatically.

## Two rollback operations

Emergency deployment rollback restores the binary snapshot immediately before
the last change. Return-to-baseline / CLI `rollback` removes owned SD-WAN objects
and restores original route flags, FastTrack, rp-filter and saved DHCP/PPPoE/LTE
APN routing options. The latter is itself protected by worker/watchdog, backup
and fresh API confirmation. If it breaks management access, the state before
that operation is restored.

## Export and manual maintenance

The standard bundle contains 12 files: JSON plus 11 RSC files (controller,
dataplane, links, overlay, vpn, dns, install, rollback, deployment, deploy-worker,
deploy-watchdog). `sdwan.py` defines `FILES`. Use GUI/CLI for protected deployment:
they archive **before** overwriting the old package and send confirmation.

Direct `/import sdwan-install.rsc` applies rules immediately and bypasses this
protection. It is a low-level lab/local-console method. Add the `flash/` prefix
when present. The controller remains entirely on RouterOS after installation.

LTE baseline is saved per APN profile before changing `add-default-route`. A shared
profile is coordinated once; an unselected modem sharing it blocks deployment.
APN distance, DNS and credentials are not overwritten. Binary emergency restore
returns APN settings with the rest of the configuration.

Address groups, composite selectors and policy order use the same local worker/
watchdog. Preview shows intersections and required outbound reclassification.
Changed selectors/groups/order recreate managed client sessions; native incoming
API/probes are excluded. Unchanged selectors/groups/order preserve sessions on
reapply. Emergency binary restore returns the old groups, rules and package.

Runtime reports, credentials and device snapshots remain private.
[Test reproduction](TESTING.en.md).
