import hashlib
from unittest.mock import Mock
import unittest
from sdwan.router import Router

class BinaryFiles(unittest.TestCase):
    def router(self,data):
        router=Router.__new__(Router);router.native=Mock();router.file_entry=lambda name:{'.id':'*1','name':name}
        router.call=Mock(return_value={'ret':str(len(data))})
        router.native.command.side_effect=lambda command,attrs,binary:([{'data':data[int(attrs['offset']):int(attrs['offset'])+int(attrs['chunk-size'])]}],{})
        return router
    def test_stream_hash_preserves_all_byte_values_and_reads_only(self):
        data=bytes(range(256))*200;router=self.router(data)
        self.assertEqual(router.file_digest('archive.tar.gz'),hashlib.sha256(data).hexdigest())
        self.assertEqual(router.native.command.call_count,2)
        self.assertTrue(all(c.kwargs['binary'] for c in router.native.command.call_args_list))
        self.assertTrue(all(c.args[0]=='/file/read' for c in router.native.command.call_args_list))
    def test_bounds_and_truncation_never_pass_integrity_check(self):
        router=self.router(b'abc')
        with self.assertRaises(ValueError):list(router.binary_chunks('x',max_bytes=2))
        router.native.command.return_value=([{'data':b'ab'}],{});router.native.command.side_effect=None
        with self.assertRaisesRegex(RuntimeError,'truncated'):router.file_digest('x')
        for limit in (0,True,129*1024*1024):
            with self.assertRaises(ValueError):list(router.binary_chunks('x',max_bytes=limit))
    def test_native_api_required_and_empty_file_hash_is_exact(self):
        router=self.router(b'');self.assertEqual(router.file_digest('x'),hashlib.sha256(b'').hexdigest())
        router.native=None
        with self.assertRaisesRegex(ValueError,'native API'):router.file_digest('x')
