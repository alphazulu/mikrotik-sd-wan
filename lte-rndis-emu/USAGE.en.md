# LTE RNDIS emulator — operating contract

[Русский](USAGE.md)

Software USB modem for CHR. Data is bridged at L2 to the caller-provided interface.
There is no DHCP server or radio; LTE fields are synthetic management state.

VID/PID alone does not create `/interface lte`. Descriptors follow Linux `f_rndis`:
control `02/02/ff`, data `0a/00/00`. `12d1:14db` is the config-less E3372h ID
documented by MikroTik, used with this class rather than replacing it.

## Probe first on the QEMU host

Work in the lab's WSL Ubuntu, not an unrelated sandbox. First command:

```bash
python3 -m lte_rndis_emu probe
```

Follow only `decision.path`:

- `usbredir-userspace`: this kernel has no USB gadget. Do not run `modprobe` or
  rebuild the kernel. Start `serve` and attach QEMU with `usb-redir`. Host `lsusb`
  cannot show this userspace device; use `enumerate` for the comparable output.
- `configfs-dummy-hcd`: run `scripts/gadget-configfs.sh`, verify with `lsusb`, then
  try `usb-host`. If libusb cannot hand it over, expose that same gadget with
  `usbredirserver` on 127.0.0.1. Never mix usbip and usbredir.
- `unproven`: stop and provide raw probe output. Do not guess a path.

`scripts/gadget-configfs.sh` probes first and exits 3 without loading modules unless
the path is `configfs-dummy-hcd`. `CONFIG_USB_SUPPORT=y` alone is insufficient.

## Command contract

Working directory: this subproject root, `lte-rndis-emu`.

```bash
python3 -m lte_rndis_emu probe
python3 -m unittest discover -s tests -v
python3 -m lte_rndis_emu enumerate --json
python3 -m lte_rndis_emu qemu-args
```

Service:

```bash
python3 -m lte_rndis_emu serve --uplink lte0
```

`--uplink` is required. `none` provides USB only, with no outgoing frames.
Positional `serve lte0` is also accepted.

Wait for this single ready line on stdout:

```text
ready usbredir=127.0.0.1:24320 control=127.0.0.1:24321 uplink=lte0 profile=hilink vid=0x12d1 pid=0x14db gate=0
```

`serve` exit codes: 0 on Ctrl+C; 2 for missing interface, non-loopback address or
occupied port. It listens only on 127.0.0.1 or ::1. A second usbredir client is
closed: one QEMU owns the device.

## Traffic path

`--uplink` names an existing interface: TAP, veth, dummy or bridge port. The
emulator opens `AF_PACKET` and copies Ethernet frames unchanged.

```text
CHR lte  --usbredir/RNDIS-->  emulator  --L2-->  --uplink
```

- USB-host frames reach the interface only after RNDIS `INITIALIZE` and a nonzero
  `SET OID_GEN_CURRENT_PACKET_FILTER`. RouterOS's driver does this itself.
- Returning interface frames become `REMOTE_NDIS_PACKET_MSG` on bulk IN.
- The process neither interprets nor answers IP, DHCP, NAT or DNS. A DHCP magic
  cookie, if present, reaches uplink byte-for-byte.
- The operator provides addressing on TAP or beyond the bridge; for example,
  external `dnsmasq` on lte0. This is not part of the emulator.

### WSL without CAP_NET_ADMIN / CAP_NET_RAW

TAP/AF_PACKET EPERM is a failure of that method, not success. No fake lte0 is
created. A separately selected **real L2 transport** is available for such hosts:

```bash
python3 -m lte_rndis_emu serve --uplink socket:127.0.0.1:24322 --gate
```

Wait for `ready`, then start a dedicated virtual ISP with another Ethernet NIC:

```text
-netdev socket,id=lte-uplink,connect=127.0.0.1:24322
-device virtio-net-pci,netdev=lte-uplink,mac=02:12:d1:14:db:01
```

USB connects to DUT through `qemu-args`; Ethernet connects to a **different** VM,
the ISP. Port 24322 belongs to this profile; never attach current lab ISPs to it.
Frames use TCP: four-byte network-order length, then Ethernet. One loopback client
is accepted, partial TCP reads are assembled, invalid length disconnects, buffers
are bounded. No privileges, USB/IP or kernel modules are needed.

Configure ISP `192.0.2.1/24`, DHCP pool `192.0.2.10-192.0.2.50`, gateway
`192.0.2.1`, and NAT through its separate uplink if external access is needed.
The ISP serves DHCP, not this process. RouterOS creates HiLink's dynamic DHCP
client through `/interface/lte/apn`; change its settings through APN.

