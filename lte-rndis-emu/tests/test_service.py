"""Exercise actual CLI sockets and cleanup without privileged host networking."""
import http.client
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import unittest

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.errors = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [sys.executable, '-m', 'lte_rndis_emu', 'serve', '--uplink',
             'socket:127.0.0.1:0', '--listen', '127.0.0.1:0', '--control', '127.0.0.1:0'],
            cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=self.errors)
        self.addCleanup(self.stop)
        self.assertTrue(select.select([self.process.stdout], [], [], 10)[0], 'missing ready')
        line = self.process.stdout.readline().decode()
        self.assertTrue(line.startswith('ready '), line)
        self.ports = [int(x) for x in re.findall(r'127\.0\.0\.1:(\d+)', line)]
        self.assertEqual(len(self.ports), 3)

    def stop(self):
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait()
        self.process.stdout.close(); self.errors.close()

    def test_rootless_peer_before_usb_and_protocol_reconnect(self):
        # A real Ethernet backend may connect first; no USB session is required
        # for accepting/draining it, and malformed USB only drops that client.
        with socket.create_connection(('127.0.0.1', self.ports[2]), timeout=2) as peer:
            peer.sendall(struct.pack('!I', 14) + b'x' * 14)
            with socket.create_connection(('127.0.0.1', self.ports[0]), timeout=2) as usb:
                self.assertTrue(usb.recv(4096))  # hello
                usb.sendall(struct.pack('<III', 100, (1 << 20) + 1, 0))
                self.assertEqual(usb.recv(4096), b'')
            with socket.create_connection(('127.0.0.1', self.ports[0]), timeout=2) as usb:
                self.assertTrue(usb.recv(4096))
        c = http.client.HTTPConnection('127.0.0.1', self.ports[1], timeout=2)
        try:
            c.request('GET', '/lte')
            r = c.getresponse(); self.assertEqual(r.status, 200)
            self.assertFalse(json.loads(r.read())['usb']['rndis_initialized'])
        finally:
            c.close()
        self.process.send_signal(signal.SIGINT)
        self.assertEqual(self.process.wait(timeout=5), 0)
        for port in self.ports:
            with socket.socket() as listener:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                listener.bind(('127.0.0.1', port))

    def test_bad_http_lengths_and_unicode_are_client_errors(self):
        for headers, body in [({'Content-Length':'-1'}, b''),
                              ({'Content-Length':'garbage'}, b''),
                              ({'Content-Length':'65537'}, b''),
                              ({'Content-Length':'1'}, b'\xff')]:
            c = http.client.HTTPConnection('127.0.0.1', self.ports[1], timeout=2)
            try:
                c.request('POST', '/lte', body=body, headers=headers)
                r = c.getresponse(); self.assertIn(r.status, (400, 413)); r.read()
            finally:
                c.close()
