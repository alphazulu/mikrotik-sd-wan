# Mandatory container unit coverage

[Русский](CONTAINER-TESTING.md) | English

Every container change requires checks of both Rust profiles (`base`, `web`),
the main loop in `main.rs`, all library modules and browser JavaScript. The owner
requirement is recorded in the [container instructions](../container-controller/AGENTS.md).

On Linux amd64 / WSL with the project's Rust SDK installed:

```bash
python3 tools/install_container_test_tools.py
python3 tools/container_checks.py
```

Every runtime file requires **100% executable line and function coverage**.
Only test source files are excluded. Branches are reported separately; execution
does not replace assertions about expected results and error handling. Coverage
tools run on the build host, never inside the scratch image. Cargo LLVM Coverage
is pinned to 0.9.1 and its archive is checked with SHA256.

JSON reports, logs and the result live in `runtime/container-unit/` and are not
published as source. `--output` or `SDWAN_CONTAINER_COVERAGE` selects another
directory. `SDWAN_LLVM_COV` selects an installed cargo-llvm-cov of the same version.
Set `CARGO_HOME`/`RUSTUP_HOME` to use an SDK outside the project.

The standard `python3 container-controller/build.py` verifies a passing coverage
result whose SHA256 binds all current container files and validation tools.
Changing source or tests invalidates stale results and triggers another check.
The build utility has no coverage bypass. Each image report retains the covered
source digest.

CI runs the same gate before building six scratch images and saves separate
coverage artifacts, including on failures. Runtime behavior changes also require
actual acceptance of the resulting image on an isolated CHR. Production routers
are not used for these tests.

The latest measured set contains 41 base Rust tests, 75 web Rust tests and eight
JavaScript tests. All runtime files pass line/function thresholds. Cases include
configuration epoch mismatch before heartbeat, every web startup cleanup stage,
bounded JSON decoding, HTTP header write failures and continued operation after
malformed requests. This does not imply 100% branch coverage. JS branches are
measured separately; stable LLVM does not expose a complete Rust branch metric
in the selected mode.

Browser tests also reproduce lost HTTP polling after a fresh snapshot, stale
WAN/VPN/overlay markers, recovery and clearing after logout. An offline Chromium
fixture is separate from unit coverage:

```bash
python3 tests/browser_network_smoke.py --chrome /path/to/chromium --output /path/to/new/report-directory
```

Playwright and Chromium are host tools, not container dependencies. The fixture
retains the production server's CSP and uses synthetic data. Actual API checks
and import of a particular image on CHR remain separate tests.

## Native intent-priority checks

Rust coverage does not replace RouterOS adapter validation. On an already prepared
isolated LTE lab:

```bash
python3 tests/container_priority_acceptance.py --lab-root /path/to/SD-WAN
```

A Git checkout containing historical commit `1b2a9d6` is needed to obtain the old
adapter for regression reproduction. The driver checks fixed loopback QMP/API
ports and owned CHR/x86 names, acquires the lab lock and refuses nodes with active
SD-WAN. It executes unchanged native-selection and generated intent-validation
fragments in RouterOS itself. Route/firewall/scheduler snapshots verify they are
unchanged; two temporary files are removed afterward.

The matrix has 20 cases per device: return to preferred WAN, stale `none`, failed
primary, allowed degraded, healthy before degraded, drain/down, strict mode and
reversed priorities. Old code violates expectations in seven cases per device;
the fix passes all 20 on CHR and all 20 on x86 RouterOS 7.24.5. Separate full
acceptance and forced smoke check real route application, TCP/NAT and preservation
of unrelated connections.