After emulator restart, QEMU usbredir reconnects if `reconnect` is supported.
Old QEMU socket netdev does **not** reconnect automatically: restart only the
dedicated ISP VM or recreate its socket netdev separately. Physical-interface
`--uplink lte0` still needs permissions.

Create TAP on a lab host with `ip` and `/dev/net/tun`:

```bash
sh scripts/prepare-uplink.sh lte0
```

Do not pass a production NIC unless intentionally injecting CHR L2 traffic into
that segment. Never loop uplink back to the same CHR. Own outgoing frames are
filtered with `PACKET_IGNORE_OUTGOING`; another bridge's round trip is still a loop.

RNDIS permanent MAC defaults to `02:12:d1:14:db:02` (`--host-mac`): it is the
RouterOS-side interface address, not uplink's address.

## TAP/virtual ISP: disable offload on the dedicated port

AF_PACKET transports Ethernet, not virtio checksum/GSO metadata. For a separate
ISP VM attached to TAP, configure **only its LTE-side NIC**:

```text
-netdev tap,id=lte,ifname=lte0,script=no,downscript=no,vnet_hdr=off
-device virtio-net-pci,netdev=lte,csum=off,gso=off,guest_csum=off,guest_tso4=off,guest_tso6=off,guest_ecn=off,guest_ufo=off,host_tso4=off,host_tso6=off,host_ecn=off,host_ufo=off
```

Do not change management NIC or existing LAN; do not loop TAP back to DUT.
With another backend, separately validate output frame sizes/checksums.

Ubuntu/QEMU 8.2.2 with ordinary virtio offload produced a 2598-byte Ethernet frame
with unfinished TCP checksum; TLS failed. With these settings, 7648 TCP packets
had no bad checksums or frames over 1514 bytes, and HTTPS, bidirectional TCP and
controlled outage/recovery passed. This is an L2-transport limit, not LTE-radio
speed evaluation. See [VALIDATION.md](VALIDATION.en.md).

## LTE control

This is neither radio nor an APN data session. Default `hilink` exposes RNDIS only,
without AT. The operator reads/changes synthetic state.

`GET http://127.0.0.1:24321/health` → `{"ready": true}`.

`GET http://127.0.0.1:24321/lte` → JSON.

`POST` or `PATCH` `/lte` accepts partial JSON. Unknown/read-only keys (`usb`,
`counters`, `source`, `uplink`) are ignored. Invalid fields return HTTP 400
`{"error": "..."}`.

Mutable fields:

| Key | Values |
|---|---|
| `registration_status` | `registered`, `roaming`, `searching`, `denied`, `unknown` |
| `access_technology` | `LTE`, `UMTS`, `GSM`, `NR` |
| `pin_status` | `ready`, `sim-pin`, `absent` |
| `rssi`, `rsrp`, `rsrq`, `sinr`, `link_bps` | Integers; `rssi` in dBm |
| `operator`, `operator_numeric`, `manufacturer`, `model`, `revision`, `imei`, `imsi`, `iccid`, `lac`, `cell_id`, `functionality`, `apn` | Strings, length 1..64 |

`link_bps` only feeds RNDIS `OID_GEN_LINK_SPEED`, in NDIS units of bit/s divided
by 100; it does not shape frames. Registration other than registered/roaming makes
`OID_GEN_MEDIA_CONNECT_STATUS` disconnected, but frames still bridge unless `--gate`
is set.

`--gate` drops both directions unless registered/roaming, enabling SD-WAN failure
tests. It defaults off so USB startup does not depend on a synthetic radio flag.

`--state path.json` loads state at startup and writes after POST; external edits
are picked up by mtime on the next read. `--control none` disables HTTP, leaving
state-file/default management only.

### `at` profile

```bash
python3 -m lte_rndis_emu serve --uplink lte0 --profile at
```

Adds CDC ACM USB interfaces, class `02/02/01`, interfaces 2/3, alongside RNDIS.
This is host management, not another dataplane. If CHR does not create LTE with
it, return to hilink: extra interfaces differ from pure f_rndis, previously
observed as lte1 on RouterBOARD.

Immediate AT responses, with no delay; unknown commands return `ERROR`:

| Command | Response |
|---|---|
| `AT`, `ATE0`, `ATE1` | OK; echo initially enabled |
| `ATI`, `AT+CGMI`, `AT+CGMM`, `AT+CGMR` | manufacturer / model / revision |
| `AT+CGSN`, `AT+GSN` | imei |
| `AT+CIMI` | imsi |
| `AT+CCID` | iccid |
| `AT+CPIN?` | `READY`, `SIM PIN`, or `+CME ERROR: 10` when `pin_status=absent` |
| `AT+CSQ` | `(rssi+113)/2` and `,99`; `99,99` unless registered/roaming |
| `AT+CREG?`, `AT+CGREG?`, `AT+CEREG?` | `0,1` registered; `0,5` roaming; `0,2` searching; `0,3` denied; `0,4` unknown |
| `AT+COPS?` | `"operator",7` for LTE; `2` UMTS; `0` GSM; `12` NR |
| `AT+CGDCONT?` | Shows `apn`; does not open PDP |

