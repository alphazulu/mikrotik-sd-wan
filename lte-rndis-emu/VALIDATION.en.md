# WSL / QEMU / RouterOS validation — 26 October 2026

[Русский](VALIDATION.md)

These are executed-check results, not a promise to support every LTE modem.

| Check | Actual result |
|---|---|
| Host | WSL Ubuntu 24.04.2, kernel 6.18.54.1-microsoft-standard-WSL2 |
| QEMU | 8.2.2, KVM |
| Probe | usbredir-userspace; USB host support present, gadget disabled, no UDC |
| TAP / AF_PACKET | TAP returned EPERM; that path was not declared working |
| Transport used | socket:127.0.0.1:24322, real Ethernet frames to a separate ISP CHR |
| x86 before upgrade | RouterOS 7.24.4, x86_64, nlevel 6 |
| x86 after normal upgrade | RouterOS + wireless 7.24.5, nlevel 6, original software-id |
| Original QCOW2 | Post-test SHA256 matched pre-copy SHA256 |
| x86 USB / LTE | hardware type=usb: 12d1:14db, HUAWEI Mobile; lte1 RUNNING |
| CHR USB / LTE | Clean CHR 7.24.5; hardware type=usb: 12d1:14db; lte1 RUNNING |
| LTE DHCP | x86 192.0.2.50/24, CHR 192.0.2.49/24, gateway 192.0.2.1 |
| x86 LTE ICMP | 5 sent / 5 received / 0% loss |
| CHR LTE ICMP | 5 sent / 5 received / 0% loss |
| LTE TCP | Both DUTs: `/tool/fetch` status finished, code 200, 1 KiB |
| CHR APN | add-default-route=no/use-peer-dns=no reflected in dynamic DHCP client |
| CHR controlled outage | --gate, registered: 3/3; searching: 0/3; registered: 3/3 + HTTP200 |
| Unit / socket tests | 21 tests: 20 passed, one explicitly skipped privileged TAP test |
| lab.py isolation | Opt-in changes edge only; other VM commands byte-identical |

TCP targeted a host HTTP server through a dedicated virtual ISP, not a public
cellular operator. Narrow /32 routes and LTE source excluded management-default
bypass. ISP provides separate NAT; the emulator has no DHCP server. QEMU usbredir
and RouterOS hardware visibility were verified separately from synthetic enumeration.

Executed output excerpts, with whitespace/line wrapping condensed:

```text
QMP info usb (CHR):
  Device 0.1, Port 1, Speed 480 Mb/s, Product USB Redirection Device, ID: lte-rndis

/system/resource/usb/print
syntax error (line 1 column 21)

/system/resource/hardware/print detail without-paging where type=usb
1 location="1-1" parent=1-0 type=usb vendor="HUAWEI" name="HUAWEI Mobile"
  serial-number="EMU00000001" vendor-id="0x12d1" device-id="0x14db"
  speed="480" usb-version=" 2.00" manufacturer-reported-max-power="500mA"
  irq=0 owner="system" device-path=""

/interface/lte/print detail without-paging
Flags: R - RUNNING
0 R default-name="lte1" name="lte1" mtu=1500 apn-profiles=default

/ping 198.18.79.1 src-address=192.0.2.49 count=5
sent=5 received=5 packet-loss=0%

/tool/fetch url="http://10.80.0.2:24406/manifest.json" src-address=192.0.2.49 output=none duration=5s
status: finished
code: 200
downloaded: 1KiB
```

Full serial/JSON logs, with lab passwords removed from echo, remain locally under
ignored `runtime/x86-lte-lab/runtime/`: probe.json, enumerate.json, chr-raw.log,
x86-raw.log, routeros-raw.log, qmp-chr-usb.json and validation.json. Images, license,
credentials and production MikroTik files are excluded from the public branch.

## Actual bugs fixed

1. QEMU initially rejected the device with `No interface info for device`.
   INTERFACE_INFO and EP_INFO now precede DEVICE_CONNECT.
2. QEMU then rejected control IN with `unexpected extra data ep 00`. Responses
   now preserve endpoint 0x80 instead of always returning 0.
3. Regression tests, an actual unprivileged TCP L2 backend, refusal to modprobe
   without proven UDC, bounded RX queue, invalid JSON/HTTP handling and socket/thread
   shutdown were added.

