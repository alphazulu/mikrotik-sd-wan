# Strict HTTP probes

[Русский](STRICT-PROBES.md) | English

Use an exact response body or a specific path when an open TCP port alone does
not prove that a WAN can reach the required service. These checks participate
in the existing WAN quorum and SLA selection, including VPN WANs.

This fragment shows the relevant fields; it is not a complete configuration:

```json
{
  "health": {
    "strict_probe_interval_seconds": 10,
    "strict_probe_timeout_ms": 2000
  },
  "probe": {
    "name": "service",
    "type": "https-get",
    "host": "service.example.com",
    "port": 443,
    "http_path": "/health",
    "http_codes": [200],
    "http_expected_body": "healthy\n"
  }
}
```

Place the probe inside the appropriate WAN's `probes` array. Body comparison is
exact, including the newline. The body limit is 1024 UTF-8 bytes. HTTPS verifies
the certificate; redirects are not followed. A body/path check requires 2xx
expected codes. A plain native HTTP status probe can use other HTTP status codes.
The origin path must start with one slash, with at most 256 characters.

A body expectation, including an empty string, or a path different from `/`
uses an asynchronous RouterOS fetch worker. Netwatch supplies its TCP primer;
the open port alone cannot satisfy that strict probe. The worker binds to the
current WAN source. Its evidence also carries the generation, exact probe
signature, gateway, Netwatch ID and slot token. A response from an old job,
source, probe object or configuration cannot qualify a replacement check.

## Scheduling and capacity

Both controller modes share two HTTP worker slots globally. The one-second
dispatcher releases a completed slot on the next tick and cancels its old
worker/timer jobs before reuse. Unfinished requests retain their deadline;
overdue requests produce failure. Results stay in RAM. The dispatcher and
controller reject overlapping named script runs, recognizing both name and
internal-ID job representations observed on RouterOS 7.24.5.

`strict_probe_interval_seconds` accepts 5–300 seconds, default 10.
`strict_probe_timeout_ms` accepts 100–2000 milliseconds, default 2000.
There can be at most 16 strict HTTP probes across all WANs. Validation also
requires:

```text
ceil(strict_probe_count / 2) * (ceil(timeout_ms / 1000) + 1) <= 2 * interval_seconds
```

For a 2000 ms timeout, 12 probes fit the default interval; 13 do not. Sixteen
require an interval of at least 12 seconds. This is a configuration admission
bound, not a guarantee of scheduling latency on every device. CPU contention,
API polling and slow targets still need testing on the intended platform.
Do not duplicate targets to inflate quorum: host/type/port must be distinct.

Evidence older than `2 * interval_seconds + 3` seconds is rejected. That limit
is unchanged by early slot release. Failed or stale evidence cannot become UP
merely because the underlying TCP port responds.
Age is sampled from the current RouterOS uptime after reading the evidence.
A worker can finish after the controller samples the start of its cycle; using
that older cycle timestamp would incorrectly reject a fresh result as future
evidence. Actual future timestamps are still rejected.

## Reproduce the narrow dispatcher contract

Use a disposable CHR 7.24.5 with an empty script/scheduler/Netwatch baseline and
identity `sdwan-strict-contract`. Expose its API only through a loopback forward.
The test imports helpers, creates controlled named jobs and disabled Netwatch
objects, and enables one loopback TCP primer to test evidence age. Discard the
test VM afterward; this is not a deployment test on an
existing SD-WAN router.

```sh
python3 tests/strict_dispatch_acceptance.py \
  --api-url api://127.0.0.1:37474 \
  --credentials /path/to/private-credentials.json \
  --output /path/to/private-result.json
```

Credentials use `{"username":"admin","password":"YOUR_LAB_PASSWORD"}`.
Keep credentials and raw results outside the public tree.

The 32 actual RSC cases cover completed/unfinished slot ownership, late timers,
all callback identity fences, obsolete Netwatch IDs, overdue failure, exact job
name cancellation, the two-slot bound, overlapping dispatchers and the native
controller's actual entry guard. A test-only scheduling barrier also verifies
that a concurrent callback survives result pruning and that an edited expectation
triggers an immediate check. The report records both the original source hash
and the instrumented test payload hash. Three cases check a commit newer than
the caller's cycle timestamp, expired evidence and actual future evidence.
The runner and the baseline/candidate comparison passed on CHR 7.24.5. Earlier
baselines exposed the slot and reconciliation defects; the latest comparison
isolated the clock defect, with only the delayed fresh commit failing in the
baseline and all 32 cases passing in the candidate.
This contract does not establish six-WAN freshness, all VPN failover scenarios,
hardware performance or a 48-hour soak result.

[Configuration](CONFIGURATION.en.md) · [Live changes](LIVE-CONFIGURATION.en.md) ·
[RouterOS scripting manual](https://manual.mikrotik.com/docs/developer-guides/scripting/)
