import socket
import threading
import unittest
from sdwan.native_api import NativeAPI,encode_length


class BufferSocket:
    def __init__(self,data):self.data=data
    def recv(self,n):
        chunk=self.data[:min(n,2)];self.data=self.data[len(chunk):];return chunk


def sentence(words):
    return b''.join(encode_length(len(w.encode()))+w.encode() for w in words)+b'\x00'


class NativeAPITests(unittest.TestCase):
    def test_length_boundaries(self):
        for n in (0,1,127,128,16383,16384,2097151,2097152,268435455,268435456):
            encoded=encode_length(n)
            if n<128:decoded=encoded[0]
            elif n<16384:decoded=int.from_bytes(encoded,'big')&0x3fff
            elif n<2097152:decoded=int.from_bytes(encoded,'big')&0x1fffff
            elif n<268435456:decoded=int.from_bytes(encoded,'big')&0xfffffff
            else:decoded=int.from_bytes(encoded[1:],'big')
            self.assertEqual(decoded,n)
    def test_utf8_word_and_fragmented_receive(self):
        text='интерфейс провайдера';b=text.encode();c=NativeAPI('none',1,'u','p');c.sock=BufferSocket(encode_length(len(b))+b)
        self.assertEqual(c._word(),text)
    def test_truncated_word_errors(self):
        c=NativeAPI('none',1,'u','p');c.sock=BufferSocket(b'\x05ab')
        with self.assertRaises(ConnectionError):c._word()
    def test_reserved_control_byte_rejected(self):
        c=NativeAPI('none',1,'u','p');c.sock=BufferSocket(b'\xf8')
        with self.assertRaises(RuntimeError):c._word()
    def test_live_login_query_and_trap(self):
        server=socket.socket();server.bind(('127.0.0.1',0));server.listen(1);port=server.getsockname()[1];errors=[]
        def serve():
            try:
                conn,_=server.accept();reader=NativeAPI('none',1,'','');reader.sock=conn
                def receive():
                    out=[]
                    while True:
                        x=reader._word()
                        if not x:return out
                        out.append(x)
                self.assertEqual(receive(),['/login','=name=user','=password=unit-pass'])
                conn.sendall(sentence(['!done']))
                self.assertEqual(receive(),['/interface/print','=.proplist=name','?type=ether'])
                conn.sendall(sentence(['!re','=name=ether1'])+sentence(['!re','=name=ether2'])+sentence(['!done']))
                self.assertEqual(receive(),['/invalid'])
                conn.sendall(sentence(['!trap','=message=no such command'])+sentence(['!done']))
                conn.close()
            except BaseException as e:errors.append(e)
            finally:server.close()
        thread=threading.Thread(target=serve);thread.start();client=NativeAPI('127.0.0.1',port,'user','unit-pass')
        try:
            rows,_=client.command('/interface/print',{'.proplist':'name'},['type=ether'])
            self.assertEqual(rows,[{'name':'ether1'},{'name':'ether2'}])
            with self.assertRaisesRegex(RuntimeError,'no such command'):client.command('/invalid')
        finally:client.close();thread.join(timeout=3)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

if __name__=='__main__':unittest.main()
