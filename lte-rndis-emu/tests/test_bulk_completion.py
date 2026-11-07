"""Regress actual-length USB bulk OUT completions (usbredir protocol section 101)."""
import struct
import unittest
from unittest.mock import Mock
from test_emu import Link
from lte_rndis_emu.usbredir import BULK, CAP_32BIT_BULK, ProtocolError, bulk_header

class BulkCompletionTests(unittest.TestCase):
    def test_out_completion_reports_actual_length_without_echo(self):
        for size in (0, 154, 65536):
            with self.subTest(size=size):
                link = Link()
                link.device.push_out = Mock()
                data = b"x" * size
                replies = link.bulk(501, 0x02, data)
                link.device.push_out.assert_called_once_with(0x02, data)
                self.assertEqual(len(replies), 1)
                typ, ident, header = replies[0]
                self.assertEqual((typ, ident), (BULK, 501))
                self.assertEqual(len(header), 10)
                ep, status, low, stream, high = struct.unpack("<BBHIH", header)
                self.assertEqual((ep, status, stream, low | (high << 16)), (0x02, 0, 0, size))

    def test_legacy_out_completion_uses_eight_byte_header(self):
        self.assertEqual(bulk_header(2, 0, b"", 0, transferred=154), struct.pack("<BBHI", 2, 0, 154, 0))
        with self.assertRaises(ProtocolError):
            bulk_header(2, 0, b"", 0, transferred=65536)

    def test_invalid_completion_length_is_rejected(self):
        for size in (-1, 1 << 32):
            with self.subTest(size=size), self.assertRaises(ProtocolError):
                bulk_header(2, 0, b"", CAP_32BIT_BULK, transferred=size)
