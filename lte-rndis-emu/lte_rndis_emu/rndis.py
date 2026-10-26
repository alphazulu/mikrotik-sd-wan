"""RNDIS control messages, matching the Linux gadget responses RouterOS hosts use.

Offsets follow MS-RNDIS: InformationBufferOffset is relative to RequestID.
"""

from __future__ import annotations

import struct

MSG_PACKET = 0x00000001
MSG_INIT = 0x00000002
MSG_INIT_C = 0x80000002
MSG_HALT = 0x00000003
MSG_QUERY = 0x00000004
MSG_QUERY_C = 0x80000004
MSG_SET = 0x00000005
MSG_SET_C = 0x80000005
MSG_RESET = 0x00000006
MSG_RESET_C = 0x80000006
MSG_KEEPALIVE = 0x00000008
MSG_KEEPALIVE_C = 0x80000008

STATUS_SUCCESS = 0x00000000
STATUS_FAILURE = 0xC0000001
STATUS_NOT_SUPPORTED = 0xC00000BB

MEDIA_CONNECTED = 0
MEDIA_DISCONNECTED = 1
PHYSICAL_MEDIUM_WIRELESS_WAN = 8
DF_CONNECTIONLESS = 1
MEDIUM_802_3 = 0

OID_GEN_SUPPORTED_LIST = 0x00010101
OID_GEN_HARDWARE_STATUS = 0x00010102
OID_GEN_MEDIA_SUPPORTED = 0x00010103
OID_GEN_MEDIA_IN_USE = 0x00010104
OID_GEN_MAXIMUM_FRAME_SIZE = 0x00010106
OID_GEN_LINK_SPEED = 0x00010107
OID_GEN_TRANSMIT_BLOCK_SIZE = 0x0001010A
OID_GEN_RECEIVE_BLOCK_SIZE = 0x0001010B
OID_GEN_VENDOR_ID = 0x0001010C
OID_GEN_VENDOR_DESCRIPTION = 0x0001010D
OID_GEN_CURRENT_PACKET_FILTER = 0x0001010E
OID_GEN_MAXIMUM_TOTAL_SIZE = 0x00010111
OID_GEN_MEDIA_CONNECT_STATUS = 0x00010114
OID_GEN_VENDOR_DRIVER_VERSION = 0x00010116
OID_GEN_PHYSICAL_MEDIUM = 0x00010202
OID_GEN_MAC_OPTIONS = 0x00010113
OID_GEN_XMIT_OK = 0x00020101
OID_GEN_RCV_OK = 0x00020102
OID_GEN_XMIT_ERROR = 0x00020103
OID_GEN_RCV_ERROR = 0x00020104
OID_GEN_RCV_NO_BUFFER = 0x00020105
OID_802_3_PERMANENT_ADDRESS = 0x01010101
OID_802_3_CURRENT_ADDRESS = 0x01010102
OID_802_3_MULTICAST_LIST = 0x01010103
OID_802_3_MAXIMUM_LIST_SIZE = 0x01010104
OID_802_3_MAC_OPTIONS = 0x01010105
OID_802_3_RCV_ERROR_ALIGNMENT = 0x01020101
OID_802_3_XMIT_ONE_COLLISION = 0x01020102
OID_802_3_XMIT_MORE_COLLISIONS = 0x01020103

SUPPORTED_OIDS = (
    OID_GEN_SUPPORTED_LIST,
    OID_GEN_HARDWARE_STATUS,
    OID_GEN_MEDIA_SUPPORTED,
    OID_GEN_MEDIA_IN_USE,
    OID_GEN_MAXIMUM_FRAME_SIZE,
    OID_GEN_LINK_SPEED,
    OID_GEN_TRANSMIT_BLOCK_SIZE,
    OID_GEN_RECEIVE_BLOCK_SIZE,
    OID_GEN_VENDOR_ID,
    OID_GEN_VENDOR_DESCRIPTION,
    OID_GEN_CURRENT_PACKET_FILTER,
    OID_GEN_MAXIMUM_TOTAL_SIZE,
    OID_GEN_MEDIA_CONNECT_STATUS,
    OID_GEN_VENDOR_DRIVER_VERSION,
    OID_GEN_PHYSICAL_MEDIUM,
    OID_GEN_MAC_OPTIONS,
    OID_GEN_XMIT_OK,
    OID_GEN_RCV_OK,
    OID_GEN_XMIT_ERROR,
    OID_GEN_RCV_ERROR,
    OID_GEN_RCV_NO_BUFFER,
    OID_802_3_PERMANENT_ADDRESS,
    OID_802_3_CURRENT_ADDRESS,
    OID_802_3_MULTICAST_LIST,
    OID_802_3_MAXIMUM_LIST_SIZE,
    OID_802_3_MAC_OPTIONS,
    OID_802_3_RCV_ERROR_ALIGNMENT,
    OID_802_3_XMIT_ONE_COLLISION,
    OID_802_3_XMIT_MORE_COLLISIONS,
)

