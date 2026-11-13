# RAM-channel acceptance for 0.4.0

[Русский](RAM-CONTROL-VALIDATION.md) | English

Completed November 13, 2026. Container intent now uses a dynamic Address List
instead of a file. [Contract and upgrades](RAM-CONTROL.en.md).

| Check | Result and scope |
|---|---|
| Python SDK | 430 unit tests |
| Container | 100% executable lines/functions in each base/web Rust file, `main.rs` and browser JS; branches reported separately |
| Packaging | Six scratch images: amd64, arm64, arm/v5, base/web; one static binary, UID 65532:65532 |
| RAM primitive, CHR 7.24.5 | 10 checks: dynamic flag after comment updates, UTF-8, 32768 bytes, ambiguity, disappearance after reboot |
| Native adapter, CHR 7.24.5 | 27 fence/replay/release, missing/static/ambiguous inbox, old-protocol and legacy-file isolation checks |
| Real container on CHR | 26 startup/failover/return/fallback/restart/reboot/generation/version-mismatch checks |
| Independent traffic replay | 24 TCP/UDP flows across primary, backup, return, native fallback, reboot and rollback: replies, full CT tuples, marks and NAT |
| Exact CI image | 11 additional checks and 20 TCP/UDP flows on CHR 7.24.5: protected native maintenance, hash/ID-verified import, failover, return, native fallback, restart and reboot; independent CT/reply/mark/NAT replay |
| Broken adapter | Missing lease metadata prevents commit despite ACK; rollback/reboot restores exact files and active configuration |
| Dedicated hAP ax2, 7.25.1 | Transport control: six RAM updates produced 0 sectors, six file updates 24 sectors; persistent API session, configuration preserved |

Fresh package installation, cold-boot device-mode confirmation, verified import
and protected deployment ran on a new CHR. Extended acceptance used a separate
COW copy of the prepared disk. Parent images were unchanged; processes and
namespaces were released. Production MikroTiks were not modified.

## Executed image behavior

Two static WANs and two clients exchanged actual TCP/UDP echo replies. One policy
prefers the primary WAN; another is pinned to backup. Internet loss with the
interface still up and subsequent recovery update accepted intent. The observer
waits for a validated Rust decision rather than counting native selection alone.

Cases cover a foreign instance, replacement with a static inbox, heartbeat loss,
recovery by the same process, stable API sessions, and priority changes advancing
generation without changing revision. Real 0.3 image/new-adapter and new-image/
old-adapter combinations retain native fallback without file intent or reconnect
churn. Restoring a matching pair restores Rust decisions.

Normal reboot recreates the inbox with a new boot fence. A deliberately broken
adapter triggers watchdog rollback despite ACK. Previous files and active JSON
were compared, followed by new TCP/UDP replies. This validates network-configuration
rollback rather than atomic rootfs upgrading.

## Physical write control

The dedicated hAP model and serial fingerprint matched private authorized state.
Gateways, bridge, interfaces, rules and containers were not reinstalled. Equivalent
intent-shaped JSON was updated in a separate test list and test file. This is
API-transport acceptance, **not a new full ARM64 SD-WAN image acceptance**.

One API session served both phases. Preparation was followed by 60 seconds of
settling and a 40-second idle window. Each phase performed six updates ten seconds
apart, then observed delayed writes for another 50 seconds. The reported
`write-sect-since-reboot` delta was **0 for RAM, 24 for the file**. Temporary
objects were removed; before/after static-configuration hashes matched.

This confirms removal of one specific intent-write source. It does not establish
zero RouterOS writes overall, physical erase-cycle counts or flash lifetime.
Installation/backup, static-route changes, housekeeping, disk logging and swap
remain separate sources.

## Sources and retained failures

Exact container source SHA256:
`40bdb3f9e3e1bf0747fe835f35556cba3c05fbc9eff56a7877ee1ae1d86ff37e`.
It binds coverage, six builds and the accepted executable source. The release
catalog and `SHA256SUMS` pin individual archives. Final CHR report SHA256:
`1dd558642ffee36fca4d8c201fbbdf06ab5ff784f91f5fe3db4304535cce82d0`.
Raw evidence remains private.

Lab-built and CI images differ byte for byte. The release catalog pins the six
archives from CI run `43359176132`; separate acceptance executed this exact CI
image rather than the lab binary. Accepted amd64/base image ID:
`3666fdfaad0134e58da75b025611095c08b73d7f2087e51c11bea5af6c3e67bd`.
Gzip archive SHA256: `9453689636aa651c1504ad46b059eeeb2d348a5476406d6b78264366b325dd57`.
Separate CI-image report SHA256: `c3debbc57c6580833a58ef3afaf96b7b07b8c84b743c62614f4e3481a521afd8`.


Failed attempts were retained and excluded from PASS: empty inbox results through
`print as-value` in the first adapter; singleton device-mode lists; an occupied
lab lease; premature conntrack reads; cold-start observations; confusing native
selection with accepted Rust intent; and starting before cleanup finalized.
Final checks use `find/get`, live sockets, bounded polling and actor/lease/cleanup
barriers. An independent pass replayed 24 complete CT tuples/echo outputs, source
and archive pins, and the cleanup journal.

Native dataplane and SLA algorithms were unchanged. Earlier 48-hour acceptance,
150 performance measurements and mixed LTE/VPN/OSPF tests retain their own 0.3
source pins; they were not repeated for 0.4.0.
[Routes without enable/disable](RAM-ROUTE-DESIGN.en.md) describes a separate
validated prototype with measured delays, not a new production route backend.
