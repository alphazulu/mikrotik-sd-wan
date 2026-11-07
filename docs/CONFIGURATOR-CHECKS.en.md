# Configurator readiness scenarios

[Русский](CONFIGURATOR-CHECKS.md) | English

Static review of existing checks at base commit `37a68a9`, dated 29 October 2026.
The six suites below contain **52 test methods**, some with several subcases.
This is not a unique network-test count or a new execution on the documentation
branch. See [current status](CURRENT-STATUS.en.md) for the overall SDK result.

| Area | Existing checks | Suite |
|---|---|---|
| Platform, packages, resources | Missing fields/permissions, unsupported architecture, insufficient RAM, disabled/mismatched packages, absent measured profiles | [8 methods](../tests/test_platform_support.py) |
| Storage | Actual mount, read-only/disabled/unmounted state, unknown free space, unsafe paths, duplicate mounts, no download before readiness | [12 methods](../tests/test_storage_readiness.py) |
| Device-mode | Required flags only, intent saved before sending, API loss without retry, expiry/cancellation, stale RAM marker, owned-worker-only removal | [10 methods](../tests/test_device_mode.py) |
| Transfer and import | SHA256, partial transfer, different existing destination, invalid URL/path, exact image ID, no repeated write, uncertain Fetch state | [12 methods](../tests/test_provisioning.py) |
| LTE/RNDIS | Router-owned dynamic DHCP retains LTE/APN; user DHCP conflict is not disguised as a permission error; original inspection errors remain | [3 methods](../tests/test_rndis_inventory.py) |
| Foreign mangle | Explicit drafts, unchanged rules, raw/notrack and incomplete inventory still blocked, persisted sidecar warnings, fresh preflight before payload | [7 methods](../tests/test_migration.py) |

The review inspected assertions and blocking order, not method names alone.
No need to duplicate existing tests was identified for these scenarios at this
stage. The table does not claim complete coverage of all GUI states. Actual Tk
suites, saved API snapshots and CHR validation are tracked separately.

For behavior changes, add a reproduction of a specific missing case and assert
its result: not ready before download/mutation, preservation of foreign files,
no duplicate update, and accurate diagnostics. This does not replace actual
RouterOS import/recovery checks.
