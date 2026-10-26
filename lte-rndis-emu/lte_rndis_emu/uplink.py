"""L2 uplink. The emulator forwards ethernet frames; it does not speak DHCP."""

from __future__ import annotations

import socket
import struct


SOL_PACKET = 263
PACKET_ADD_MEMBERSHIP = 1
PACKET_MR_PROMISC = 1
PACKET_IGNORE_OUTGOING = 23


class UplinkError(RuntimeError):
    pass


class MemoryUplink:
    """In-process peer used by tests and by `--uplink none`."""

    def __init__(self):
        self.tx: list[bytes] = []
        self.name = "none"

    def send(self, frame: bytes) -> None:
        self.tx.append(bytes(frame))

    def fileno(self):
        return None

    def drain(self) -> list[bytes]:
        return []

    def close(self) -> None:
        return None


class PacketUplink:
    """Raw ethernet on an existing interface (tap, veth, dummy, or bridge port)."""

    def __init__(self, name: str):
        self.name = name
        if not _valid_name(name):
            raise UplinkError(f"refusing interface name {name!r}")
        path = f"/sys/class/net/{name}"
        try:
            with open(path + "/address", encoding="ascii"):
                pass
        except OSError as exc:
            raise UplinkError(
                f"interface {name} does not exist. Create a tap first; "
                "the emulator will not create one and will not run DHCP on it."
            ) from exc
        try:
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
        except OSError as exc:
            raise UplinkError(f"AF_PACKET open failed: {exc}") from exc
        sock.setblocking(False)
        try:
            sock.bind((name, 0))
            index = socket.if_nametoindex(name)
            membership = struct.pack("IHH8s", index, PACKET_MR_PROMISC, 0, b"\x00" * 8)
            sock.setsockopt(SOL_PACKET, PACKET_ADD_MEMBERSHIP, membership)
        except OSError as exc:
            sock.close()
            raise UplinkError(f"cannot bind AF_PACKET to {name}: {exc}") from exc
        try:
            sock.setsockopt(SOL_PACKET, PACKET_IGNORE_OUTGOING, 1)
        except OSError:
            # Own transmissions may be echoed. The agent must not loop this
            # interface back into the same bridge.
            pass
        self._sock = sock

    def send(self, frame: bytes) -> None:
        self._sock.send(frame)

    def fileno(self):
        return self._sock.fileno()

    def drain(self) -> list[bytes]:
        frames = []
        while True:
            try:
                frame = self._sock.recv(65535)
            except BlockingIOError:
                break
            if len(frame) >= 14:
                frames.append(frame)
        return frames

    def close(self) -> None:
        self._sock.close()


def open_uplink(name: str):
    if name in ("", "none"):
        return MemoryUplink()
    return PacketUplink(name)


def _valid_name(name: str) -> bool:
    if not 1 <= len(name) <= 15:
        return False
    return all(ch.isalnum() or ch in "_.-" for ch in name)
