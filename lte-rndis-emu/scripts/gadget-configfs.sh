#!/bin/sh
# Path A, only when this kernel actually has a gadget UDC.
# Do not modprobe if CONFIG_USB_SUPPORT is disabled. The CHR QEMU process
# stays where it is; this script only creates the gadget on a Linux that
# can enumerate it locally.
set -eu

fail() {
    echo "gadget-configfs: $*" >&2
    exit 3
}

if [ -r /proc/config.gz ]; then
    if zcat /proc/config.gz | grep -q '^# CONFIG_USB_SUPPORT is not set$'; then
        fail "CONFIG_USB_SUPPORT is not set. Not loading dummy_hcd or libcomposite. Use: python3 -m lte_rndis_emu serve --uplink IFACE"
    fi
fi

if ! command -v modprobe >/dev/null 2>&1; then
    fail "modprobe is not available and /sys/class/udc was not checked successfully"
fi

modprobe libcomposite
modprobe usb_f_rndis 2>/dev/null || true
if [ ! -d /sys/class/udc ] || [ -z "$(ls /sys/class/udc 2>/dev/null)" ]; then
    modprobe dummy_hcd
fi

if [ ! -d /sys/class/udc ] || [ -z "$(ls /sys/class/udc 2>/dev/null)" ]; then
    fail "no UDC after dummy_hcd. Do not rebuild this kernel. Use the userspace usbredir emulator."
fi

mountpoint -q /sys/kernel/config || mount -t configfs none /sys/kernel/config

GADGET=/sys/kernel/config/usb_gadget/lte-rndis
mkdir -p "$GADGET"
cd "$GADGET"
echo 0x12d1 > idVendor
echo 0x14db > idProduct
echo 0x0200 > bcdUSB
echo 0x0100 > bcdDevice
echo 0xEF > bDeviceClass
echo 0x02 > bDeviceSubClass
echo 0x01 > bDeviceProtocol
mkdir -p strings/0x409
echo EMU00000001 > strings/0x409/serialnumber
echo HUAWEI > strings/0x409/manufacturer
echo "HUAWEI Mobile" > strings/0x409/product
mkdir -p configs/c.1/strings/0x409
echo RNDIS > configs/c.1/strings/0x409/configuration
echo 250 > configs/c.1/MaxPower
mkdir -p functions/rndis.usb0
if [ -e functions/rndis.usb0/host_addr ]; then
    echo 02:12:d1:14:db:02 > functions/rndis.usb0/host_addr
fi
if [ -e functions/rndis.usb0/dev_addr ]; then
    echo 02:12:d1:14:db:01 > functions/rndis.usb0/dev_addr
fi
ln -s functions/rndis.usb0 configs/c.1/rndis.usb0 2>/dev/null || true
UDC=$(ls /sys/class/udc | head -n 1)
echo "$UDC" > UDC

IFNAME=usb0
if [ -r functions/rndis.usb0/ifname ]; then
    IFNAME=$(cat functions/rndis.usb0/ifname)
fi
echo "gadget up udc=$UDC ifname=$IFNAME"
echo "Confirm with lsusb before any QEMU usb-host claim."
echo "This script does not run DHCP and does not enslave an uplink."
if [ -n "${UPLINK:-}" ]; then
    echo "Bridge $IFNAME to $UPLINK yourself only after lsusb shows 12d1:14db."
    echo "ip link set $IFNAME up"
    echo "ip link add name lte-br type bridge"
    echo "ip link set $IFNAME master lte-br"
    echo "ip link set $UPLINK master lte-br"
    echo "ip link set lte-br up"
fi
