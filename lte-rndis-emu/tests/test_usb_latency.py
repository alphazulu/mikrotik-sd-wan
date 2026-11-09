"""Observe transport options on a real accepted USB connection, after its HELLO."""
import contextlib,io,shlex,socket,subprocess,threading,types,unittest
from unittest.mock import patch
from lte_rndis_emu import emulator

class UsbTransportLatencyTests(unittest.TestCase):
    def test_live_usb_connection_is_nonblocking_and_disables_nagle(self):
        listening=threading.Event();stop=threading.Event();accepted=[];addresses=[];errors=[];results=[]
        original_accept=socket.socket.accept;original_listen=socket.socket.listen;original_select=emulator.select.select
        def listen(channel,*args,**kwargs):
            result=original_listen(channel,*args,**kwargs)
            addresses.append(channel.getsockname());listening.set();return result
        def accept(channel,*args,**kwargs):
            result=original_accept(channel,*args,**kwargs);accepted.append(result[0]);return result
        def select(read,write,error,timeout=None):
            if threading.current_thread() is worker and stop.is_set():raise KeyboardInterrupt
            return original_select(read,write,error,min(timeout or .1,.1))
        def serve():
            try:results.append(emulator.main(['serve','--uplink','none','--listen','127.0.0.1:0','--control','none']))
            except BaseException as e:errors.append(e);listening.set()
        worker=threading.Thread(target=serve,name='usb-transport-test')
        with patch.object(socket.socket,'listen',listen),patch.object(socket.socket,'accept',accept),patch.object(emulator.select,'select',select),patch.object(emulator,'qemu_args',return_value=[]),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            worker.start()
            try:
                self.assertTrue(listening.wait(3),'USB listener did not start');self.assertFalse(errors)
                with socket.create_connection(addresses[0],timeout=2) as client:
                    self.assertTrue(client.recv(4096),'No actual usbredir HELLO')
                    self.assertEqual(len(accepted),1)
                    self.assertFalse(accepted[0].getblocking())
                    self.assertEqual(accepted[0].getsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY),1,'USB responses must not wait for Nagle/delayed ACK')
            finally:stop.set();worker.join(3)
        self.assertFalse(worker.is_alive());self.assertFalse(errors);self.assertEqual(results,[0]);self.assertEqual(accepted[0].fileno(),-1)

class QemuTransportContractTests(unittest.TestCase):
    def test_cli_requests_low_latency_and_preserves_reconnect_capabilities(self):
        for help_text, reconnect in [('nodelay reconnect-ms', 'reconnect-ms=2000'),
                                     ('nodelay reconnect=', 'reconnect=2'),
                                     ('nodelay', None)]:
            with self.subTest(help=help_text),patch.object(emulator,'_qemu_bin',return_value='/test/qemu'),patch.object(emulator.subprocess,'run',return_value=types.SimpleNamespace(stdout=help_text,stderr='')):
                output=io.StringIO()
                with contextlib.redirect_stdout(output):self.assertEqual(emulator.main(['qemu-args','--port','35280']),0)
                args=shlex.split(output.getvalue());channel=args[args.index('-chardev')+1].split(',')
                self.assertIn('host=127.0.0.1',channel);self.assertIn('port=35280',channel);self.assertEqual(channel.count('nodelay=on'),1)
                if reconnect:self.assertIn(reconnect,channel)
                else:self.assertFalse(any(s.startswith('reconnect') for s in channel))
    def test_offline_and_failed_help_keep_low_latency_request(self):
        with patch.object(emulator,'_qemu_bin',return_value=None):self.assertIn('nodelay=on',emulator.qemu_chardev(35280))
        for error in (OSError('fixture'),subprocess.TimeoutExpired('qemu',5)):
            with self.subTest(error=type(error).__name__),patch.object(emulator,'_qemu_bin',return_value='/test/qemu'),patch.object(emulator.subprocess,'run',side_effect=error):self.assertIn('nodelay=on',emulator.qemu_chardev(35280))

if __name__=='__main__':unittest.main()
