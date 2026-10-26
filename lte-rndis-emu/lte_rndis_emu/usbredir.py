"""usbredir device side (the protocol's usb-host).

Hello packets use 32-bit ids. After both peers advertise usb_redir_cap_64bits_ids,
later packets use 64-bit ids. Bulk length_high is present only when
usb_redir_cap_32bits_bulk_length is negotiated. QEMU is the TCP client.
"""

from __future__ import annotations

import struct
from collections import deque
import logging

from lte_rndis_emu.rndis import NOTIFY_RESPONSE_AVAILABLE

HELLO = 0
DEVICE_CONNECT = 1
DEVICE_DISCONNECT = 2
RESET = 3
INTERFACE_INFO = 4
EP_INFO = 5
SET_CONFIGURATION = 6
GET_CONFIGURATION = 7
CONFIGURATION_STATUS = 8
SET_ALT_SETTING = 9
GET_ALT_SETTING = 10
ALT_SETTING_STATUS = 11
START_ISO = 12
STOP_ISO = 13
ISO_STATUS = 14
START_INTERRUPT = 15
STOP_INTERRUPT = 16
INTERRUPT_STATUS = 17
CANCEL = 21
FILTER_REJECT = 22
FILTER_FILTER = 23
DISCONNECT_ACK = 24
CONTROL = 100
BULK = 101
ISO = 102
INTERRUPT = 103

ST_SUCCESS = 0
ST_CANCELLED = 1
ST_INVAL = 2
ST_IOERROR = 3
ST_STALL = 4
ST_BABBLE = 6

SPEED_HIGH = 2
EP_CONTROL = 0
EP_ISO = 1
EP_BULK = 2
EP_INTERRUPT = 3
EP_INVALID = 255

CAP_CONNECT_DEVICE_VERSION = 1 << 1
CAP_FILTER = 1 << 2
CAP_DISCONNECT_ACK = 1 << 3
CAP_EP_INFO_MAX_PACKET = 1 << 4
CAP_64BIT_IDS = 1 << 5
CAP_32BIT_BULK = 1 << 6

OUR_CAPS = (
    CAP_CONNECT_DEVICE_VERSION
    | CAP_FILTER
    | CAP_DISCONNECT_ACK
    | CAP_EP_INFO_MAX_PACKET
    | CAP_64BIT_IDS
    | CAP_32BIT_BULK
)

log = logging.getLogger("lte_rndis_emu")

MAX_PAYLOAD = 1 << 20


class ProtocolError(RuntimeError):
    pass