Do not promise that RouterOS config-less `12d1:14db` will open ACM at all.
HiLink monitor fields may remain empty while only management JSON has values.

## Attach to the existing CHR lab

Repository `alphazulu/mikrotik-sd-wan`, `node_command` in lab.py. Normal VM startup
adds no USB controller; optional integration is already implemented as described
below. Add arguments to edge only, retaining up/down lifecycle and other nodes.

Order: `serve`, then QEMU. QEMU is the TCP client. An already running CHR does not
automatically gain a new chardev.

`qemu-args` prints arguments. If `qemu-system-x86_64 -chardev socket,help` supports
`reconnect-ms` or `reconnect=`, the suffix is added automatically. Otherwise no
reconnect is emitted: starting the emulator after QEMU will not attach until
QEMU restarts.

Integration pattern:

```python
if name == "edge" and os.environ.get("LTE_RNDIS_EMU") == "1":
    args.extend([
        "-device", "qemu-xhci,id=xhci",
        "-chardev", "socket,id=lteusb,host=127.0.0.1,port=24320",
        "-device", "usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0",
    ])
```

Ports 24320/24321 do not overlap this lab's QMP24100+, serial25100+, sockets
23100/22100 or host forwards. Keep them on 127.0.0.1.

Never combine usbip and usbredir. QEMU has no universal `-device usbip`.
`usbredirserver` wraps real libusb hardware; it is unnecessary without a gadget
in lsusb. Probe records its help only when installed and does not redirect devices.

Hot-adding controller/device after service startup was tested on separate x86;
the base lab uses launch arguments. Adding them before starting edge is preferred.

## Sequential acceptance criteria

1. AF_PACKET: interface exists (`ip link show lte0`); EPERM fails this path.
   Explicit socket transport needs actual Ethernet with separate ISP. Enumeration
   replaces frame transfer in neither path.
2. `enumerate`, or lsusb on a gadget-capable kernel: `12d1:14db`, RNDIS `02/02/ff`.
3. QEMU monitor/QMP `info usb` shows the device on xhci. This is not yet RouterOS.
4. CHR: `/system/resource/usb/print`, and `/system/resource/hardware/print detail`
   if available in that version; verify actual USB visibility.
5. Only then `/interface/lte/print detail`. Until steps 3–4 pass, changing PID alone
   is not a remedy for missing LTE.
6. A CHR frame reaches uplink; a reply returns. DHCP must be served by the endpoint
   provided on uplink, not the emulator.

If RouterOS sees USB but no LTE, stop and capture usbmon from a live compatible
modem instead of guessing output. The next evidence-based class after RNDIS is
MBIM, not a random VID.

## Out of scope

- No DHCP, CHR address assignment or hidden NAT.
- No AT responses in hilink profile.
- No SIM, mobile-network registration or radio-band simulation; JSON imei/imsi are synthetic.
- No proof of `/interface lte` from the process alone: actual CHR/raw output is required.

## Verified on RouterOS 7.24.5

[VALIDATION.md](VALIDATION.en.md): separate x86 L6 and CHR exposed real lte1, DHCP
through APN, ICMP/TCP through RNDIS. In this version `/system/resource/usb/print`
was absent (syntax error); USB is visible in
`/system/resource/hardware/print detail without-paging where type=usb`.

`lab.py` adds qemu-args only for edge and `LTE_RNDIS_EMU=1`. Default VM commands
and up/down are unchanged. Do not restart unrelated running nodes for this check.
Separate x86 launch: [X86-LAB.md](X86-LAB.en.md), retaining IDE
`bus=0,unit=0,media=disk`.

HiLink limit: `/interface/lte/monitor lte1 once` shows session uptime, while HTTP
synthetic RSSI/APN/operator do not become RouterOS radio fields. With `--gate`,
registration POST changes packet forwarding, emulating SLA availability loss,
not physical SIM removal or operator change. TAP tests require explicit
`LTE_EMU_TAP_TEST=1`.

RX accepts Ethernet frames up to 1514 bytes (IP MTU 1500); larger frames are dropped
before USB completion. Disable TAP/veth offload on the dedicated source side:
GSO/checksum-offload packets are not ordinary RNDIS Ethernet. Size limits cannot
fix bad TCP checksums or replace offload settings. Jumbo/VLAN dataplane is not
separately implemented.
