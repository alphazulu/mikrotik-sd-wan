# SD-WAN diagnostics in the GUI

[Русский](DIAGNOSTICS.md) | English

The diagnostics tab is available after connecting to MikroTik, even before
generating another configuration. It reads the router's active state, not unsaved
editor changes. Closing the GUI does not stop the controller. The initial milestone
used 147 unit tests, 121 CHR checks and five Windows GUI suites; those are historical
results, not acceptance of the new candidate. See [historical results](POLICIES-VALIDATION.en.md)
and [current status](CURRENT-STATUS.en.md).

## Displayed information

- WAN channels: interface, static/DHCP/PPPoE/LTE type, APN, current IP/gateway,
  default-profile SLA state, RTT/jitter/loss, quorum and sample age. Carrier/IP
  alone is not presented as healthy Internet access.
- Policies and selected WANs: rule order, selectors, SLA, prefer/strict mode,
  allowed WANs and current selection reason. Rules fully shadowed by an earlier
  rule are marked; selecting a WAN for a policy does not prove a client flow matches it.
- SLA and recovery: state/verdict for each profile/WAN pair, good/bad windows,
  remaining recovery windows and hold-down. Violations show metric and threshold.
- Switching history: the last 100 RouterOS RAM events for SLA, policy/WAN, session
  changes and reclassification. Uptime comes from the router; UTC estimates use
  the computer clock and do not replace time synchronization.

Refresh reads an API snapshot. Optional automatic refresh runs every five seconds
while the tab is open and no other operation is active. Snapshots also age while
automatic refresh is disabled. Connection changes or API errors remove old data;
stopped schedulers and stale snapshots are not shown as current healthy state.

## Flow explanation

Enter client IP, destination IP, TCP/UDP/ICMP, required ports and actual ingress
interface. The policy explanation describes a **new outbound connection** using
the active configuration and last WAN state. Local destinations show a `main`
bypass. Port/interface selectors need those fields to establish a match.

Existing flows retain their connection mark and can differ from this prediction.
The tool does not generate client traffic or change routes to explain a flow.
Missing/stale snapshots are marked explicitly.

## Retention and export

The controller retains up to 100 events in RAM without periodic flash history
writes. Reboot starts a new history. Use diagnostic JSON export to save a snapshot.

Export includes allowed state fields, policy selectors, reasons and events.
Connection credentials, APN credentials, PIN, full RouterOS environment, backup
requests and transaction journals are excluded. Like any diagnostic export, it
can still contain the operator's addresses and topology.

Sources: `sdwan/diagnostics.py`, `sdwan/diagnostics_ui.py` and enriched status in
`native/sdwan-controller.rsc`. The current standard bundle has JSON and 11 RSC
files; `sdwan.py` defines its `FILES` list. Original milestone reports were stored
in `runtime/policies-acceptance.json`, `runtime/policies-protection-acceptance.json`
and `runtime/gui-policies-diagnostics-validation.json`.

Local runtime reports, credentials and device snapshots are not published.
See [test reproduction](TESTING.en.md).
