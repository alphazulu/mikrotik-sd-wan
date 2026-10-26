"""Composite USB device: RNDIS data plane plus optional CDC ACM AT port."""

from __future__ import annotations

import logging
import threading
from collections import deque

from lte_rndis_emu.atport import AtPort
from lte_rndis_emu.descriptors import Descriptors, UsbIdentity
from lte_rndis_emu.rndis import RndisEngine, ethernet_frames, wrap_ethernet
from lte_rndis_emu.state import LteState

log = logging.getLogger("lte_rndis_emu")

ST_SUCCESS = 0
ST_STALL = 4
ST_BABBLE = 6

GET_STATUS = 0
SET_ADDRESS = 5
GET_DESCRIPTOR = 6
GET_CONFIGURATION = 8
SET_CONFIGURATION = 9
GET_INTERFACE = 10
SET_INTERFACE = 11
SEND_ENCAPSULATED = 0x00
GET_ENCAPSULATED = 0x01
SET_LINE_CODING = 0x20
GET_LINE_CODING = 0x21
SET_CONTROL_LINE_STATE = 0x22


def parse_mac(text: str) -> bytes:
    parts = text.split(":")
    if len(parts) != 6:
        raise ValueError("MAC must look like 02:12:d1:14:db:02")
    raw = bytes(int(part, 16) for part in parts)
    if len(raw) != 6:
        raise ValueError("MAC must be 6 bytes")
    return raw


