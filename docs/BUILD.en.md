# Building the minimal container

[Русский](BUILD.md) | English

Published archives are available in [GitHub Releases](https://github.com/alphazulu/mikrotik-sd-wan/releases).
They are Docker-save tar/gzip archives for RouterOS import, not CHR disk images.
Download CHR and the RouterOS `container` package separately from MikroTik.
Candidate 0.3.0 is not a published release yet; see [current status](CURRENT-STATUS.en.md).

## Pinned SDK

The build is checked on Linux x86_64 with Rust **1.99.1**, musl target libraries
and bundled `rust-lld`. Scripts use the SDK in local `runtime/toolchains` without
changing the system PATH. From a clean checkout:

```sh
mkdir -p runtime/toolchains
curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs -o runtime/toolchains/rustup-init.sh
RUSTUP_HOME="$PWD/runtime/toolchains/rustup" CARGO_HOME="$PWD/runtime/toolchains/cargo" sh runtime/toolchains/rustup-init.sh -y --no-modify-path --default-toolchain 1.99.1
RUSTUP_HOME="$PWD/runtime/toolchains/rustup" CARGO_HOME="$PWD/runtime/toolchains/cargo" runtime/toolchains/cargo/bin/rustup target add x86_64-unknown-linux-musl aarch64-unknown-linux-musl armv5te-unknown-linux-musleabi
python3 tools/install_container_test_tools.py
python3 tools/container_checks.py
python3 container-controller/build.py
```

SDK/crate installation needs Internet access; the deployed controller does not
need it for its runtime dependencies. `Cargo.lock` pins dependencies and Cargo
uses `--locked`. Other SDK versions and build-host architectures have not passed
separate acceptance. Node.js is required on the build host for browser JavaScript
checks. See [coverage requirements](CONTAINER-TESTING.en.md).

For a single architecture:

```sh
python3 container-controller/build.py --architectures amd64
```

Defaults build two profiles (`base`, `web`) for three architectures. `--profiles base`
selects the minimal controller; `--profiles web` selects embedded HTTP. All six builds
produce `dist/container/build-report.json`, tar/gzip archives and Docker contexts.
The script checks ELF machine and absence of `PT_INTERP`/`PT_DYNAMIC`. Each image has
one static executable, mode `0555`, UID `65532:65532`, without settings, passwords,
shell, toolchain or shared libraries.

## Docker and artifact checks

The main build does not need a Docker daemon. A generated context can be used
after cross-building:

```sh
docker build --platform linux/arm64 -t sdwan-controller:arm64 dist/container/arm64
```

After building both profiles for all three architectures:

```sh
mkdir -p runtime
python3 tests/container_artifact_acceptance.py
```

Checks compare tar/gzip/ELF/image-config SHA256 values, single-layer rootfs, UID
and Docker contexts. `dist/` is generated locally and excluded from Git. Release
archives include `SHA256SUMS` and a build report. Absolute toolchain/crate paths
can appear in ELF diagnostic strings, so local builds need not be byte-identical
to CI. Release sizes come from their build report. The exact CI web amd64 image
has separate actual CHR acceptance.

CI also runs this before publication:

```sh
python3 tools/release_checksums.py --check-catalog
```

It requires exactly six unique architecture/profile pairs and compares the
configurator catalog against actual gzip hashes/sizes, image IDs, covered-source
SHA256 values and release version/URLs. Stale pins stop CI before release artifact
creation. A local build with different absolute paths can legitimately fail
`--check-catalog`, because that catalog describes exact CI archives. Without the
flag, the command still creates checksums for local archives. Catalog equality
does not replace CHR acceptance of the exact image.

## Rust unit tests

```sh
RUSTUP_HOME="$PWD/runtime/toolchains/rustup" CARGO_HOME="$PWD/runtime/toolchains/cargo" CARGO_TARGET_DIR="$PWD/runtime/container-build" RUSTC="$PWD/runtime/toolchains/cargo/bin/rustc" runtime/toolchains/cargo/bin/cargo test --locked --manifest-path container-controller/Cargo.toml
```

Run Rust tests with `--features web` for the web profile. Windows CI also checks
`tests/gui_telemetry_smoke.py`. `dist/container/web-arm64` contains a separate
`/sdwan-controller-web`; there are no separate shell/assets files in the layer.
HTML/CSS/JS are embedded in the executable. `build-report.json` records profile/version.

[Container installation, API and limits](CONTAINER.en.md).
