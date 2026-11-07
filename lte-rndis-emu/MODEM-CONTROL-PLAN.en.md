# LTE fields in RouterOS: a future emulator profile

[Русский](MODEM-CONTROL-PLAN.md)

Goal: synthetic state reaches `/interface/lte/monitor` through the normal modem
driver, without a script imitating its output. Working HiLink with real traffic
remains a separately verified profile.

## Protocol choice

Preferred prototype: **MBIM**, then an AT channel for fields RouterOS obtains only
through vendor commands. RouterOS v7 documents automatic MBIM driver loading.
An AT interface next to RNDIS does not itself make the HiLink driver poll it.
Do not guess VID/PID or present management JSON as MikroTik fields.

MikroTik notes that monitor fields depend on the modem. Promising every field of
every modem is incorrect. Acceptance must list specific fields actually shown
by CHR/x86 7.24.5. Unknown remains unknown, not zero.

| Group | Modem implementation | Verification |
|---|---|---|
| Identity | Device Caps, revision, IMEI, serial; AT manufacturer/model if requested | monitor, hardware |
| SIM | Subscriber Ready, IMSI, ICCID, PIN query/set, absent/locked/ready | monitor, pin-status, errors |
| Network | Register State, Packet Service, provider/PLMN, registered/roaming/searching/denied, LTE/UMTS/GSM | monitor, transitions |
| Basic signal | MBIM Signal State: RSSI and correct unknown codes | monitor, HTTP changes |
| Extended signal | MBIMEx/observed AT queries for RSRP, RSRQ, SINR | actual trace and monitor only |
| Cell | Supported Location/Cell Info service or AT; CID/TAC/eNB/PCI/band/EARFCN | monitor/cell-monitor if supported |
| Session/APN | Connect query/set, Radio State, IP Configuration, address/DNS/gateway/MTU | RouterOS APN, IP, routes, traffic |

MBIM 1.0 alone does not guarantee RSRP/RSRQ/SINR. MBIMEx 2.0 extends Signal State
with RSRP/SNR, but RouterOS must negotiate and actually use it. Other fields need
confirmed driver queries, not arbitrary extra response properties.

## Implementation and acceptance order

1. Add optional `mbim` USB profile: CDC-MBIM descriptors, interrupt notifications,
   SEND/GET_ENCAPSULATED_COMMAND and transfer-size negotiation. Use a separate VM
   and separate ports; preserve working HiLink.
2. Record bounded request trace: transaction ID, service UUID, CID, query/set,
   status, length. Redact APN/PIN secrets. Observe RouterOS 7.24.5 requests first,
   then implement responses and state sequencing.
3. Share RAM state between HTTP, MBIM and AT. Registration/SIM/radio changes send
   MBIM indications and affect data-session availability. RouterOS sees changes
   without manual refresh/import or emulator restart.
4. MBIM dataplane uses CDC-NCM/NTB IP datagrams, not Ethernet RNDIS. Implement a
   separate codec and explicit IP↔Ethernet adapter to the dedicated ISP, including
   next-hop/ARP resolution, sizes, fragmentation/aggregation. Changing a descriptor
   does not turn the old RNDIS bulk transport into MBIM.
5. First implement Device Caps/SIM/registration/RSSI and working Connect+IP.
   Capture real monitor output and bidirectional TCP. Add extended signal/cell
   based on actual driver requests afterwards.
6. Unit-test codecs/state: fragments, bad lengths/offsets, unsupported CIDs,
   timeout/cancel, PIN, roaming, APN rejection, radio-off, reconnect. Bound RAM
   queues; persistent writes default off.
7. Each field needs live acceptance: HTTP POST → matching response/indication →
   changed RouterOS field. Enumeration or units alone do not establish a complete
   modem. Preserve raw monitor/USB/trace and traffic evidence.
8. Repeat SD-WAN APN ownership, failover/failback and scoped conntrack retirement
   using modem data-session loss. Verify HiLink and the new profile separately.

SMS, USSD, eSIM, carrier aggregation and modem firmware upgrades do not follow
from monitor fields; add only with explicit acceptance. Physical radio is not
modeled: values and failures are synthetic and reproducible.

## Sources

- [Current RouterOS Manual: LTE/5G](https://manual.mikrotik.com/docs/mobile-networking/lte-5g/):
  MBIM, AT and modem-dependent monitor. The current page is marked 7.26; prove
  compatibility on target 7.24.5.
- [MikroTik LTE/5G documentation archive](https://help.mikrotik.com/docs/spaces/ROS/pages/30146563/LTE+5G):
  MBIM in v7, APN, monitor examples.
- [MikroTik Peripherals](https://help.mikrotik.com/docs/spaces/ROS/pages/13500447/Peripherals):
  MBIM/CDC/RNDIS classes and separate per-model AT support.
- [Microsoft MBIMEx 2.0](https://learn.microsoft.com/en-us/windows-hardware/drivers/network/mbimex-2.0-5g-nsa-support):
  extension negotiation and RSRP/SNR.

Status: **design only; this profile is not implemented**. Proven current result:
HiLink RNDIS, LTE/DHCP/APN, bidirectional traffic and controlled data loss.