MTU = 1500
MAX_TOTAL = 1580
NOTIFY_RESPONSE_AVAILABLE = b"\x01\x00\x00\x00\x00\x00\x00\x00"


def wrap_ethernet(frame: bytes) -> bytes:
    """One REMOTE_NDIS_PACKET_MSG. DataOffset 36 points just past the 44-byte header."""
    return struct.pack(
        "<IIIIIIIIIII",
        MSG_PACKET,
        44 + len(frame),
        36,
        len(frame),
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ) + frame


def ethernet_frames(blob: bytes) -> tuple[list[bytes], bytes]:
    """Split a bulk buffer into ethernet frames. Return leftover bytes."""
    frames: list[bytes] = []
    buf = blob
    while len(buf) >= 8:
        msg_len = struct.unpack_from("<I", buf, 4)[0]
        if msg_len < 8 or msg_len > 65536:
            return frames, b""
        if len(buf) < msg_len:
            break
        msg, buf = buf[:msg_len], buf[msg_len:]
        msg_type = struct.unpack_from("<I", msg, 0)[0]
        if msg_type != MSG_PACKET or len(msg) < 44:
            continue
        data_off, data_len = struct.unpack_from("<II", msg, 8)
        start = 8 + data_off
        frame = msg[start : start + data_len]
        if len(frame) >= 14:
            frames.append(frame)
    return frames, buf


def _u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def _query_c(req_id: int, status: int, data: bytes = b"") -> bytes:
    return struct.pack("<IIIIII", MSG_QUERY_C, 24 + len(data), req_id, status, len(data), 16) + data


def _set_c(req_id: int, status: int) -> bytes:
    return struct.pack("<IIII", MSG_SET_C, 16, req_id, status)


