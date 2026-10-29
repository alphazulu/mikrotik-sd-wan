# Native SD-WAN validation — 23 October 2026

[Русский](NATIVE-VALIDATION.md)

Historical report: counts, file sets and lab state describe this stage. See [current status](CURRENT-STATUS.en.md) for current checks and pending release gates.

Controller: RouterOS script + scheduler only, on CHR 7.24.5. Python deployed,
injected failures and read results; it did not select channels.

## Results

- 15/15 CHR integration scenarios passed.
- 19/19 configuration validation tests passed.
- Native fractional conversion passed: 0.125 ms → 125 µs; 0.5% → 50 basis points;
  15.0 ms → 15000 µs.
- DNS + certificate-checked HTTPS to mikrotik.com: 2/2 client addresses.
- Windows GUI: forms, JSON read and validation; screenshot
  `runtime/screenshots/configurator.png`. GUI REST connection and plan command
  were checked separately.

## Measurements from one run

| Scenario | Result |
|---|---|
| Client .101 | Actual WAN1, confirmed by ISP counters |
| Client .102 | Actual WAN2 |
| Strict .103 | WAN3 only; its failure does not permit bypass |
| One of three HTTP targets fails | Two votes retain quorum; WAN stays healthy |
| ISP1 forwarding drop while gateway replies | Failure detected and WAN2 selected in 4.052 s |
| Failed WAN probes after switching | Remain down; do not escape through backup |
| WAN1 recovery | Approximately 6.031 s recovering before return, including hold-down |
| WAN2 +55 ms each direction | RTT 119.592 ms, jitter 23.380 ms: voice degraded, default healthy |
| All WANs link-down | All policies select none; user Internet unavailable; management REST available |
| Frozen ICMP measurements | Stale timeout excludes WAN; old metrics are not healthy |
| Repeated poll of same Netwatch data | Does not increase good-window count |
| Invalid strict in staging JSON | Does not itself change active config; native installer rejects before mutation |
| CHR reboot | Files, script and scheduler persist; channel control recovers locally |
| Native rollback | Original routes/rules restored; baseline verification 14/14 |
| Reinstall | SD-WAN and policies restored without duplicate objects |

Times describe one run and are not guaranteed SLA. The model uses Netwatch windows;
this fixture's ICMP traverses virtual ISP to a QEMU host alias, while HTTP targets
run on the test host. Real independent providers/resources and prolonged load
were not verified in this historical iteration.

## Artifacts

- `runtime/native-acceptance.json`: all results and counters.
- `runtime/native-numeric.json`: numeric helper executed in RouterOS itself.
- `runtime/internet.json`: client DNS/HTTPS.
- `runtime/verification.json`: base version/connectivity check aware of native mode.
- `runtime/pre-native-*.json`: pre-install snapshots.
- `runtime/native-plan.txt`: managed-object plan.
- `runtime/gui-connection-smoke.txt`: CLI commands invoked by Windows GUI.

All injected faults were removed, as was temporary client address .103. Its policy
remained for a future client. The controller was installed and enabled on edge.

Further stages/limits: [roadmap](../ROADMAP.en.md),
[NATIVE-CONTROLLER.md](NATIVE-CONTROLLER.en.md).

Local `runtime/` reports, credentials and device snapshots are excluded from the
repository. Repeatable verification: [TESTING.md](TESTING.en.md).