def parse_caps(payload: bytes) -> int:
    blob = payload[64:]
    caps = 0
    for index in range(0, len(blob) // 4):
        word = struct.unpack_from("<I", blob, index * 4)[0]
        caps |= word << (32 * index)
    return caps


def version_of(payload: bytes) -> str:
    return payload[:64].split(b"\x00", 1)[0].decode("ascii", "replace")


class Codec:
    def __init__(self, our_caps: int = OUR_CAPS):
        self.our_caps = our_caps
        self.peer_caps = 0
        self.ids64 = False
        self.hello_seen = False
        self.buf = b""

    @property
    def negotiated(self) -> int:
        return self.peer_caps & self.our_caps

    def pack(self, typ: int, ident: int, payload: bytes, force32: bool = False) -> bytes:
        if self.ids64 and not force32:
            header = struct.pack("<IIQ", typ, len(payload), ident)
        else:
            header = struct.pack("<III", typ, len(payload), ident & 0xFFFFFFFF)
        return header + payload

    def feed(self, data: bytes) -> list[tuple[int, int, bytes]]:
        self.buf += data
        if len(self.buf) > 8 << 20:
            raise ProtocolError("peer flooded the usbredir parser")
        packets = []
        while True:
            header_len = 16 if self.ids64 else 12
            if len(self.buf) < header_len:
                break
            if self.ids64:
                typ, length, ident = struct.unpack_from("<IIQ", self.buf)
            else:
                typ, length, ident = struct.unpack_from("<III", self.buf)
            if length > MAX_PAYLOAD:
                raise ProtocolError("usbredir packet is too large")
            total = header_len + length
            if len(self.buf) < total:
                break
            payload = bytes(self.buf[header_len:total])
            self.buf = self.buf[total:]
            if typ == HELLO and not self.hello_seen:
                self.hello_seen = True
                self.peer_caps = parse_caps(payload)
                if self.negotiated & CAP_64BIT_IDS:
                    self.ids64 = True
            packets.append((typ, ident, payload))
        return packets


def bulk_header(endpoint: int, status: int, data: bytes, caps: int) -> bytes:
    length = len(data)
    low = length & 0xFFFF
    high = (length >> 16) & 0xFFFF
    if caps & CAP_32BIT_BULK:
        return struct.pack("<BBHIH", endpoint, status, low, 0, high) + data
    if high:
        raise ProtocolError("bulk transfer needs the 32-bit length capability")
    return struct.pack("<BBHI", endpoint, status, low, 0) + data


def parse_bulk(payload: bytes, caps: int) -> tuple[int, int, bytes]:
    header_len = 10 if caps & CAP_32BIT_BULK else 8
    if len(payload) < header_len:
        raise ProtocolError("short bulk header")
    if caps & CAP_32BIT_BULK:
        endpoint, status, low, _stream, high = struct.unpack_from("<BBHIH", payload)
        declared = low | (high << 16)
    else:
        endpoint, status, low, _stream = struct.unpack_from("<BBHI", payload)
        declared = low
    data = payload[header_len:]
    if status == ST_SUCCESS and declared != len(data):
        # Trust the bytes that actually arrived. QEMU sets both consistently.
        pass
    return endpoint, status, data


def parse_control(payload: bytes) -> tuple[int, int, int, int, int, int, bytes]:
    if len(payload) < 10:
        raise ProtocolError("short control header")
    endpoint, request, reqtype, status, value, index, length = struct.unpack_from("<BBBBHHH", payload)
    data = payload[10:]
    return endpoint, request, reqtype, status, value, index, data if data else b""


class Session:
    """One QEMU client. A second client is the caller's problem; serve() refuses it."""

    def __init__(self, device, send):
        self.device = device
        self._send = send
        self.codec = Codec()
        self.announced = False
        self.interrupt_on: set[int] = set()
        self.pending: deque[tuple[int, int, int]] = deque()

    def start(self) -> None:
        version = b"lte-rndis-emu 1.0".ljust(64, b"\x00")
        payload = version + struct.pack("<I", OUR_CAPS)
        self._emit(self.codec.pack(HELLO, 0, payload, force32=True))

    def receive(self, data: bytes) -> None:
        for typ, ident, payload in self.codec.feed(data):
            self._handle(typ, ident, payload)

    def deliver_rx(self, frame: bytes) -> None:
        self.device.enqueue_rx(frame)
        self._flush_pending()

    def _emit(self, blob: bytes) -> None:
        self._send(blob)

    def _handle(self, typ: int, ident: int, payload: bytes) -> None:
        log.debug("usbredir rx type=%d id=%d size=%d", typ, ident, len(payload))
        if typ == HELLO:
            if not self.announced:
                self.announced = True
                self._announce()
            return
        if typ == FILTER_FILTER or typ == FILTER_REJECT or typ == DISCONNECT_ACK:
            return
        if typ == RESET:
            self.pending.clear()
            self.interrupt_on.clear()
            self.device.usb_reset()
            return
        if typ == SET_CONFIGURATION and payload:
            self._config_status(ident, payload[0])
            return
        if typ == GET_CONFIGURATION:
            self._config_status(ident, None)
            return
        if typ == SET_ALT_SETTING and len(payload) >= 2:
            status = ST_SUCCESS if payload[1] == 0 else ST_STALL
            self._emit(self.codec.pack(ALT_SETTING_STATUS, ident, struct.pack("<BBB", status, payload[0], 0 if status == 0 else payload[1])))
            return
        if typ == GET_ALT_SETTING and payload:
            self._emit(self.codec.pack(ALT_SETTING_STATUS, ident, struct.pack("<BBB", ST_SUCCESS, payload[0], 0)))
            return
        if typ == START_ISO and payload:
            self._emit(self.codec.pack(ISO_STATUS, ident, struct.pack("<BB", ST_INVAL, payload[0])))
            return
        if typ == STOP_ISO and payload:
            self._emit(self.codec.pack(ISO_STATUS, ident, struct.pack("<BB", ST_SUCCESS, payload[0])))
            return
        if typ == START_INTERRUPT and payload:
            endpoint = payload[0]
            self.interrupt_on.add(endpoint)
            self._emit(self.codec.pack(INTERRUPT_STATUS, ident, struct.pack("<BB", ST_SUCCESS, endpoint)))
            self._flush_notify()
            return
        if typ == STOP_INTERRUPT and payload:
            self.interrupt_on.discard(payload[0])
            self._emit(self.codec.pack(INTERRUPT_STATUS, ident, struct.pack("<BB", ST_SUCCESS, payload[0])))
            return
        if typ == CANCEL:
            self.pending = deque(item for item in self.pending if item[0] != ident)
            return
        if typ == CONTROL:
            self._control(ident, payload)
            return
        if typ == BULK:
            self._bulk(ident, payload)
            return
        if typ == ISO:
            return

    def _announce(self) -> None:
        caps = self.codec.negotiated
        identity = self.device.identity
        connect = struct.pack(
            "<BBBBHHH",
            SPEED_HIGH,
            0xEF,
            0x02,
            0x01,
            identity.vid,
            identity.pid,
            identity.bcd_device,
        )
        if not caps & CAP_CONNECT_DEVICE_VERSION:
            connect = connect[:8]
        numbers = bytearray(32)
        classes = bytearray(32)
        subclasses = bytearray(32)
        protocols = bytearray(32)
        for index, (number, klass, sub, proto) in enumerate(self.device.descriptors.interfaces()):
            numbers[index] = number
            classes[index] = klass
            subclasses[index] = sub
            protocols[index] = proto
        info = struct.pack("<I", self.device.descriptors.interface_count)
        info += bytes(numbers) + bytes(classes) + bytes(subclasses) + bytes(protocols)
        self._emit(self.codec.pack(INTERFACE_INFO, 0, info))
        types = bytearray([EP_INVALID]) * 32
        intervals = bytearray(32)
        ifaces = bytearray(32)
        sizes = [0] * 32
        types[0] = EP_CONTROL
        sizes[0] = 64

        def put(address: int, kind: str, interval: int, interface: int, size: int) -> None:
            index = ((address & 0x80) >> 3) | (address & 0x0F)
            types[index] = {"bulk": EP_BULK, "interrupt": EP_INTERRUPT}[kind]
            intervals[index] = interval
            ifaces[index] = interface
            sizes[index] = size

        for endpoint in self.device.descriptors.endpoints():
            put(endpoint.address, endpoint.kind, endpoint.interval_hs, endpoint.interface, endpoint.max_packet_hs)
        ep = bytes(types) + bytes(intervals) + bytes(ifaces)
        if caps & CAP_EP_INFO_MAX_PACKET:
            ep += struct.pack("<32H", *sizes)
        self._emit(self.codec.pack(EP_INFO, 0, ep))
        # QEMU applies its device filter immediately on DEVICE_CONNECT; it
        # must already know interface classes and endpoint topology.
        self._emit(self.codec.pack(DEVICE_CONNECT, 0, connect))

    def _config_status(self, ident: int, requested: int | None) -> None:
        if requested is None:
            current = self.device.configuration
            status = ST_SUCCESS
        else:
            status = ST_SUCCESS if self.device.set_configuration(requested) else ST_STALL
            current = self.device.configuration if status == ST_SUCCESS else 0
        self._emit(self.codec.pack(CONFIGURATION_STATUS, ident, bytes((status, current))))

    def _control(self, ident: int, payload: bytes) -> None:
        endpoint, request, reqtype, _status, value, index, data = parse_control(payload)
        wlen = struct.unpack_from("<H", payload, 8)[0]
        log.debug("control type=%02x request=%02x value=%04x index=%d length=%d", reqtype, request, value, index, wlen)
        try:
            status, reply = self.device.control(reqtype, request, value, index, data, wlen)
        except Exception:
            log.exception("control transfer failed")
            status, reply = ST_STALL, b""
        if status != ST_SUCCESS:
            reply = b""
        header = struct.pack("<BBBBHHH", endpoint, request, reqtype, status, value, index, len(reply) if reqtype & 0x80 else wlen)
        self._emit(self.codec.pack(CONTROL, ident, header + reply))
        self._flush_notify()

    def _bulk(self, ident: int, payload: bytes) -> None:
        endpoint, _status, data = parse_bulk(payload, self.codec.negotiated)
        if endpoint & 0x80:
            wlen = struct.unpack_from("<H", payload, 2)[0]
            if self.codec.negotiated & CAP_32BIT_BULK and len(payload) >= 10:
                high = struct.unpack_from("<H", payload, 8)[0]
                wlen |= high << 16
            pulled = self.device.pull_in(endpoint, wlen)
            if pulled is None:
                self.pending.append((ident, endpoint, wlen))
                return
            status, blob = pulled
            self._emit(self.codec.pack(BULK, ident, bulk_header(endpoint, status, blob, self.codec.negotiated)))
            return
        self.device.push_out(endpoint, data)
        self._emit(self.codec.pack(BULK, ident, bulk_header(endpoint, ST_SUCCESS, b"", self.codec.negotiated)))
        self._flush_pending()
        self._flush_notify()

    def _flush_pending(self) -> None:
        kept = deque()
        while self.pending:
            ident, endpoint, wlen = self.pending.popleft()
            pulled = self.device.pull_in(endpoint, wlen)
            if pulled is None:
                kept.append((ident, endpoint, wlen))
                continue
            status, blob = pulled
            self._emit(self.codec.pack(BULK, ident, bulk_header(endpoint, status, blob, self.codec.negotiated)))
        self.pending = kept

    def _flush_notify(self) -> None:
        if 0x81 not in self.interrupt_on:
            return
        if self.device.take_notify():
            header = struct.pack("<BBH", 0x81, ST_SUCCESS, len(NOTIFY_RESPONSE_AVAILABLE))
            self._emit(self.codec.pack(INTERRUPT, 0, header + NOTIFY_RESPONSE_AVAILABLE))