Connection ordering/endpoint direction were checked against
[QEMU 8.2.2 hw/usb/redirect.c](https://github.com/qemu/qemu/blob/v8.2.2/hw/usb/redirect.c).
VID/PID and RNDIS class were unchanged to obtain this result.

## Limits

HiLink creates an actual RouterOS LTE interface with Ethernet/DHCP but does not
emulate RF, SIM or mobile operator. `/interface/lte/monitor lte1 once` showed
session uptime; JSON RSSI/RSRP/operator are available through HTTP, not proven as
RouterOS monitor fields. AT profile was not used in these live checks. MBIM is
not implemented. `--gate` emulates data loss and does not guarantee clearing the
hardware RUNNING flag. Old QEMU socket netdev needs separate reconnect after
service restart. This is LTE-path validation, not full SD-WAN failover/48h soak.
At that historical date the owner's main SD-WAN work was paused; this is not the
current project state. Existing nodes and production were unchanged in that test.

## TAP recheck on separate Ubuntu VM — 28 October 2026

A separate Ubuntu 24.04/KVM lab was used without changing the then-running long
SD-WAN soak or production. QEMU 8.2.2, x86 RouterOS 7.24.5 L6, original IDE geometry.
A dedicated virtual ISP serves DHCP/NAT; the emulator assigns no addresses.
USB/control endpoints bind loopback only.

| Check | Result |
|---|---|
| Probe | usbredir-userspace; no USB gadget modules or usbip |
| Units | 24/24 PASS; actual privileged TAP test, ResourceWarning treated as error |
| RouterOS hardware | type=usb, HUAWEI Mobile, 12d1:14db; actual CLI output |
| LTE / APN | lte1 RUNNING, dynamic DHCP bound; add-default-route=no/use-peer-dns=no through APN |
| Internet | Public HTTPS completed with LTE source and narrow LTE route |
| Extended TCP | 40 GET: 6225920 bytes; 40 POST: 1310720 bytes; server checked every POST body |
| TAP capture | 7732 Ethernet frames; 7648 TCP packets, zero bad TCP checksums, zero frames over 1514 bytes |
| Outage / recovery | registered 3/3; searching 0/3; registered 3/3 |
| Cleanup | Owned routes/APN/USB frontend/processes removed; L6 retained |

A separate isolated working copy fixed bulk OUT completion: length returns the
actual bytes accepted without echoing payload. A regression reproduces old zero
length and checks the fix including upper-16-bit propagation. This matches the
[usbredir protocol](https://gitlab.freedesktop.org/spice/usbredir/-/blob/main/docs/usb-redirection-protocol.md)
and usbredirhost bulk completion.

Failed attempts remain separate. One QEMU attempt asserted in
usb_packet_complete_one; its precise cause was unproven and no universal QEMU fix
is claimed. A later TLS timeout was localized by pcap to a virtual ISP's offloaded
2598-byte frame with invalid TCP checksum. Disabling offload only on the dedicated
TAP port allowed the functional series above to pass. This is no reason to change
VID/PID or load USB modules.

The test launcher also stopped inheriting ignored SIGINT from the background shell.
One run passed traffic but failed service shutdown and is not a complete PASS.
After manual cleanup a corrected launcher confirmed automatic cleanup. RouterOS
may cache an inactive LTE entry after USB detach; fixture ownership was checked
before reuse.

This is isolated LTE datapath acceptance, not SD-WAN policy switching, radio, SIM
or complete monitor/scanner-field support. It establishes neither actual LTE
bandwidth nor MikroTik hardware performance. Intermediate CHR throughput is not
a capacity profile.

## Additional MTU / QEMU 8.2.2 checks — 28 October 2026

On a fresh disposable CHR without Ethernet, original code and code with only the
OUT-length fix reproduce `usb_packet_complete_one` on mixed 64/2598-byte frames.
A 64-byte control series passes. Backtrace: `usb_packet_complete_one` ←
`usb_combined_input_packet_complete` ← `hw-usb-redirect.so`. Trace shows five
BABBLE completions then cancellations, with no FIFO bulk-completion violations.
This localizes the triggering input, not a universal cause/fix for every QEMU failure.

The new candidate drops RX Ethernet frames over 1514 bytes before RNDIS packing;
advertised IP MTU is 1500. 25/25 tests passed, including actual privileged TAP.
The new test fails as expected on old source: an oversized frame completes a
pending USB request with BABBLE rather than being dropped. Fixed code keeps the
request pending for the next valid frame. Mixed series transferred all 450 valid
frames without QEMU assertion or BABBLE; cleanup passed. Jumbo/VLAN frames are
unsupported by this profile.

Earlier HTTPS/gate acceptance applies to the previous source. This MTU step ran
units and separate USB series, not another HTTPS/gate test. Those separate results
cannot be combined into complete acceptance of the new code.

## MTU guard: full CHR datapath check — 28 October 2026

After the MTU change a separate series used two new CHR 7.24.5/KVM nodes: RNDIS DUT
and DHCP/NAT ISP. Licensed x86 and existing VMs were unused. Actual USB12d1:14db
and lte1 RUNNING confirmed; APN controls dynamic DHCP with
add-default-route=no/use-peer-dns=false. Public HTTPS fetch used LTE source and
/32 route. Then 40 TLS GET / 40 TLS POST transferred 6225920 / 1310720 bytes;
the server verified every POST body. Only the local self-signed TLS fixture had
certificate verification disabled. Gate ICMP: 3/3 → 0/3 → 3/3. No QEMU assertion.

PCAP: 8563 Ethernet frames, 8434 IPv4 TCP packets, zero frames over 1514 bytes,
zero IPv4/TCP checksum errors, zero unchecked TCP fragments. The inspector detects
an intentionally corrupted TCP checksum and truncated capture. Cleanup passed:
owned QEMU/emulator/capture stopped, owned TAP removed, original raw CHR backing
SHA unchanged. Disks/keys/credentials remain private and are not publication assets.

Earlier failed attempts concerned bootstrap/strict API comparison: dynamic DHCP
cannot be deleted; LTE REST can report add-default-route=no rather than false.
The test scenario was corrected without emulator-code changes. This series
validates the MTU candidate on CHR, not RF/SIM, MikroTik performance or SD-WAN
policy failover.
