"""Real unprivileged TCP Ethernet transport, independent of host kernel."""
import select
import socket
import struct
import unittest
from lte_rndis_emu.uplink import SocketUplink, UplinkError, open_uplink

FRAME = bytes.fromhex('ffffffffffff0200000000010800') + b'test'

class SocketTests(unittest.TestCase):
    def setUp(self):
        self.uplink = SocketUplink('127.0.0.1:0')
        self.addCleanup(self.uplink.close)
        self.port = self.uplink.server.getsockname()[1]

    def connect(self):
        peer = socket.create_connection(('127.0.0.1', self.port), timeout=1)
        self.addCleanup(peer.close)
        self.uplink.drain()
        return peer

    def drain(self):
        select.select(self.uplink.filenos(), [], [], 1)
        return self.uplink.drain()

    def test_fragmented_header_body_multiple_frames_both_directions(self):
        peer = self.connect()
        blob = struct.pack('!I', len(FRAME)) + FRAME
        peer.sendall(blob[:2]); self.assertEqual(self.drain(), [])
        peer.sendall(blob[2:7]); self.assertEqual(self.drain(), [])
        peer.sendall(blob[7:] + blob); self.assertEqual(self.drain(), [FRAME, FRAME])
        self.uplink.send(FRAME)
        self.assertEqual(peer.recv(65536), blob)
        self.assertEqual(self.uplink.counters['rx_frames'], 2)
        self.assertEqual(self.uplink.counters['tx_frames'], 1)

    def test_no_peer_is_error_and_no_pending_transmission(self):
        with self.assertRaises(OSError):
            self.uplink.send(FRAME)
        self.assertEqual(self.uplink.tx, b'')
        self.assertEqual(self.uplink.writable(), [])

    def test_invalid_length_disconnect_and_reconnect_clear_buffers(self):
        for length in (0, 13, 65536, 0xffffffff):
            peer = self.connect(); peer.sendall(struct.pack('!I', length))
            self.assertEqual(self.drain(), [])
            self.assertIsNone(self.uplink.peer)
            self.assertEqual(peer.recv(1), b'')
        peer = self.connect()
        peer.sendall(struct.pack('!I', len(FRAME)) + FRAME)
        self.assertEqual(self.drain(), [FRAME])
        self.assertEqual(self.uplink.counters['invalid'], 4)

    def test_second_peer_rejected_and_eof_resets(self):
        first = self.connect(); second = self.connect()
        self.assertEqual(second.recv(1), b'')
        first.sendall(b'\x00\x00'); self.assertEqual(self.drain(), [])
        first.close(); self.drain()
        self.assertIsNone(self.uplink.peer)
        self.assertFalse(self.uplink.rx)
        self.connect()
        with self.assertRaises(OSError):
            self.uplink.send(b'bad')
        self.uplink.tx.extend(b'x' * self.uplink.MAX_QUEUE)
        with self.assertRaises(BlockingIOError):
            self.uplink.send(FRAME)

    def test_only_loopback_and_factory(self):
        for value in ('0.0.0.0:24322', '192.0.2.1:24322', 'localhost:1', 'bad', '127.0.0.1:bad'):
            with self.subTest(value=value), self.assertRaises(UplinkError):
                SocketUplink(value)
        with self.assertRaises(UplinkError):
            SocketUplink('127.0.0.1:' + str(self.port))
        other = open_uplink('socket:127.0.0.1:0'); other.close()

if __name__ == '__main__':
    unittest.main()
