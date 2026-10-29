# Reproducing checks

[Русский](TESTING.md) | English

## Without router access

From project root with Python 3.12:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q sdwan tools configurator.py sdwan.py
python3 sdwan.py --config config/sdwan.json validate
python3 sdwan.py --config config/examples/clients-applications.json validate
python3 sdwan.py --config config/examples/container.json validate
python3 sdwan.py --config config/examples/container-web.json validate
python3 tools/audit_public_tree.py
```

Current candidate baseline passed 391 SDK units; [status/commit](CURRENT-STATUS.en.md)
is tracked separately. Units use temporary files/mocks. Network CHR acceptance
has different filenames and does not run via unittest discovery. Rust/artifact
checks are in [building](BUILD.en.md). Tk needs a display; offline
`python3 tests/gui_wizard_regression.py` uses synthetic data without a router.

## Original five-node lab

Prepare QEMU/WSL using [LAB.md](LAB.en.md), then:

```sh
python3 lab.py up
python3 lab.py verify
python3 sdwan.py --url api://127.0.0.1:18728 apply
python3 tests/native_acceptance.py
python3 tests/connections_acceptance.py
python3 tests/dynamic_wan_acceptance.py
python3 tests/lte_acceptance.py
python3 tests/lte_protection_acceptance.py
python3 tests/protected_deployment_acceptance.py
python3 lab.py verify
```

Run fault suites sequentially after predecessors finish. They modify only test
CHR and restore fixtures. After interruption inspect deployment journal and use
`python3 lab.py heal`; never install over an unfinished transaction.

Additional suites: `tests/policies_acceptance.py`, `tests/policies_protection_acceptance.py`,
`tests/link_resolver_acceptance.py`, `tests/link_reconcile_acceptance.py`. Initial
CHR LTE uses an inventory adapter over actual PPP, not a physical modem test.

`tests/legacy_update_acceptance.py` requires a saved old package path; it is not
standalone quickstart and does not reconstruct missing old source. Protected
deployment `--resume-negatives` only resumes a suite with a retained passing
positive result of the same version.

## Container lab

Separate `runtime/container-lab/project` uses ports +20000 and independent writable
qcow2. Download base with `python3 lab.py prepare`, then use
`python3 tools/container_lab.py up` and `python3 tools/container_lab_native.py`.
Place container7.24.5 NPK at `runtime/container-packages/container-7.24.5.npk` first;
`tools/container_lab_package.py` installs/confirms device-mode via cold boot of
that separate VM only.

Use current container-prepare/apply from [container setup](CONTAINER.en.md).
[container.json](../config/examples/container.json) supplies lab identity/ports/image;
prepare the archive before import.

Core scenarios: container_bridge_acceptance.py, container_provision_acceptance.py,
container_active_acceptance.py, container_fencing_acceptance.py,
container_protection_acceptance.py, container_missing_metadata_acceptance.py,
container_resources_acceptance.py. They require prepared active SDK/owned fixtures
and retain results privately in runtime.

Shadow/image bootstrap scripts reflect prototypes and may require historical file
layouts. Current deployment uses SDK/GUI. Builds need no Docker daemon. Avoid
concurrent timing loads across the two five-node labs.

## Completed milestones

Initial container matrix: 155 Python units, nine Rust units, 50 container CHR
checks, 70 native regressions and four Windows GUI suites. See
[historical scope](CONTAINER-VALIDATION.en.md), [current acceptance](CURRENT-STATUS.en.md).
Do not add milestone counts as unique tests. Raw logs, credentials, screenshots,
recovery archives and exports are private; cloning does not supply these files.
Your own runs create them locally.

## CI

`.github/workflows/ci.yml` checks units/schema/bundles/privacy on Linux/Windows,
offline GUI on Windows, Gitleaks and Rust. It builds six scratch images (base/web
× three architectures) and inspects archives. Actions use full SHA pins; Gitleaks
has version/SHA256 pins. Normal jobs have contents:read only. Explicit v* tags
enable release after gates; only the release job has write permissions. Cloud CI
does not run CHR fault suites or need production router access.

## RAM/web module

`tests/gui_telemetry_smoke.py` checks mock-API configuration/clipboard with
Windows/Tk. [Mandatory coverage](CONTAINER-TESTING.en.md) covers Rust profiles,
main and JS at 100% executable lines/functions, branches separately. Cases include
limits, authorization, actual loopback HTTP and slow headers.

On an already prepared separate container CHR lab with web enabled:

```sh
python3 tests/container_web_acceptance.py --reboot
```

Use `--lab-root /path/to/existing/project` for a separate clean source checkout.
This checks fixed localhost API and identity sdwan-container-edge, never creates
a lab. Temporary SOCKS4 runs only on client CHR via QEMU loopback48881 and restores
settings. Do not compile/run a browser during resource observation: host load can
legitimately change SLA and cause new intent writes. The test stops/starts the
container, disables web temporarily and changes a WAN; `--reboot` reboots edge only.
RAM history is lost. [Measurement method and limits](STATISTICS-VALIDATION.en.md).
