# Minimal local SD-WAN controller

[Русский](README.md) | English

Rust/musl, `FROM scratch`, one executable without a shell, distribution or database.
Separate read-only mounts supply configuration and password. The controller runs
on MikroTik itself; RouterOS measures SLAs, applies decisions and retains native
fallback.

The `base` profile contains no HTTP server. Optional `web` embeds the UI and bounded
RAM history/events; the module is disabled by default. There is no database, HTTP
access log, CDN or automatic history persistence. See [statistics](../docs/STATISTICS.en.md).

From the project root: `python3 container-controller/build.py`. Every change requires
exact-source coverage for both Rust profiles, `main` and browser JS before building:
[commands and requirements](../docs/CONTAINER-TESTING.en.md). Archives, SHA256 values
and Docker contexts are generated in `dist/container/`; an external Docker daemon
is not required. ARM builds exist; physical hardware acceptance is still pending.

Candidate 0.3.0 and its long acceptance are described in
[current status](../docs/CURRENT-STATUS.en.md). The earlier completed milestone is
described in [historical acceptance](../docs/CONTAINER-VALIDATION.en.md); it does not
replace current checks. [Installation, JSON/GUI and limits](../docs/CONTAINER.en.md) ·
[Building](../docs/BUILD.en.md).
