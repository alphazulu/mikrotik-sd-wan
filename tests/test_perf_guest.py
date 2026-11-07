"""Check isolation and serial framing before commanding benchmark guests."""
import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import perf_guest as guest


class GuestTests(unittest.TestCase):
    def test_frame_is_token_bound_and_requires_completion(self):
        payload='ошибка\n__SDWAN_END_other__\n'
        data=b'boot\r\n__SDWAN_BEGIN_token__\r\n7\r\n'+base64.b64encode(payload.encode())+b'\r\n\r\n__SDWAN_END_token__\r\n# '
        self.assertEqual(guest.decode_frame(data,'token'),(7,payload))
        self.assertIsNone(guest.decode_frame(data,'other'))
        self.assertIsNone(guest.decode_frame(data[:-28],'token'))

    def test_rejects_corrupt_response(self):
        for content in (b'x\n',b'0\n***'):
            with self.assertRaises(ValueError):
                guest.decode_frame(b'__SDWAN_BEGIN_t__\n'+content+b'\n__SDWAN_END_t__','t')

    def test_unknown_guest_never_opens_socket(self):
        with patch.object(guest.socket,'create_connection') as connect:
            with self.assertRaises(ValueError):guest.command('production','true')
            connect.assert_not_called()

    def test_cpio_rejects_path_escape_and_preserves_alignment(self):
        for name in ('/init','a/../init','a\0b'):
            with self.assertRaises(ValueError):guest.cpio_file(name,b'body')
        item=guest.cpio_file('init',b'body')
        self.assertEqual(len(item)%4,0)
        self.assertEqual(item[:6],b'070701')
        self.assertIn(b'init\0',item)

    def test_iso_mismatch_does_not_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.iso';path.write_bytes(b'not the trusted ISO')
            with self.assertRaises(ValueError):guest.iso_boot_files(path,Path(tmp)/'out')
            self.assertFalse((Path(tmp)/'out').exists())

    def test_checked_preserves_failed_status(self):
        with patch.object(guest,'command',return_value=(13,'permission denied')):
            with self.assertRaisesRegex(RuntimeError,'13.*permission denied'):guest.checked('client','ip link')


if __name__=='__main__':unittest.main()
