# Long CHR acceptance

[Русский](NETWORK-SOAK.md) | English

`tools/network_soak.py` runs on Linux/WSL and observes an existing isolated
RouterOS 7.24.5 lab. MikroTik makes routing decisions. Fixed loopback APIs,
identity/version checks and both lab.lock/network-soak.lock protect ownership.

Complete matching functional gates first: DHCP/PPPoE, outer UDP retirement,
reapply and rollback. A clean tested Git commit, imported stopped web image and
prepared four-WAN/two-overlay SiteA configuration are required:

```bash
python3 tools/overlay_container.py prepare --project-root /path/to/private/project
```

Check no run already exists:

```bash
python3 tools/network_soak.py status --lab-root /path/to/private/project
```

Short driver smoke uses separate reports and **is not long acceptance**:

```bash
python3 tools/network_soak.py run --lab-root /path/to/private/project --smoke-seconds 180 --sample-seconds 10
```

Main acceptance is 48 hours: first 24 hours the same configuration uses warm
RouterOS fallback, then local container starts without reinstalling rules.
Before measurement, all four WANs must stay healthy for 60 seconds within a
separate 240-second warmup. Total can increase to 72 hours. Run one driver in
a durable background session and retain PID:

```bash
python3 -u tools/network_soak.py run --lab-root /path/to/private/project --hours 48 --native-hours 24
```

Three original TCP sessions continuously carry ordinary Internet, Address-List
VPN WAN and private branch traffic. Driver checks original/reply TCP/NAT tuples,
increasing counters and one active HTTP request without reconnect. API IDs can
change on a live flow and are recorded separately. Checks include preferred WANs,
selected-channel SLA, all four SiteA reports, eight OSPF neighbors, fresh controllers
and unchanged source/libraries/configs/intent within each phase. Container startup
may claim ownership once; this is recorded before establishing a new intent base.
Initial preparation/final restoration mutate configuration; periodic measurement
only reads APIs.

Unselected backup SLA changes are recorded as quality/events, not automatically
called controller failures. Selected WAN1/VPN1, private paths and three continuous
flows keep strict criteria. Driver does not change product/lab SLA thresholds.

Container phase also checks authenticated web, 12-point history bound, exact image
ID and RSS. Default RSS budget is 32 MiB (`--max-rss-mib`), an acceptance limit,
not physical ARM/LTE memory promise. Process write counters are checked only if
the kernel exposes them; unavailable remains unknown. Stable intent does not
prove no hardware flash writes anywhere in RouterOS.

Private report `runtime/overlay-lab/runtime/network-soak.json` and JSONL samples
live on the host. Duration uses the actual driver's monotonic clock; VM uptime
or old reports do not count. Errors retain pass:false. Success requires complete
both-phase duration and successful configuration restoration. Smoke uses
network-soak-smoke filenames.

`failure_context` retains exception type/message, file/line/function traceback,
even for empty asserts. Last-web diagnostics retain request time/status, previous
successful snapshot time, actor/stale/age, transport/overlay counts and bounded
path/resource fields, never headers/tokens. `cleanup_failure_context` separately
records recovery errors. A previous successful snapshot is not treated as a
fresh reply to a failed request. Diagnostics do not weaken acceptance criteria.

SIGINT/SIGTERM stop container, remove temporary traffic/rules and restore original
config saved in private network-soak-before.json. After crash/host power loss,
inspect PID, locks and temporary objects before another run. Never duplicate over
unfinished restoration. Owner can stop at any time. Do not change the tested Git
tree or run mutating tests on this fabric during acceptance.

Image ID, commit, duration, sample count, RSS range and I/O-counter availability
are recorded. Until the actual 48–72 hours complete, long acceptance remains
unfinished and release is not published.
