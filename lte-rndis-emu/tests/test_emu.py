"""Host-side proof of enumeration, RNDIS bring-up, and L2 uplink forwarding."""

from __future__ import annotations

import json
import os
import struct
import unittest
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lte_rndis_emu.atport import AtPort, csq_from_rssi
from lte_rndis_emu.control import ControlServer
from lte_rndis_emu.descriptors import Descriptors, UsbIdentity
from lte_rndis_emu.device import UsbDevice, parse_mac
from lte_rndis_emu.probe import collect, decide
from lte_rndis_emu.rndis import (
    MSG_INIT,
    MSG_INIT_C,
    MSG_QUERY,
    MSG_QUERY_C,
    MSG_SET,
    OID_802_3_PERMANENT_ADDRESS,
    OID_GEN_LINK_SPEED,
    OID_GEN_MEDIA_CONNECT_STATUS,
    OID_GEN_PHYSICAL_MEDIUM,
    wrap_ethernet,
)
from lte_rndis_emu.state import LteState
from lte_rndis_emu.uplink import MemoryUplink, PacketUplink
from lte_rndis_emu.usbredir import (
    BULK,
    CONTROL,
    DEVICE_CONNECT,
    EP_INFO,
    HELLO,
    INTERFACE_INFO,
    OUR_CAPS,
    SET_CONFIGURATION,
    ST_SUCCESS,
    Codec,
    Session,
    bulk_header,
)


MAC = parse_mac("02:12:d1:14:db:02")


def _walk(blob: bytes):
    items = []
    index = 0
    while index + 1 < len(blob):
        length = blob[index]
        if length < 2 or index + length > len(blob):
            break
        items.append(blob[index : index + length])
        index += length
    return items


class DescriptorTests(unittest.TestCase):
    def test_hilink_matches_f_rndis_and_documented_ids(self):
        desc = Descriptors(UsbIdentity())
        self.assertEqual(desc.device[8:12], bytes((0xD1, 0x12, 0xDB, 0x14)))
        self.assertEqual(len(desc.hs_config), int.from_bytes(desc.hs_config[2:4], "little"))
        self.assertEqual(desc.hs_config[4], 2)
        interfaces = [item for item in _walk(desc.hs_config) if item[1] == 4]
        self.assertEqual(interfaces[0][5:8], bytes((0x02, 0x02, 0xFF)))
        self.assertEqual(interfaces[1][5:8], bytes((0x0A, 0x00, 0x00)))
        self.assertFalse(any(item[1] == 4 and item[7] == 0x01 for item in _walk(desc.hs_config)))
        iad = next(item for item in _walk(desc.hs_config) if item[1] == 0x0B)
        self.assertEqual(iad[4:7], bytes((0x02, 0x06, 0x00)))

    def test_at_profile_adds_cdc_acm_management_interfaces(self):
        desc = Descriptors(UsbIdentity(profile="at"))
        self.assertEqual(desc.hs_config[4], 4)
        protocols = [item[7] for item in _walk(desc.hs_config) if item[1] == 4]
        self.assertEqual(protocols, [0xFF, 0x00, 0x01, 0x00])


class Link:
    def __init__(self, profile="hilink", gate=False, state=None):
        self.uplink = MemoryUplink()
        self.state = state or LteState()
        self.device = UsbDevice(
            UsbIdentity(profile=profile),
            MAC,
            self.state,
            self.uplink.send,
            "none",
            gate,
        )
        self.out = bytearray()
        self.session = Session(self.device, self.out.extend)
        self.guest = Codec()
        self.session.start()
        hello = b"qemu usb-redir guest test".ljust(64, b"\x00") + struct.pack("<I", OUR_CAPS)
        self.session.receive(self.guest.pack(HELLO, 0, hello, force32=True))
        self.boot = self.pump()
        types = [p[0] for p in self.boot]
        assert types.index(INTERFACE_INFO) < types.index(DEVICE_CONNECT)
        assert types.index(EP_INFO) < types.index(DEVICE_CONNECT)

    def pump(self):
        data = bytes(self.out)
        self.out.clear()
        return self.guest.feed(data)

    def control(self, ident, reqtype, request, value, index, data=b"", wlen=None):
        if wlen is None:
            wlen = 0 if reqtype & 0x80 else len(data)
        payload = struct.pack("<BBBBHHH", reqtype & 0x80, request, reqtype, 0, value, index, wlen)
        if not reqtype & 0x80:
            payload += data
        self.session.receive(self.guest.pack(CONTROL, ident, payload))
        return self.pump()

    def bulk(self, ident, endpoint, data):
        self.session.receive(
            self.guest.pack(BULK, ident, bulk_header(endpoint, 0, data, self.guest.negotiated))
        )
        return self.pump()

    def bulk_in(self, ident, endpoint, size):
        low = size & 0xFFFF
        high = (size >> 16) & 0xFFFF
        header = struct.pack("<BBHIH", endpoint, 0, low, 0, high)
        self.session.receive(self.guest.pack(BULK, ident, header))
        return self.pump()


