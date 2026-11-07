# Isolated x86 / CHR LTE lab

[Русский](X86-LAB.md)

Production MikroTik is not used. Never modify/publish the original licensed image
or include it in Docker. This lab tests a separate full copy; license portability
to another topology is not assumed.

## x86 disk and launch

From the local SD-WAN project root:

```bash
mkdir -p runtime/x86-lte-lab/images runtime/x86-lte-lab/runtime
cp --sparse=always --reflink=auto images/mikrotik-routeros-kvm-disk.qcow2 \
  runtime/x86-lte-lab/images/routeros-x86-l6.qcow2
```

**Copy only when first creating the VM**, never over an already updated disk.
Record source/copy SHA256 before first boot. Do not recreate MBR, reinstall the
system, change software-id or substitute a key.

Start the emulator and wait for `ready`, then x86 from the project root. Check
port availability beforehand:

```bash
qemu-system-x86_64 \
  -name sdwan-x86-lte -machine pc -accel kvm -cpu host -m 1024 -smp 1 \
  -display none \
  -drive file=runtime/x86-lte-lab/images/routeros-x86-l6.qcow2,format=qcow2,bus=0,unit=0,media=disk \
  -serial tcp:127.0.0.1:24401,server=on,wait=off \
  -qmp tcp:127.0.0.1:24400,server=on,wait=off \
  -netdev user,id=mgmt,net=10.79.0.0/24,dhcpstart=10.79.0.15,ipv6=off \
  -device e1000,netdev=mgmt,mac=52:54:00:79:00:01 \
  -device qemu-xhci,id=xhci \
  -chardev socket,id=lteusb,host=127.0.0.1,port=24320,reconnect=2 \
  -device usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0
```

Obtain chardev arguments with `python3 -m lte_rndis_emu qemu-args` from
`lte-rndis-emu`; `reconnect=2` was confirmed specifically on QEMU 8.2.2.
If the current WSL session has not picked up kvm membership, use
`sg kvm -c '...full command...'`. Do not add the user to root groups.

Log into serial as `admin+ct`. Identify management Ethernet through
`/interface/print detail`; it was `ether3` in the provided image. Set a separate
lab password. Management is loopback only; USB/Ethernet reachability into RouterOS
does not imply safe public management.

## Upgrade using RouterOS facilities

Before upgrade the provided copy reported `7.24.4`, `x86_64`, `nlevel: 6`.
The x86 package is **routeros-7.24.5.npk**, without an x86_64 suffix. Upgrade the
installed wireless package alongside it. Check server reachability and space:

```routeros
/system/resource/print without-paging
/system/license/print
/system/package/print without-paging
/tool/fetch url="https://download.mikrotik.com/routeros/7.24.5/routeros-7.24.5.npk" dst-path=routeros-7.24.5.npk
/tool/fetch url="https://download.mikrotik.com/routeros/7.24.5/wireless-7.24.5.npk" dst-path=wireless-7.24.5.npk
/file/print without-paging
/system/reboot
```

In the actual check, the host first downloaded official NPKs over HTTPS. RouterOS
then fetched them from a loopback HTTP server reachable as `10.79.0.2:24406` from
the guest. Installation uses an ordinary RouterOS reboot. Packages, keys and disks
stay in ignored directories. Recheck version/packages/license afterwards: actual
result was 7.24.5 and nlevel 6. Original QCOW2 remained byte-for-byte unchanged.

MikroTik [upgrade/install](https://help.mikrotik.com/docs/spaces/ROS/pages/328142/Upgrading+and+installation),
[license documentation](https://help.mikrotik.com/docs/spaces/ROS/pages/328149/RouterOS+license+keys).

## Separate ISP and traffic verification

Create a separate CHR overlay on clean `chr-7.24.5.img`, not current VM disks.
Two NICs: management usernet `10.80.0.0/24`, DHCP start `10.80.0.15`; second NIC
uses USAGE's `socket,connect=127.0.0.1:24322`. QMP 24410, serial 24411.
Clean CHR already has an ether1 DHCP client; do not add another.

```routeros
/ip/address/add address=192.0.2.1/24 interface=ether2
/ip/address/add address=198.18.79.1/32 interface=lo
/ip/pool/add name=lte ranges=192.0.2.10-192.0.2.50
/ip/dhcp-server/network/add address=192.0.2.0/24 gateway=192.0.2.1 dns-server=10.80.0.3
/ip/dhcp-server/add name=lte interface=ether2 address-pool=lte disabled=no
/ip/firewall/nat/add chain=srcnat out-interface=ether1 action=masquerade
```

On DUT wait for DHCP `bound` specifically on lte1. Add narrow LTE routes for test
targets so management default cannot produce a false success:

```routeros
/ip/route/add dst-address=198.18.79.1/32 gateway=192.0.2.1%lte1 comment=lte-emulator-test
/ip/route/add dst-address=10.80.0.2/32 gateway=192.0.2.1%lte1 comment=lte-emulator-test
/ping 198.18.79.1 interface=lte1 count=5
```

For TCP, run a host loopback HTTP server on 24406 with a small file; fetch with
the actual DHCP LTE address as src-address and `output=none`. Long JSON with
`output=user` invokes a pager and obstructs automated serial.

To test CHR as DUT, create another clean overlay: QMP24420/serial24421,
management usernet10.81.0.0/24, virtio disk/NIC and the same USB arguments.
**One emulator belongs to one DUT**: first remove the x86 USB frontend and chardev
through QMP, then start CHR. Simultaneous use needs separate emulator instances
and nonoverlapping ports; the actual check switched sequentially. Do not replace
running edge or use its ports.

APN check: `/interface/lte/apn/set [find where default=yes] add-default-route=no use-peer-dns=no`.
Wait for dynamic client recreation and compare settings. For controlled outage,
start the service with `--gate`, then POST `/lte` to change registration_status
from registered to searching and back. Capture ping before/during/after.

Results: [VALIDATION.md](VALIDATION.en.md). Radio and an external cellular network
are not emulated.