class UsbDevice:
    def __init__(self, identity: UsbIdentity, host_mac: bytes, state: LteState, on_tx, uplink_name: str, gate: bool):
        self.identity = identity
        self.descriptors = Descriptors(identity)
        self.host_mac = host_mac
        self.state = state
        self.on_tx = on_tx
        self.uplink_name = uplink_name
        self.gate = gate
        self.lock = threading.Lock()
        self.configuration = 0
        self.rndis = RndisEngine(host_mac, identity.product, state.get)
        self.at = AtPort(state.get)
        self.responses: deque[bytes] = deque()
        self.rx_pkts: deque[bytes] = deque()
        self.at_pkts: deque[bytes] = deque()
        self._out_buf = b""
        self._notify = False
        self._line_coding = b"\x00\xc2\x01\x00\x00\x00\x08"  # 115200 8N1
        self.counters = {"tx_frames": 0, "rx_frames": 0, "dropped": 0}

    def set_configuration(self, value: int) -> bool:
        with self.lock:
            if value not in (0, 1):
                return False
            self.configuration = value
            if value == 0:
                self.rndis.reset_engine()
            return True

    def usb_reset(self) -> None:
        with self.lock:
            self.configuration = 0
            self.rndis.reset_engine()
            self.at.reset()
            self.responses.clear()
            self.rx_pkts.clear()
            self.at_pkts.clear()
            self._out_buf = b""
            self._notify = False

    def snapshot(self) -> dict:
        with self.lock:
            data = self.state.get()
            data["usb"] = {
                "vid": f"{self.identity.vid:04x}",
                "pid": f"{self.identity.pid:04x}",
                "serial": self.identity.serial,
                "profile": self.identity.profile,
                "host_mac": ":".join(f"{byte:02x}" for byte in self.host_mac),
                "configuration": self.configuration,
                "packet_filter": self.rndis.filter,
                "rndis_initialized": self.rndis.initialized,
            }
            data["uplink"] = self.uplink_name
            data["gate"] = self.gate
            data["counters"] = dict(self.counters)
            data["forwarding"] = self._forward_allowed_unlocked()
            return data

    def update_lte(self, patch: dict) -> dict:
        with self.lock:
            updated = self.state.update(patch)
        return self.snapshot() if updated is not None else updated

    def take_notify(self) -> bool:
        with self.lock:
            pending = self._notify
            self._notify = False
            return pending

    def control(self, reqtype: int, request: int, value: int, index: int, data: bytes, wlen: int):
        with self.lock:
            direction_in = bool(reqtype & 0x80)
            kind = reqtype & 0x60
            if kind == 0x20:
                return self._class(direction_in, request, value, index, data, wlen)
            if kind != 0:
                return ST_STALL, b""
            return self._standard(direction_in, request, value, index, wlen)

    def push_out(self, endpoint: int, data: bytes) -> None:
        if endpoint == 0x02:
            self._rndis_out(data)
            return
        if endpoint == 0x04 and self.identity.profile == "at":
            self._at_out(data)
            return
        log.debug("ignoring bulk OUT on endpoint %#x", endpoint)

    def pull_in(self, endpoint: int, wlen: int):
        with self.lock:
            queue = None
            if endpoint == 0x82:
                queue = self.rx_pkts
            elif endpoint == 0x84 and self.identity.profile == "at":
                queue = self.at_pkts
            if queue is None:
                return ST_STALL, b""
            if not queue:
                return None
            if wlen < len(queue[0]):
                queue.popleft()
                self.counters["dropped"] += 1
                return ST_BABBLE, b""
            return ST_SUCCESS, queue.popleft()

    def enqueue_rx(self, frame: bytes) -> None:
        if len(frame) < 14:
            return
        with self.lock:
            if not self._forward_allowed_unlocked():
                self.counters["dropped"] += 1
                return
            self.rx_pkts.append(wrap_ethernet(bytes(frame)))
            self.rndis.rx_ok += 1
            self.counters["rx_frames"] += 1

    def _forward_allowed_unlocked(self) -> bool:
        if self.configuration != 1 or not self.rndis.initialized or self.rndis.filter == 0:
            return False
        if self.gate:
            status = self.state.get()["registration_status"]
            if status not in ("registered", "roaming"):
                return False
        return True

    def _rndis_out(self, data: bytes) -> None:
        forwarded = []
        with self.lock:
            self._out_buf += data
            frames, self._out_buf = ethernet_frames(self._out_buf)
            for frame in frames:
                if not self._forward_allowed_unlocked():
                    self.counters["dropped"] += 1
                    continue
                self.rndis.tx_ok += 1
                forwarded.append(frame)
        for frame in forwarded:
            try:
                self.on_tx(frame)
            except OSError as exc:
                log.warning("uplink send failed: %s", exc)
                with self.lock:
                    self.counters["dropped"] += 1
                    self.rndis.tx_ok = max(0, self.rndis.tx_ok - 1)
            else:
                with self.lock:
                    self.counters["tx_frames"] += 1

    def _at_out(self, data: bytes) -> None:
        with self.lock:
            for reply in self.at.feed(data):
                self.at_pkts.append(reply)

    def _class(self, direction_in, request, value, index, data, wlen):
        if index == 0 and request == SEND_ENCAPSULATED and not direction_in:
            self._accept_rndis(data)
            return ST_SUCCESS, b""
        if index == 0 and request == GET_ENCAPSULATED and direction_in:
            if not self.responses:
                self._notify = False
                return ST_STALL, b""
            payload = self.responses.popleft()
            self._notify = bool(self.responses)
            if wlen < len(payload):
                payload = payload[:wlen]
            return ST_SUCCESS, payload
        if self.identity.profile == "at" and index == 2:
            if request == SET_LINE_CODING and not direction_in and len(data) >= 7:
                self._line_coding = data[:7]
                return ST_SUCCESS, b""
            if request == GET_LINE_CODING and direction_in:
                return ST_SUCCESS, self._clip(self._line_coding, wlen)
            if request == SET_CONTROL_LINE_STATE and not direction_in:
                return ST_SUCCESS, b""
        return ST_STALL, b""

    def _accept_rndis(self, data: bytes) -> None:
        buf = data
        while len(buf) >= 8:
            msg_len = int.from_bytes(buf[4:8], "little")
            if msg_len < 8 or msg_len > 65536:
                break
            if len(buf) < msg_len:
                break
            reply = self.rndis.handle(buf[:msg_len])
            buf = buf[msg_len:]
            if reply is not None:
                self.responses.append(reply)
                self._notify = True

    def _standard(self, direction_in, request, value, index, wlen):
        if request == GET_DESCRIPTOR and direction_in:
            return ST_SUCCESS, self._clip(self._descriptor(value >> 8, value & 0xFF), wlen)
        if request == SET_CONFIGURATION and not direction_in:
            if value not in (0, 1):
                return ST_STALL, b""
            self.configuration = value
            if value == 0:
                self.rndis.reset_engine()
            return ST_SUCCESS, b""
        if request == GET_CONFIGURATION and direction_in:
            return ST_SUCCESS, self._clip(bytes((self.configuration,)), wlen)
        if request == SET_ADDRESS:
            return ST_SUCCESS, b""
        if request == GET_STATUS and direction_in:
            return ST_SUCCESS, self._clip(b"\x00\x00", wlen)
        if request == SET_INTERFACE and value == 0:
            return ST_SUCCESS, b""
        if request == GET_INTERFACE and direction_in:
            return ST_SUCCESS, self._clip(b"\x00", wlen)
        if request in (1, 3):  # CLEAR_FEATURE / SET_FEATURE, tolerated
            return ST_SUCCESS, b""
        return ST_STALL, b""

    def _descriptor(self, kind: int, index: int) -> bytes:
        if kind == 1 and index == 0:
            return self.descriptors.device
        if kind == 2 and index == 0:
            return self.descriptors.hs_config
        if kind == 3:
            return self.descriptors.strings.get(index, b"")
        if kind == 6 and index == 0:
            return self.descriptors.qualifier
        if kind == 7 and index == 0:
            return self.descriptors.other_speed
        return b""

    @staticmethod
    def _clip(payload: bytes, wlen: int) -> bytes:
        if not payload:
            return b""
        if wlen < len(payload):
            return payload[:wlen]
        return payload