def _control_data(packet):
    _typ, _ident, payload = packet
    status = payload[3]
    return status, payload[10:]


def _rndis(msg_type, req_id, oid=None, info=b""):
    if msg_type == MSG_INIT:
        return struct.pack("<IIIIII", MSG_INIT, 24, req_id, 1, 0, 16384)
    if msg_type == MSG_QUERY:
        return struct.pack("<IIIIIII", MSG_QUERY, 28 + len(info), req_id, oid, len(info), 20, 0) + info
    if msg_type == MSG_SET:
        return struct.pack("<IIIIIII", MSG_SET, 28 + len(info), req_id, oid, len(info), 20, 0) + info
    raise AssertionError(msg_type)


class UsbRedirTests(unittest.TestCase):
    def test_rx_memory_is_bounded_and_reset_releases_queue(self):
        link = Link()
        link.device.set_configuration(1)
        link.device.rndis.initialized = True
        link.device.rndis.filter = 1
        frame = b"x" * 65535
        for _ in range(100):
            link.device.enqueue_rx(frame)
        self.assertLessEqual(link.device.rx_bytes, link.device.MAX_RX_BYTES)
        self.assertGreater(link.device.counters["dropped"], 0)
        while link.device.rx_pkts:
            link.device.pull_in(0x82, 65579)
        self.assertEqual(link.device.rx_bytes, 0)
        for _ in range(300):
            link.device.enqueue_rx(b"x" * 14)
        self.assertEqual(len(link.device.rx_pkts), 256)
        link.device.pull_in(0x82, 1)
        self.assertEqual(link.device.rx_bytes, sum(map(len, link.device.rx_pkts)))
        link.device.usb_reset()
        self.assertEqual(link.device.rx_bytes, 0)
        self.assertFalse(link.device.rx_pkts)

    def test_qemu_control_reply_preserves_in_endpoint(self):
        link = Link()
        packets = link.control(123, 0x80, 6, 0x0100, 0, wlen=64)
        typ, ident, payload = next(p for p in packets if p[0] == CONTROL)
        self.assertEqual((typ, ident, payload[0]), (CONTROL, 123, 0x80))
        self.assertEqual(payload[3], ST_SUCCESS)
        self.assertEqual(payload[10:], link.device.descriptors.device)

    def test_enumeration_and_rndis_then_transparent_forward(self):
        link = Link()
        types = [typ for typ, _ident, _payload in link.boot]
        self.assertIn(DEVICE_CONNECT, types)
        self.assertIn(INTERFACE_INFO, types)
        self.assertIn(EP_INFO, types)
        connect = next(payload for typ, _i, payload in link.boot if typ == DEVICE_CONNECT)
        _speed, _cls, _sub, _proto, vid, pid, _bcd = struct.unpack("<BBBBHHH", connect)
        self.assertEqual((vid, pid), (0x12D1, 0x14DB))
        ep = next(payload for typ, _i, payload in link.boot if typ == EP_INFO)
        self.assertEqual(len(ep), 160)  # max_packet_size negotiated, streams not advertised
        self.session_configure(link)

        status, body = self._rndis(link, _rndis(MSG_INIT, 1))
        self.assertEqual(status, ST_SUCCESS)
        self.assertEqual(struct.unpack_from("<I", body)[0], MSG_INIT_C)

        status, body = self._rndis(link, _rndis(MSG_QUERY, 2, OID_802_3_PERMANENT_ADDRESS, b"\x00" * 6))
        self.assertEqual(status, ST_SUCCESS)
        self.assertEqual(struct.unpack_from("<I", body)[0], MSG_QUERY_C)
        self.assertEqual(body[24:30], MAC)

        status, body = self._rndis(link, _rndis(MSG_QUERY, 3, OID_GEN_PHYSICAL_MEDIUM))
        self.assertEqual(struct.unpack_from("<I", body, 24)[0], 8)

        status, body = self._rndis(link, _rndis(MSG_QUERY, 4, OID_GEN_LINK_SPEED))
        self.assertEqual(struct.unpack_from("<I", body, 24)[0], 1_500_000)

        self._rndis(link, _rndis(MSG_SET, 5, 0x0001010E, struct.pack("<I", 0x0F)))
        frame = bytes.fromhex("ffffffffffff0212d114db020800") + bytes.fromhex("63825363") + b"not-a-dhcp-server"
        link.bulk(20, 0x02, wrap_ethernet(frame))
        self.assertEqual(link.uplink.tx, [frame])
        self.assertEqual(len(link.device.rx_pkts), 0)

        reply = bytes.fromhex("0212d114db02aabbccddeeff0800") + b"upstream"
        link.session.deliver_rx(reply)
        packets = link.bulk_in(21, 0x82, 2048)
        bulk = next(payload for typ, _i, payload in packets if typ == BULK)
        _ep, status, data = _parse_bulk(bulk)
        self.assertEqual(status, ST_SUCCESS)
        self.assertTrue(data.endswith(reply))
        self.assertEqual(struct.unpack_from("<I", data)[0], 1)

    def test_pending_in_completes_when_uplink_frame_arrives(self):
        link = Link()
        self.session_configure(link)
        self._bring_up(link)
        ident = 40
        low, high = 2048 & 0xFFFF, 0
        header = struct.pack("<BBHIH", 0x82, 0, low, 0, high)
        link.session.receive(link.guest.pack(BULK, ident, header))
        self.assertEqual(link.pump(), [])
        frame = bytes.fromhex("0212d114db02aabbccddeeff0800") + b"late"
        link.session.deliver_rx(frame)
        packets = link.pump()
        self.assertEqual(packets[0][0], BULK)
        self.assertEqual(packets[0][1], ident)

    def test_filter_blocks_forwarding_and_gate_blocks_radio_down(self):
        link = Link()
        self.session_configure(link)
        frame = bytes.fromhex("ffffffffffff0212d114db020800") + b"early"
        link.bulk(20, 0x02, wrap_ethernet(frame))
        self.assertEqual(link.uplink.tx, [])
        self._bring_up(link)
        link.device.update_lte({"registration_status": "searching"})
        gated = Link(gate=True)
        self.session_configure(gated)
        self._bring_up(gated)
        gated.device.update_lte({"registration_status": "searching"})
        status, body = self._rndis(gated, _rndis(MSG_QUERY, 9, OID_GEN_MEDIA_CONNECT_STATUS))
        self.assertEqual(status, ST_SUCCESS)
        self.assertEqual(struct.unpack_from("<I", body, 24)[0], 1)
        gated.bulk(21, 0x02, wrap_ethernet(frame))
        self.assertEqual(gated.uplink.tx, [])

    def test_at_port_serves_management_state(self):
        link = Link(profile="at")
        self.session_configure(link)
        link.device.update_lte({"rssi": -75, "registration_status": "registered"})
        packets = link.bulk(30, 0x04, b"AT+CSQ\r")
        self.assertTrue(any(typ == BULK for typ, _i, _p in packets))
        inn = link.bulk_in(31, 0x84, 512)
        bulk = next(payload for typ, _i, payload in inn if typ == BULK)
        _ep, _status, data = _parse_bulk(bulk)
        self.assertIn(b"+CSQ: 19,99", data)
        self.assertIn(b"OK", data)
        link.device.update_lte({"registration_status": "searching"})
        link.bulk(32, 0x04, b"ATE0\r")
        link.bulk_in(33, 0x84, 512)
        link.bulk(34, 0x04, b"AT+CEREG?\r")
        inn = link.bulk_in(35, 0x84, 512)
        bulk = next(payload for typ, _i, payload in inn if typ == BULK)
        _ep, _status, data = _parse_bulk(bulk)
        self.assertIn(b"+CEREG: 0,2", data)

    def session_configure(self, link: Link) -> None:
        link.session.receive(link.guest.pack(SET_CONFIGURATION, 7, bytes((1,))))
        packets = link.pump()
        self.assertEqual(packets[0][0], 8)  # configuration status
        self.assertEqual(link.device.configuration, 1)

    def _bring_up(self, link: Link) -> None:
        self._rndis(link, _rndis(MSG_INIT, 1))
        self._rndis(link, _rndis(MSG_SET, 5, 0x0001010E, struct.pack("<I", 0x0F)))

    def _rndis(self, link: Link, message: bytes):
        replies = link.control(10, 0x21, 0x00, 0, 0, message)
        self.assertEqual(_control_data(replies[0])[0], ST_SUCCESS)
        fetched = link.control(11, 0xA1, 0x01, 0, 0, wlen=4096)
        return _control_data(fetched[0])