class RndisEngine:
    """Stateful RNDIS responder. `host_mac` is the address the USB host should adopt."""

    def __init__(self, host_mac: bytes, vendor: str, state_provider):
        if len(host_mac) != 6:
            raise ValueError("host_mac must be 6 bytes")
        self.host_mac = host_mac
        self.vendor = vendor
        self._state = state_provider
        self.initialized = False
        self.filter = 0
        self.tx_ok = 0
        self.rx_ok = 0

    def reset_engine(self) -> None:
        self.initialized = False
        self.filter = 0

    def handle(self, msg: bytes) -> bytes | None:
        if len(msg) < 12:
            return None
        msg_type, msg_len, req_id = struct.unpack_from("<III", msg, 0)
        if msg_type == MSG_INIT:
            self.initialized = True
            self.filter = 0
            return struct.pack(
                "<IIIIIIIIIIIII",
                MSG_INIT_C,
                52,
                req_id,
                STATUS_SUCCESS,
                1,
                0,
                DF_CONNECTIONLESS,
                MEDIUM_802_3,
                1,
                MAX_TOTAL,
                0,
                0,
                0,
            )
        if msg_type == MSG_HALT:
            self.reset_engine()
            return None
        if msg_type == MSG_RESET:
            self.reset_engine()
            return struct.pack("<IIII", MSG_RESET_C, 16, STATUS_SUCCESS, 1)
        if msg_type == MSG_KEEPALIVE:
            return struct.pack("<IIII", MSG_KEEPALIVE_C, 16, req_id, STATUS_SUCCESS)
        if not self.initialized:
            if msg_type == MSG_QUERY:
                return _query_c(req_id, STATUS_FAILURE)
            if msg_type == MSG_SET:
                return _set_c(req_id, STATUS_FAILURE)
            return None
        if msg_type == MSG_QUERY:
            return self._query(req_id, msg)
        if msg_type == MSG_SET:
            return self._set(req_id, msg)
        return None

    def _info(self, msg: bytes) -> bytes:
        if len(msg) < 28:
            return b""
        length, offset = struct.unpack_from("<II", msg, 16)
        start = 8 + offset
        return msg[start : start + length]

    def _query(self, req_id: int, msg: bytes) -> bytes:
        oid = struct.unpack_from("<I", msg, 12)[0]
        data = self._oid(oid)
        if data is None:
            return _query_c(req_id, STATUS_NOT_SUPPORTED)
        return _query_c(req_id, STATUS_SUCCESS, data)

    def _set(self, req_id: int, msg: bytes) -> bytes:
        oid = struct.unpack_from("<I", msg, 12)[0]
        if oid == OID_GEN_CURRENT_PACKET_FILTER:
            raw = self._info(msg)
            if len(raw) < 4:
                return _set_c(req_id, STATUS_FAILURE)
            self.filter = struct.unpack_from("<I", raw, 0)[0]
            return _set_c(req_id, STATUS_SUCCESS)
        if oid == OID_802_3_MULTICAST_LIST:
            return _set_c(req_id, STATUS_SUCCESS)
        return _set_c(req_id, STATUS_NOT_SUPPORTED)

    def _oid(self, oid: int) -> bytes | None:
        radio = self._state()
        connected = radio["registration_status"] in ("registered", "roaming")
        if oid == OID_GEN_SUPPORTED_LIST:
            return b"".join(_u32(item) for item in SUPPORTED_OIDS)
        if oid == OID_GEN_HARDWARE_STATUS:
            return _u32(0)
        if oid in (OID_GEN_MEDIA_SUPPORTED, OID_GEN_MEDIA_IN_USE):
            return _u32(MEDIUM_802_3)
        if oid in (OID_GEN_MAXIMUM_FRAME_SIZE, OID_GEN_TRANSMIT_BLOCK_SIZE, OID_GEN_RECEIVE_BLOCK_SIZE):
            return _u32(MTU)
        if oid == OID_GEN_LINK_SPEED:
            return _u32(int(radio["link_bps"]) // 100)
        if oid == OID_GEN_VENDOR_ID:
            return _u32(0)
        if oid == OID_GEN_VENDOR_DESCRIPTION:
            text = (self.vendor or "LTE RNDIS emu").encode("ascii", "replace") + b"\x00"
            return text
        if oid == OID_GEN_CURRENT_PACKET_FILTER:
            return _u32(self.filter)
        if oid == OID_GEN_MAXIMUM_TOTAL_SIZE:
            return _u32(MAX_TOTAL)
        if oid == OID_GEN_MEDIA_CONNECT_STATUS:
            return _u32(MEDIA_CONNECTED if connected else MEDIA_DISCONNECTED)
        if oid == OID_GEN_VENDOR_DRIVER_VERSION:
            return _u32(1)
        if oid == OID_GEN_PHYSICAL_MEDIUM:
            # Not a VID/PID trick: NDIS physical medium wireless WAN.
            return _u32(PHYSICAL_MEDIUM_WIRELESS_WAN)
        if oid == OID_GEN_MAC_OPTIONS:
            return _u32(0x00000021)  # receive serialized | full duplex
        if oid == OID_GEN_XMIT_OK:
            return _u32(self.tx_ok)
        if oid == OID_GEN_RCV_OK:
            return _u32(self.rx_ok)
        if oid in (OID_GEN_XMIT_ERROR, OID_GEN_RCV_ERROR, OID_GEN_RCV_NO_BUFFER):
            return _u32(0)
        if oid in (OID_802_3_PERMANENT_ADDRESS, OID_802_3_CURRENT_ADDRESS):
            return self.host_mac
        if oid == OID_802_3_MULTICAST_LIST:
            return b""
        if oid == OID_802_3_MAXIMUM_LIST_SIZE:
            return _u32(1)
        if oid in (
            OID_802_3_MAC_OPTIONS,
            OID_802_3_RCV_ERROR_ALIGNMENT,
            OID_802_3_XMIT_ONE_COLLISION,
            OID_802_3_XMIT_MORE_COLLISIONS,
        ):
            return _u32(0)
        return None
