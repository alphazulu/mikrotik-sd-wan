"""USB descriptors for a Linux f_rndis function, plus an optional CDC ACM AT port.

The RNDIS control interface is class/subclass/protocol 02/02/ff. That is the
match Linux rndis_host uses, and it is the gadget profile forum reports showed
up as an LTE interface on RouterOS. VID 12d1 / PID 14db is the ID MikroTik
documents for a config-less Huawei E3372h, not a substitute for those classes.
"""

from __future__ import annotations

from dataclasses import dataclass


VID_HUAWEI = 0x12D1
PID_E3372_CONFIGLESS = 0x14DB


@dataclass(frozen=True)
class Endpoint:
    address: int
    kind: str  # bulk or interrupt
    max_packet_hs: int
    max_packet_fs: int
    interval_hs: int
    interval_fs: int
    interface: int


@dataclass(frozen=True)
class UsbIdentity:
    vid: int = VID_HUAWEI
    pid: int = PID_E3372_CONFIGLESS
    bcd_device: int = 0x0100
    manufacturer: str = "HUAWEI"
    product: str = "HUAWEI Mobile"
    serial: str = "EMU00000001"
    profile: str = "hilink"


def _ep(address: int, attributes: int, packet: int, interval: int) -> bytes:
    return bytes(
        (
            7,
            5,
            address,
            attributes,
            packet & 0xFF,
            (packet >> 8) & 0xFF,
            interval,
        )
    )


def _interface(number: int, alternate: int, endpoints: int, klass: int, sub: int, proto: int) -> bytes:
    return bytes((9, 4, number, alternate, endpoints, klass, sub, proto, 0))


def _rndis_function(notify_interval: int, bulk_packet: int) -> bytes:
    # IAD + control interface match drivers/usb/gadget/function/f_rndis.c (Linux 6.12).
    return b"".join(
        (
            bytes((8, 0x0B, 0, 2, 0x02, 0x06, 0x00, 0)),
            _interface(0, 0, 1, 0x02, 0x02, 0xFF),
            bytes((5, 0x24, 0x00, 0x10, 0x01)),
            bytes((5, 0x24, 0x01, 0x00, 0x01)),
            bytes((4, 0x24, 0x02, 0x00)),
            bytes((5, 0x24, 0x06, 0x00, 0x01)),
            _ep(0x81, 0x03, 8, notify_interval),
            _interface(1, 0, 2, 0x0A, 0x00, 0x00),
            _ep(0x82, 0x02, bulk_packet, 0),
            _ep(0x02, 0x02, bulk_packet, 0),
        )
    )


def _at_function(notify_interval: int, bulk_packet: int) -> bytes:
    # CDC ACM, protocol AT (0x01), interfaces 2 and 3. Not part of f_rndis.
    return b"".join(
        (
            bytes((8, 0x0B, 2, 2, 0x02, 0x02, 0x01, 0)),
            _interface(2, 0, 1, 0x02, 0x02, 0x01),
            bytes((5, 0x24, 0x00, 0x10, 0x01)),
            bytes((5, 0x24, 0x01, 0x00, 0x03)),
            bytes((4, 0x24, 0x02, 0x02)),
            bytes((5, 0x24, 0x06, 0x02, 0x03)),
            _ep(0x83, 0x03, 8, notify_interval),
            _interface(3, 0, 2, 0x0A, 0x00, 0x00),
            _ep(0x84, 0x02, bulk_packet, 0),
            _ep(0x04, 0x02, bulk_packet, 0),
        )
    )


def _config(function: bytes, descriptor_type: int) -> bytes:
    total = 9 + len(function)
    # Pure f_rndis is 66 bytes. The AT function appends another 66.
    interfaces = 4 if len(function) > 66 else 2
    header = bytes(
        (
            9,
            descriptor_type,
            total & 0xFF,
            (total >> 8) & 0xFF,
            interfaces,
            1,
            0,
            0x80,
            250,
        )
    )
    blob = header + function
    if len(blob) != total:
        raise RuntimeError("config descriptor length mismatch")
    return blob


