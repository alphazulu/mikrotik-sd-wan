# GUI wizard and RouterOS API validation

[Русский](WIZARD-VALIDATION.md)

Historical report: counts and fixture state describe this stage. Current acceptance gates: [CURRENT-STATUS.md](CURRENT-STATUS.en.md).

Date: 23 October 2026. Windows Python/Tk 8.6, WSL Ubuntu-24.04, CHR RouterOS 7.24.5.
The external process does not make SD-WAN decisions.

| Check | Result |
|---|---|
| Units: config, discovery, API framing/login/query/errors | 44 / 44 |
| Live CHR: REST/native API return identical interfaces, IPs, gateways | PASS |
| Live CHR: select three WANs and generate without changing active JSON | PASS |
| Live CHR: native-API install, adopt uncommented route, disable FastTrack | PASS |
| Live CHR: native rollback restores original route/FastTrack flags | PASS |
| Windows GUI: connect, six interfaces, explicit three-WAN checkbox selection, JSON/RSC and plan | PASS |
| Windows GUI: four policies retained, no password saved, active JSON unchanged | PASS |
| Lab verification after installation/rollback | 14 / 14 |

Startup does not load lab JSON as device configuration. Reading settings does not
automatically select WANs. This test selected `ether2`, `ether3`, `ether4`; management
`ether1` and LAN `ether5` were excluded. Example output is saved locally as
`config/discovered-<identity>.json`, never published; manual-import bundle:
`build/wizard-sdwan-edge/`.

The deployment scenario created a temporary non-primary default at distance 250
and FastTrack that did not match lab traffic. It checked installer disable and
rollback restoration. `finally` removed objects, restored backup and reinstalled
original `config/sdwan.json`. Three WANs were healthy, loss/delay emulation off,
client priorities restored.

CHR also checked opaque file `.id` values and reading `.rsc` over 4 KiB through
`/file/get value-name=contents`. Rollback accounts for an implicit-main disabled
route returning empty `routing-table`.

## Repeat

In WSL from the project directory:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -q
python3 tests/wizard_acceptance.py
python3 lab.py verify
```

Integration modifies only lab edge and restores it. Do not point it at production.

In PowerShell with the lab running:

```powershell
python .\tests\gui_wizard_smoke.py
```

Normal app launcher: `Configure-SD-WAN.cmd`. The GUI test reads, generates, exports
and plans without installation. Pillow optionally enables window screenshots;
the application does not require it.

Reports:

- `runtime/wizard-acceptance.json`: four live checks.
- `runtime/gui-wizard-validation.json`: Windows GUI.
- `runtime/verification.json`: restored lab state.
- Private `runtime/screenshots/wizard-interfaces.png`.
- Private `runtime/screenshots/wizard-generated.png`.

TLS code checks certificate chain/name, but no real API-SSL server was exercised
in this iteration. Dynamic WANs, VRF and foreign routing marks were outside its
confirmed scope. Later supported methods and current limits:
[CONFIGURATOR-WIZARD.md](CONFIGURATOR-WIZARD.en.md).

## Create configuration error fix, 23 October 2026

`error.png` and saved inventory reproduced empty WAN IP/gateway causing unexplained
`Address cannot be empty`. Validation now names the interface, opens step 1 and
focuses the required field. Recursive routes no longer create false ambiguity
between remote targets and actual gateways. Probe names containing dots from the
screenshot are accepted without renaming.

After the fix: **49 units**, **six Windows GUI checks**. Tests cover missing IP,
ambiguous gateway, correction without reconnect, successful generation with
hostname targets and saved inventory. No network calls or production config
changes. Existing default-route/routing-mark conflict checks remain; fixing an
empty field does not remove those restrictions.

```powershell
python .\tests\gui_wizard_regression.py
```

Pass `--inventory <path-to-discovery.json>` for a specific saved inventory.
Report: `runtime/gui-create-regression.json`; successful creation screenshot:
`runtime/screenshots/wizard-create-regression.png`.

Local `runtime/` reports, credentials and device snapshots are excluded from the
repository. Repeatable verification: [TESTING.md](TESTING.en.md).
