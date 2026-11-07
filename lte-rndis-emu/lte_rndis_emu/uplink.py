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


class SocketUplink:
    """QEMU socket netdev: a network-order length followed by Ethernet bytes.

    One loopback peer, bounded buffers, no privileges, IP or DHCP server.
    QEMU connects using ``-netdev socket,id=lte,connect=127.0.0.1:PORT``.
    """

    MAX_FRAME = 65535
    MAX_QUEUE = 1 << 20

    def __init__(self, address: str):
        try:
            host, port = address.rsplit(":", 1)
            if host != "127.0.0.1":
                raise ValueError("only 127.0.0.1 is allowed")
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((host, int(port)))
            self.server.listen(1)
            self.server.setblocking(False)
        except (OSError, ValueError) as exc:
            if hasattr(self, "server"):
                self.server.close()
            raise UplinkError(f"socket uplink: {exc}") from exc
        self.name = f"socket:127.0.0.1:{self.server.getsockname()[1]}"
        self.peer = None
        self.rx = bytearray()
        self.tx = bytearray()
        self.counters = {"tx_frames": 0, "rx_frames": 0, "disconnects": 0, "invalid": 0}

    def filenos(self):
        return [self.server] + ([self.peer] if self.peer is not None else [])

    def writable(self):
        return [self.peer] if self.peer is not None and self.tx else []

    def _disconnect(self):
        if self.peer is not None:
            self.peer.close()
            self.peer = None
            self.counters["disconnects"] += 1
        self.rx.clear()
        self.tx.clear()

    def send(self, frame: bytes) -> None:
        if self.peer is None:
            raise OSError("socket uplink has no peer")
        if not 14 <= len(frame) <= self.MAX_FRAME:
            raise OSError("invalid Ethernet frame length")
        if len(self.tx) + len(frame) + 4 > self.MAX_QUEUE:
            raise BlockingIOError("socket uplink queue full")
        self.tx.extend(struct.pack("!I", len(frame)) + frame)
        self.counters["tx_frames"] += 1
        self.flush()

    def flush(self):
        while self.peer is not None and self.tx:
            try:
                sent = self.peer.send(self.tx)
                if sent == 0:
                    raise ConnectionError("closed uplink")
            except BlockingIOError:
                break
            except OSError:
                self._disconnect()
                break
            del self.tx[:sent]

    def drain(self) -> list[bytes]:
        # Accept/drain even before USB attaches, so a pending peer never spins
        # the select loop. Never retain Ethernet from a previous USB session.
        try:
            extra, address = self.server.accept()
        except BlockingIOError:
            pass
        else:
            if self.peer is not None or address[0] != "127.0.0.1":
                extra.close()
            else:
                extra.setblocking(False)
                self.peer = extra
        frames = []
        budget = self.MAX_QUEUE
        while self.peer is not None and budget > 0:
            try:
                data = self.peer.recv(min(65536, budget))
            except BlockingIOError:
                break
            except OSError:
                self._disconnect()
                break
            if not data:
                self._disconnect()
                break
            budget -= len(data)
            self.rx.extend(data)
            while len(self.rx) >= 4:
                length = struct.unpack_from("!I", self.rx)[0]
                if not 14 <= length <= self.MAX_FRAME:
                    self.counters["invalid"] += 1
                    self._disconnect()
                    return frames
                if len(self.rx) < length + 4:
                    break
                frames.append(bytes(self.rx[4:4 + length]))
                del self.rx[:4 + length]
                self.counters["rx_frames"] += 1
        return frames

    def close(self):
        self._disconnect()
        self.server.close()


def open_uplink(name: str):
    if name in ("", "none"):
        return MemoryUplink()
    if name.startswith("socket:"):
        return SocketUplink(name[len("socket:"):])
    return PacketUplink(name)


def _valid_name(name: str) -> bool:
    if not 1 <= len(name) <= 15:
        return False
    return all(ch.isalnum() or ch in "_.-" for ch in name)