def _parse_bulk(payload: bytes):
    endpoint, status, low, _stream, high = struct.unpack_from("<BBHIH", payload)
    return endpoint, status, payload[10 : 10 + (low | (high << 16))]


class StateAndProbeTests(unittest.TestCase):
    def test_csq_and_http_and_rejected_field(self):
        self.assertEqual(csq_from_rssi(-75), 19)
        state = LteState()
        device = UsbDevice(UsbIdentity(), MAC, state, MemoryUplink().send, "none", False)
        server = ControlServer(device, "127.0.0.1", 0)
        thread_started = __import__("threading").Thread(target=server.serve_forever, daemon=True)
        thread_started.start()
        try:
            port = server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/lte",
                data=json.dumps({"rssi": -89, "operator": "LAB"}).encode(),
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                body = json.load(response)
            self.assertEqual(body["rssi"], -89)
            self.assertEqual(body["operator"], "LAB")
            self.assertEqual(body["usb"]["vid"], "12d1")
            self.assertNotIn("dhcp", json.dumps(body).lower())
        finally:
            server.shutdown()
            server.server_close()
            thread_started.join(timeout=2)
        at = AtPort(state.get)
        text = at.feed(b"AT+CSQ\r")[0]
        self.assertIn(b"+CSQ: 12,99", text)

    def test_this_kernel_cannot_host_a_gadget(self):
        evidence = {"config_usb_support": False, "udc": [], "modprobe_attempted": False}
        decision = decide(evidence)
        self.assertIs(evidence["config_usb_support"], False)
        self.assertEqual(evidence["udc"], [])
        self.assertFalse(evidence["modprobe_attempted"])
        self.assertEqual(decision["path"], "usbredir-userspace")
        self.assertIn("configfs-dummy-hcd", decision["rejected"])
        self.assertIn("usb-host", decision["rejected"])
        self.assertIn("usbip", decision["rejected"])

    def test_missing_uplink_is_refused(self):
        from lte_rndis_emu.uplink import UplinkError

        with self.assertRaises(UplinkError):
            PacketUplink("no-such-ifc")

    @unittest.skipUnless(os.environ.get("LTE_EMU_TAP_TEST") == "1", "explicit privileged TAP integration test")
    def test_packet_uplink_forwards_to_a_tap(self):
        import fcntl
        import select
        import socket

        try:
            tun = os.open("/dev/net/tun", os.O_RDWR)
        except PermissionError:
            self.skipTest("TUN is not permitted here; run this on the lab host")
            return
        try:
            try:
                created = fcntl.ioctl(tun, 0x400454CA, struct.pack("16sH", b"lteemu0", 0x0002 | 0x1000))
            except PermissionError:
                self.skipTest("creating a tap is not permitted here")
                return
            ifname = created[:16].split(b"\x00", 1)[0].decode()
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            current = fcntl.ioctl(sock, 0x8913, struct.pack("16sH", ifname.encode(), 0) + b"\x00" * 14)
            flags = struct.unpack_from("H", current, 16)[0] | 0x1
            fcntl.ioctl(sock, 0x8914, struct.pack("16sH", ifname.encode(), flags) + b"\x00" * 14)
            uplink = PacketUplink(ifname)
            frame = bytes.fromhex("ffffffffffff0200000000010800") + b"out"
            uplink.send(frame)
            self.assertEqual(os.read(tun, 65535), frame)
            back = bytes.fromhex("020000000001ffffffffffff0800") + b"in"
            os.write(tun, back)
            readable, _, _ = select.select([uplink.fileno()], [], [], 1)
            self.assertTrue(readable)
            self.assertEqual(uplink.drain(), [back])
            uplink.close()
        finally:
            os.close(tun)


class ScriptTests(unittest.TestCase):
    def test_gadget_script_refuses_this_kernel(self):
        import subprocess

        script = Path(__file__).resolve().parents[1] / "scripts" / "gadget-configfs.sh"
        if decide(collect())["path"] == "configfs-dummy-hcd":
            self.skipTest("do not configure host gadget from unit tests")
        result = subprocess.run(["sh", str(script)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no modules loaded", result.stderr + result.stdout)


if __name__ == "__main__":
    unittest.main()