class Descriptors:
    def __init__(self, identity: UsbIdentity):
        if identity.profile not in ("hilink", "at"):
            raise ValueError("profile must be hilink or at")
        self.identity = identity
        hs_fn = _rndis_function(9, 512)
        fs_fn = _rndis_function(32, 64)
        if identity.profile == "at":
            hs_fn += _at_function(9, 512)
            fs_fn += _at_function(32, 64)
        self.hs_config = _config(hs_fn, 2)
        self.fs_config = _config(fs_fn, 2)
        self.other_speed = _config(fs_fn, 7)
        self.device = bytes(
            (
                18,
                1,
                0x00,
                0x02,
                0xEF,
                0x02,
                0x01,
                64,
                identity.vid & 0xFF,
                (identity.vid >> 8) & 0xFF,
                identity.pid & 0xFF,
                (identity.pid >> 8) & 0xFF,
                identity.bcd_device & 0xFF,
                (identity.bcd_device >> 8) & 0xFF,
                1,
                2,
                3,
                1,
            )
        )
        self.qualifier = bytes((10, 6, 0x00, 0x02, 0xEF, 0x02, 0x01, 64, 1, 0))
        self.strings = {
            0: bytes((4, 3, 0x09, 0x04)),
            1: _utf16(identity.manufacturer),
            2: _utf16(identity.product),
            3: _utf16(identity.serial),
        }

    @property
    def interface_count(self) -> int:
        return 4 if self.identity.profile == "at" else 2

    def endpoints(self) -> tuple[Endpoint, ...]:
        rndis = (
            Endpoint(0x81, "interrupt", 8, 8, 9, 32, 0),
            Endpoint(0x82, "bulk", 512, 64, 0, 0, 1),
            Endpoint(0x02, "bulk", 512, 64, 0, 0, 1),
        )
        if self.identity.profile != "at":
            return rndis
        return rndis + (
            Endpoint(0x83, "interrupt", 8, 8, 9, 32, 2),
            Endpoint(0x84, "bulk", 512, 64, 0, 0, 3),
            Endpoint(0x04, "bulk", 512, 64, 0, 0, 3),
        )

    def interfaces(self) -> tuple[tuple[int, int, int, int], ...]:
        rndis = ((0, 0x02, 0x02, 0xFF), (1, 0x0A, 0x00, 0x00))
        if self.identity.profile != "at":
            return rndis
        return rndis + ((2, 0x02, 0x02, 0x01), (3, 0x0A, 0x00, 0x00))


def _utf16(text: str) -> bytes:
    encoded = text.encode("utf-16le")
    return bytes((2 + len(encoded), 3)) + encoded


def lsusb_text(desc: Descriptors) -> str:
    ident = desc.identity
    lines = [
        f"Bus usbredir Device 001: ID {ident.vid:04x}:{ident.pid:04x} {ident.manufacturer} {ident.product}",
        "Device Descriptor:",
        "  bcdUSB               2.00",
        "  bDeviceClass        0xef Miscellaneous",
        "  bDeviceSubClass     0x02",
        "  bDeviceProtocol     0x01 Interface Association",
        f"  idVendor            0x{ident.vid:04x}",
        f"  idProduct           0x{ident.pid:04x}",
        f"  iManufacturer       {ident.manufacturer}",
        f"  iProduct            {ident.product}",
        f"  iSerial             {ident.serial}",
        "  RNDIS control       class 02 subclass 02 protocol ff",
        "  RNDIS data          class 0a",
    ]
    if ident.profile == "at":
        lines.append("  AT management       CDC ACM class 02 subclass 02 protocol 01 (interfaces 2+3)")
    else:
        lines.append("  AT management       absent (profile hilink)")
    lines.append("  Comparable to lsusb. This host has no USB bus, so this is not kernel enumeration.")
    return "\n".join(lines) + "\n"
