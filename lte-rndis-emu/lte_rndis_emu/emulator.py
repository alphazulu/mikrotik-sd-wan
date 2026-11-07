"""CLI. Read USAGE.md before attaching this to a CHR lab."""

from __future__ import annotations

import argparse
import json
import logging
import select
import shlex
import socket
import subprocess
import sys

from lte_rndis_emu import __version__
from lte_rndis_emu.control import ControlServer
from lte_rndis_emu.descriptors import UsbIdentity, lsusb_text
from lte_rndis_emu.device import UsbDevice, parse_mac
from lte_rndis_emu.probe import report
from lte_rndis_emu.state import LteState
from lte_rndis_emu.uplink import UplinkError, open_uplink
from lte_rndis_emu.usbredir import ProtocolError, Session


def _loopback(host: str) -> str:
    if host == "localhost":
        return "127.0.0.1"
    if host not in ("127.0.0.1", "::1"):
        raise SystemExit("refusing to bind outside loopback: " + host)
    return host


def _split_host_port(text: str) -> tuple[str, int]:
    if text == "none":
        raise ValueError("none")
    host, _, port = text.rpartition(":")
    if not host:
        raise SystemExit(f"expected host:port, got {text}")
    return _loopback(host), int(port)


def _parse_id(text: str) -> int:
    value = int(text, 0)
    if not 0 <= value <= 0xFFFF:
        raise SystemExit(f"USB id out of range: {text}")
    return value


