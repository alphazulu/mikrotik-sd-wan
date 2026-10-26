"""Agent-facing LTE management state.

RouterOS may never read this. The HTTP control API and the optional AT port do.
Radio fields do not allocate addresses and do not answer DHCP.
"""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy


REGISTRATION = ("registered", "roaming", "searching", "denied", "unknown")
PIN_STATUS = ("ready", "sim-pin", "absent")
RAT = ("LTE", "UMTS", "GSM", "NR")

MUTABLE = (
    "manufacturer",
    "model",
    "revision",
    "imei",
    "imsi",
    "iccid",
    "operator",
    "operator_numeric",
    "access_technology",
    "registration_status",
    "rssi",
    "rsrp",
    "rsrq",
    "sinr",
    "lac",
    "cell_id",
    "pin_status",
    "functionality",
    "apn",
    "link_bps",
)

_INTS = ("rssi", "rsrp", "rsrq", "sinr", "link_bps")
_STRS = (
    "manufacturer",
    "model",
    "revision",
    "imei",
    "imsi",
    "iccid",
    "operator",
    "operator_numeric",
    "lac",
    "cell_id",
    "functionality",
    "apn",
)


def defaults() -> dict:
    return {
        "source": "emulator",
        "manufacturer": "HUAWEI",
        "model": "E3372",
        "revision": "emu-1.0",
        "imei": "358240051111110",
        "imsi": "001010000000001",
        "iccid": "8900100000000000019",
        "operator": "TEST",
        "operator_numeric": "00101",
        "access_technology": "LTE",
        "registration_status": "registered",
        "rssi": -75,
        "rsrp": -95,
        "rsrq": -10,
        "sinr": 12,
        "lac": "0001",
        "cell_id": "0000001",
        "pin_status": "ready",
        "functionality": "full",
        "apn": "internet",
        # Informational only. NDIS link speed reports this value / 100.
        # It does not shape the bridged frames.
        "link_bps": 150_000_000,
    }


class StateError(ValueError):
    pass


class LteState:
    def __init__(self, path: str | None = None):
        self.path = path
        self._lock = threading.Lock()
        self._data = defaults()
        self._mtime: float | None = None
        if path and os.path.exists(path):
            self._load_unlocked()

    def get(self) -> dict:
        with self._lock:
            self._reload_unlocked()
            return deepcopy(self._data)

    def update(self, patch: dict) -> dict:
        if not isinstance(patch, dict):
            raise StateError("JSON object required")
        with self._lock:
            self._reload_unlocked()
            for key, value in patch.items():
                if key not in MUTABLE:
                    continue
                self._data[key] = self._check(key, value)
            self._data["source"] = "emulator"
            if self.path:
                self._write_unlocked()
            return deepcopy(self._data)

    def _check(self, key: str, value):
        if key == "registration_status":
            if value not in REGISTRATION:
                raise StateError(
                    "registration_status must be one of " + ", ".join(REGISTRATION)
                )
            return value
        if key == "pin_status":
            if value not in PIN_STATUS:
                raise StateError("pin_status must be one of " + ", ".join(PIN_STATUS))
            return value
        if key == "access_technology":
            if value not in RAT:
                raise StateError("access_technology must be one of " + ", ".join(RAT))
            return value
        if key in _INTS:
            if isinstance(value, bool) or not isinstance(value, int):
                raise StateError(f"{key} must be an integer")
            if key == "link_bps" and value < 0:
                raise StateError("link_bps must be >= 0")
            return value
        if key in _STRS:
            if not isinstance(value, str) or not value or len(value) > 64:
                raise StateError(f"{key} must be a string of 1..64 characters")
            return value
        raise StateError(key)

    def _reload_unlocked(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        mtime = os.path.getmtime(self.path)
        if self._mtime is not None and mtime == self._mtime:
            return
        self._load_unlocked()

    def _load_unlocked(self) -> None:
        with open(self.path, encoding="utf-8") as handle:
            raw = json.load(handle)
        if not isinstance(raw, dict):
            raise StateError("state file must be a JSON object")
        data = defaults()
        for key in MUTABLE:
            if key in raw:
                data[key] = self._check(key, raw[key])
        self._data = data
        self._mtime = os.path.getmtime(self.path)

    def _write_unlocked(self) -> None:
        parent = os.path.dirname(self.path) or "."
        os.makedirs(parent, exist_ok=True)
        tmp = self.path + ".tmp"
        payload = {key: self._data[key] for key in ("source", *MUTABLE)}
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self.path)
        self._mtime = os.path.getmtime(self.path)
