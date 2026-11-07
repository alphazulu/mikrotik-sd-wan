# Connection marking and protected deployment: results

[Русский](CONNECTIONS-VALIDATION.md)

Historical report: counts, file sets and lab state describe this stage. See [current status](CURRENT-STATUS.en.md) for current checks and pending release gates.

23 October 2026. Lab only: five CHR RouterOS **7.24.5** nodes under QEMU/KVM in
WSL2. Production MikroTik was unchanged. RouterOS scripts execute the controller,
SLA decisions and emergency recovery.

| Check | Result |
|---|---:|
| Units: validation, state, discovery with actual API projection, marking plan | 62 PASS |
| Protected deployment, missing ACK, error after API disable | 3 PASS |
| Extra WAN IPs, local access, rp-filter, recovery after controller error | 4 PASS |
| Previous-package install and failed-migration recovery | 2 PASS |
| Native SD-WAN: SLA, quorum, faults, hold-down, strict, stale, reboot, baseline rollback/reinstall | 15 PASS |
| Real connections, WAN/DNAT symmetry, scoped conntrack and failback | 8 PASS |
| REST/API discovery, wizard generation/install/rollback | 4 PASS |
| Final lab connectivity and versions | 14 PASS |
| Windows GUI: original configuration-creation error, offline | 6 PASS |
| Windows GUI: connect, select three WANs, export eight files, plan | PASS |

There were 50 CHR checks, with units and GUI recorded separately. Machine summary
`runtime/final-validation.json` links reports and the seven native RSC SHA256 values.
All seven installed edge RSC files were compared with source. Final logs are
`runtime/final-*-output.txt`; units: `runtime/unit-final-output.txt`.

## What connection tests establish

- A remote source receives replies from three main and three alias WAN IPs.
  Replies also work with no selected SLA default while the underlay remains
  reachable, and LAN access works after reinstall.
- A long-lived incoming native API session through standby WAN3 stays on WAN3.
  DNAT to client102 replies through WAN3 although its outgoing policy prefers WAN2.
- Two simultaneous TCP/NAT streams from .101 and .102 receive different policy/WAN
  marks. Voice SLA degradation moves only .102 and removes its old entry while
  retaining .101 and incoming management. Recovery also removes the fallback entry.
- Silent WAN1 blackhole removes .101's old NAT state; its replacement uses WAN2.
  Returning .101 from WAN2 does not remove .102's connections on that same WAN.
  Probes retain separate marks.

Conntrack deletion sends no TCP RST and cannot migrate TCP between different public
NAT IPs. Applications must reconnect. Pre-installation unmarked/FastTracked flows
need a separate migration decision; they are not automatically cleared in bulk.

## What deployment tests establish

1. Installation runs through a local scheduler; ACK is sent after opening a new API
   connection. The new backup password does not appear in the RouterOS log.
2. The installer session is closed without ACK and new package files differ. The
   watchdog independently restores the encrypted backup, reboots CHR and restores
   all seven previous core/config files with exact content comparison.
3. The installer deliberately adds an unrelated address-list entry, disables API
   and fails. Without external rollback commands, API, previous files and config
   recover; the added entry disappears.
4. A new-controller failure restores previous source, adopted route/FastTrack flags,
   strict rp-filter and scheduler. Failed migration from an older package without
   dataplane restores that controller, removes new mangle/list objects and deletes
   the previously absent RSC.

This iteration fixed a CHR hang during routing-rule move/rollback/reinstall: owned
local bypass rules are recreated before an explicit first `.id`, without move.
Reinstall, baseline rollback/reinstall and alias WAN IP local access were checked
afterwards. An empty archive manifest was also found and fixed; completeness is
now checked before uploading the new package, and failure tests compare whole
changed files.

The GUI formerly omitted `comment` from its API mangle whitelist and misidentified
owned rules as foreign. The field and a `.proplist` projection regression were
added; genuinely foreign marks still blocked generation at that historical stage.
Current draft handling: [MIGRATION.en.md](MIGRATION.en.md).
Live Windows GUI read settings, generated output and showed the plan without
changing active router JSON. A final automatic screenshot was unavailable with
the desktop locked; functional checks ran independently of it.

## Final state and limits

Edge revision `lab-v1`: default/client101 → WAN1, client102 → WAN2,
strict103 → WAN3. SLA healthy, no emulator faults. No temporary test firewall,
NAT, IP, script objects or fetch jobs remained. SD-WAN scheduler was enabled;
installation worker/watchdog disabled after commit. Backups and logs were retained.

Scope: CHR 7.24.5 and admin/full. Real RouterBOARD, a minimal separate role,
power-loss flash behavior and performance require separate acceptance. This
report describes the static iteration; static/DHCP/PPPoE follows in
[DYNAMIC-WAN.md](DYNAMIC-WAN.en.md). PCC/weights, QoS and IPv6 remain roadmap items;
VPN overlay was outside this historical iteration and has later development
checks. See [roadmap](../ROADMAP.en.md). Recovery and binary-backup limits:
[DEPLOYMENT.md](DEPLOYMENT.en.md).

Local `runtime/` reports, credentials and device snapshots are excluded from the
repository. Repeatable verification: [TESTING.md](TESTING.en.md).