def qemu_chardev(port: int) -> str:
    base = f"socket,id=lteusb,host=127.0.0.1,port={port}"
    qemu = _qemu_bin()
    if not qemu:
        return base
    try:
        result = subprocess.run(
            [qemu, "-chardev", "socket,help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return base
    text = (result.stdout or "") + (result.stderr or "")
    if "reconnect-ms" in text:
        return base + ",reconnect-ms=2000"
    if "reconnect=" in text:
        return base + ",reconnect=2"
    return base


def qemu_args(port: int = 24320) -> list[str]:
    return [
        "-device",
        "qemu-xhci,id=xhci",
        "-chardev",
        qemu_chardev(port),
        "-device",
        "usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0",
    ]


def _qemu_bin() -> str | None:
    from shutil import which

    return which("qemu-system-x86_64")


def build_device(args, on_tx, uplink_name: str) -> UsbDevice:
    identity = UsbIdentity(
        vid=_parse_id(args.vid),
        pid=_parse_id(args.pid),
        manufacturer="HUAWEI",
        product="HUAWEI Mobile",
        serial=args.serial,
        profile=args.profile,
    )
    return UsbDevice(
        identity=identity,
        host_mac=parse_mac(args.host_mac),
        state=LteState(args.state),
        on_tx=on_tx,
        uplink_name=uplink_name,
        gate=args.gate,
    )


def serve(args) -> int:
    name = args.uplink if args.uplink is not None else args.uplink_pos
    if name is None:
        raise SystemExit("serve requires --uplink IFACE, or --uplink none for USB-only")
    try:
        uplink = open_uplink(name)
    except UplinkError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    host, port = _split_host_port(args.listen)
    device = build_device(args, uplink.send, uplink.name)
    control = None
    if args.control != "none":
        control_host, control_port = _split_host_port(args.control)
        try:
            control = ControlServer(device, control_host, control_port)
        except OSError as exc:
            uplink.close()
            print(f"control bind failed: {exc}", file=sys.stderr)
            return 2
        control.serve_forever_thread = __import__("threading").Thread(
            target=control.serve_forever, name="lte-control", daemon=True
        )
        control.serve_forever_thread.start()
    server = socket.socket(socket.AF_INET6 if host == "::1" else socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host, port))
    except OSError as exc:
        print(f"usbredir bind failed: {exc}", file=sys.stderr)
        server.close()
        uplink.close()
        if control is not None:
            control.shutdown()
            control.server_close()
            control.serve_forever_thread.join(timeout=2)
        return 2
    server.listen(1)
    server.setblocking(False)
    bound_port = server.getsockname()[1]
    control_text = "none" if control is None else f"{control.server_address[0]}:{control.server_address[1]}"
    print(
        f"ready usbredir={host}:{bound_port} control={control_text} "
        f"uplink={uplink.name} profile={args.profile} "
        f"vid={args.vid} pid={args.pid} gate={int(args.gate)}",
        flush=True,
    )
    print("qemu " + " ".join(shlex.quote(part) for part in qemu_args(bound_port)), file=sys.stderr)
    client = None
    session = None
    out = bytearray()

    def flush() -> bool:
        nonlocal client
        if client is None:
            return False
        while out:
            try:
                sent = client.send(out)
            except BlockingIOError:
                return True
            except OSError:
                return False
            if sent == 0:
                return False
            del out[:sent]
        return True

    def drop_client():
        nonlocal client, session
        if client is not None:
            client.close()
        client = None
        session = None
        device.usb_reset()
        out.clear()

    try:
        while True:
            watch = [server]
            if client is not None:
                watch.append(client)
            uplink_fds = (uplink.filenos() if hasattr(uplink, "filenos")
                          else ([] if uplink.fileno() is None else [uplink.fileno()]))
            watch.extend(uplink_fds)
            write_set = [client] if client is not None and out else []
            uplink_writes = uplink.writable() if hasattr(uplink, "writable") else []
            readable, writable, _ = select.select(watch, write_set + uplink_writes, [], 0.5)
            if uplink_writes and any(fd in writable for fd in uplink_writes):
                uplink.flush()
            if client is not None and client in writable:
                if not flush():
                    drop_client()
            if server in readable:
                extra, addr = server.accept()
                peer = addr[0]
                if peer not in ("127.0.0.1", "::1"):
                    extra.close()
                    continue
                if client is not None:
                    extra.close()
                    log_exclusive()
                    continue
                extra.setblocking(False)
                client = extra
                out.clear()
                device.usb_reset()
                session = Session(device, out.extend)
                session.start()
                if not flush():
                    client.close()
                    client = None
                    session = None
            if client is not None and client in readable:
                try:
                    data = client.recv(65535)
                except OSError:
                    data = b""
                if not data:
                    client.close()
                    client = None
                    session = None
                    device.usb_reset()
                    out.clear()
                else:
                    assert session is not None
                    try:
                        session.receive(data)
                    except (ProtocolError, ValueError) as exc:
                        print(f"usbredir protocol error: {exc}", file=sys.stderr)
                        drop_client()
                        continue
                    if not flush():
                        client.close()
                        client = None
                        session = None
                        device.usb_reset()
                        out.clear()
            if any(fd in readable for fd in uplink_fds):
                for frame in uplink.drain():
                    if session is not None:
                        session.deliver_rx(frame)
                if client is not None and not flush():
                    client.close()
                    client = None
                    session = None
                    device.usb_reset()
                    out.clear()
    except KeyboardInterrupt:
        return 0
    finally:
        if client is not None:
            client.close()
        server.close()
        uplink.close()
        if control is not None:
            control.shutdown()
            control.server_close()
            control.serve_forever_thread.join(timeout=2)


def log_exclusive() -> None:
    print("rejected a second usbredir client; one QEMU owns the device", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lte_rndis_emu", description=f"LTE RNDIS emulator {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="print the USB path this kernel can run")

    enum = sub.add_parser("enumerate", help="print the USB identity the device will present")
    enum.add_argument("--profile", choices=("hilink", "at"), default="hilink")
    enum.add_argument("--vid", default="0x12d1")
    enum.add_argument("--pid", default="0x14db")
    enum.add_argument("--json", action="store_true")

    qemu = sub.add_parser("qemu-args", help="print the three QEMU arguments for the edge CHR")
    qemu.add_argument("--port", type=int, default=24320)

    serve_parser = sub.add_parser("serve", help="bridge RNDIS to --uplink and speak usbredir")
    serve_parser.add_argument("uplink_pos", nargs="?", default=None)
    serve_parser.add_argument("--uplink", default=None, help="host interface that carries ethernet, or none")
    serve_parser.add_argument("--listen", default="127.0.0.1:24320")
    serve_parser.add_argument("--control", default="127.0.0.1:24321", help="loopback HTTP, or none")
    serve_parser.add_argument("--profile", choices=("hilink", "at"), default="hilink")
    serve_parser.add_argument("--vid", default="0x12d1")
    serve_parser.add_argument("--pid", default="0x14db")
    serve_parser.add_argument("--serial", default="EMU00000001")
    serve_parser.add_argument("--host-mac", default="02:12:d1:14:db:02")
    serve_parser.add_argument("--state", default=None, help="JSON file for LTE management fields")
    serve_parser.add_argument("--gate", action="store_true", help="drop frames unless registration is registered or roaming")
    serve_parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    if args.cmd == "probe":
        json.dump(report(), sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
        return 0
    if args.cmd == "enumerate":
        identity = UsbIdentity(vid=_parse_id(args.vid), pid=_parse_id(args.pid), profile=args.profile)
        from lte_rndis_emu.descriptors import Descriptors

        desc = Descriptors(identity)
        if args.json:
            json.dump(
                {
                    "vid": f"{identity.vid:04x}",
                    "pid": f"{identity.pid:04x}",
                    "profile": identity.profile,
                    "interfaces": [
                        {"number": number, "class": klass, "subclass": sub, "protocol": proto}
                        for number, klass, sub, proto in desc.interfaces()
                    ],
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            sys.stdout.write(lsusb_text(desc))
        return 0
    if args.cmd == "qemu-args":
        parts = qemu_args(args.port)
        print(" ".join(shlex.quote(part) for part in parts))
        return 0
    if args.cmd == "serve":
        return serve(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
