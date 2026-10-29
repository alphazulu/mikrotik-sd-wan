# RAM/web 0.2.0 acceptance

[Русский](STATISTICS-VALIDATION.md)

Historical report: counts and fixture state describe this stage. Current acceptance gates: [CURRENT-STATUS.md](CURRENT-STATUS.en.md).

Checks ran on a separate amd64 CHR RouterOS 7.24.5. Production MikroTik was neither
connected nor changed. Eight native RSC files remained unchanged at this stage.

## Code and artifacts

- 193 Python units: settings, private CIDR limits, WAN/bridge rejection, swap,
  exact firewall scopes and ordering.
- 12 Rust base tests and 27 with `web`: WAN choice, codec, bounded observer API
  transcript, queues, rings, epoch, secret redaction, maximum export size, HTTP
  authentication/origin/methods/queries/deadlines.
- Six new offline Windows/Tk web checks and six previous creation-wizard checks.
- Six scratch images: base/web × amd64, ARM64, ARMv5; one static ELF,
  UID 65532:65532, one layer, no dynamic loader, settings or secrets.
- Tar/gzip/binary/image-config SHA256 and prepared Docker contexts checked.
  Imported CI web-amd64 image ID matched its GitHub Actions build report. All six
  images were byte-identical across two independent PR CI builds.

## CHR

`tests/container_web_acceptance.py --reboot` passed 11 checks:

1. LAN access, static assets, bearer; incorrect methods, Origin, keys, token-query
   and excessive history rejected.
2. SLA, RX/TX, policies and export available; JSON excludes API password, web token
   and owner credentials.
3. Direct HTTP from ISP/WAN reaches owned firewall deny.
4. Regular polling/export for 66.2 s grows RAM history, leaves checked files
   unchanged and keeps RSS below 2 MiB.
5. WAN link failure/recovery during slow HTTP headers preserves the lease;
   observed switching was 0.91 s after administrative link-down. This is not a
   remote-outage detection guarantee; SLA timers determine that.
6. Stopping the container leaves working native fallback.
7. Restart clears RAM history and resumes container control.
8. SIGKILL causes lease expiry and native fallback.
9. Runtime off removes web settings/ACL and separate observer API session;
   routing remains active and active JSON unchanged.
10. Re-enabling reuses the separate token and creates fresh RAM history.
11. Reboot changes the boot fence, clears history and automatically starts the
    configured web/controller.

## Memory and writes

Scenario: three WANs, two SLA profiles, four policies, sample10 s/history360,
existing Netwatch probes, HTTP status every 2 s and periodic export.

| Metric | Result |
|---|---:|
| Duration | 66.2 s |
| Process RSS | 851968–856064 bytes (832–836 KiB) |
| RouterOS container `memory-current` | 598016–724992 bytes |
| Checked file metadata/content | Unchanged |
| `/proc/self/io` on this CHR | Unavailable, `write_bytes=null` |

`memory-current` and RSS use different accounting and are not interchangeable.
This short sample establishes neither the maximum for 16 WANs × 600 points nor
physical ARM behavior. Point/event/string/response/queue bounds are separately
implemented and unit-tested. Unavailable `/proc/self/io` is not a measured zero.

Exact before/after metadata and SHA256 were compared for five files: active JSON,
intent, mounted controller settings, API password and web token. No WAN/owner
selection changed in the stable window. Actual transitions can separately write
intent, as in the base controller. This does not establish absence of every write
by all RouterOS components or user disk logging.

The collector makes only bounded identity/interface-print queries, verified by a
unit transcript. Statistics do not call file/set or open files for writing.
Settings/secrets mounts are RO and container logging is disabled. Preparation
requires no enabled swap; `swap-max=1` adds a limit because 0 means unlimited
on RouterOS 7.24.5.

## Browser

A separate actual Chrome pass over the LAN path checked three WAN cards, four
policies, SVG chart, JSON download to the computer, no localStorage/sessionStorage
data, clearing the token field and logout. At 390 px width the page had no
horizontal overflow and no JavaScript errors. HTML/CSS/JS are embedded in the
binary; no CDN is used. Events are limited to a 360 px-high internally scrolling
panel.

Raw reports, browser downloads, screenshots, credentials and recovery archives
remain in private local `runtime/`, excluded from source/releases.
