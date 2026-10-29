# Next statistics iteration

[Русский](STATISTICS-NEXT.md) | English

**Design only; no current container changes.** The implemented web interface and
settings are described in [STATISTICS.md](STATISTICS.en.md). This page does not
claim new API/GUI fields are implemented and does not change current long acceptance.

## Separate measurements

| Group | Proposed metrics |
|---|---|
| Whole MikroTik | CPU, free/total RAM, uptime, sample time and freshness |
| Container process | RSS, CPU ticks and derived utilization only with a known tick frequency and valid interval |
| WAN | RX/TX, RTT, jitter, loss, carrier/IP, SLA and probe age |
| Policy | Selected WAN, reason, last transition time, maintenance/drain |

Process CPU must not be labeled router CPU. Unavailable counters use `null` and
an explanation. Reboot, epoch changes and byte-counter resets must not produce
negative or enormous rates. Users see units and measurement periods; charts
distinguish missing data from zero.

## Budget and retention

All new data remain in bounded RAM buffers and are disabled with the module.
There is no database, background checkpoint, access log or periodic flash write.
An explicit user export creates a file only on the operator's computer.

A shared low-frequency API resource snapshot, for example every ten seconds,
should serve all readers. Browser polling must not increase API request frequency
or delay WAN selection. History size, replies and reader count have explicit
limits. Sampling/memory budgets need measurement; these are design values only.

## Switching and acceptance

Controller decision time is separate from actual client traffic interruption.
The latter requires an external observer and cannot be inferred from a selection
event alone. Chart scaling must not hide missing samples.

Before enabling: 100% executable line/function coverage for both Rust profiles,
`main` and JS; branches reported separately; API errors, stale data, resets and
limits verified with assertions. Then check the browser, exact image on isolated
RouterOS, polling impact on WAN decisions and memory. The current test package
stays frozen; new runtime needs its own evidence rather than inheriting the old
version's PASS status.
