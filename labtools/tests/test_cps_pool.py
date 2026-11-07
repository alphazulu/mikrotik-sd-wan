import json,os,signal,shutil,socket,subprocess,tempfile,threading,time,unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from sdwan_lab.cps_pool import PoolSpec,reserve,validate_result


class PoolBudgetTests(unittest.TestCase):
    def test_long_NAT_case_requires_destination_pool_even_with_many_sources(self):
        sources=tuple('192.0.2.'+str(i) for i in range(1,129))
        spec=PoolSpec(sources).validate();self.assertEqual(spec.attempts,180000)
        with self.assertRaisesRegex(ValueError,'destination'):replace(spec,destination_port_count=1).validate()
        self.assertEqual(len(spec.client_argv('worker','198.18.79.1')),13)

    def test_invalid_or_exhausted_pools_rejected(self):
        spec=PoolSpec(('192.0.2.1','192.0.2.2'),rate=100,warmup=0,seconds=1,destination_port_count=1)
        for changes in [{'sources':('192.0.2.1','192.0.2.1')},{'sources':('224.0.0.1',)},
                        {'rate':True},{'tuple_offset':1000000},{'destination_port_base':65535,'destination_port_count':2},
                        {'sources':()},{'concurrency':257},{'source_port_low':20}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):replace(spec,**changes).validate()

    def test_crash_reservations_are_not_reused(self):
        with tempfile.TemporaryDirectory() as root:
            run=SimpleNamespace(folder=Path(root));sources=tuple('192.0.2.'+str(i) for i in range(1,129))
            one=reserve(run,sources);two=reserve(run,sources)
            self.assertEqual(two.tuple_offset,one.attempts)
            self.assertEqual(two.destination_port_base,one.destination_port_base+one.destination_port_count)
            with self.assertRaisesRegex(ValueError,'changed'):reserve(run,sources[:-1])
            self.assertEqual(len(json.loads((Path(root)/'cps-pool-reservations.json').read_text())['reservations']),2)


@unittest.skipUnless(shutil.which('cc') and os.name=='posix','POSIX C compiler required')
class RealPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.binary=Path(cls.temp.name)/'cps'
        source=Path(__file__).resolve().parents[1]/'sdwan_lab/cps_pool.c'
        subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',source,'-o',cls.binary],check=True,capture_output=True,text=True)

    def test_two_source_multidestination_roundtrip_and_peer_counts(self):
        with socket.socket() as reservation:
            reservation.bind(('127.105.0.1',0));port=reservation.getsockname()[1]
        if port>65534:self.skipTest('Need two consecutive test ports')
        spec=PoolSpec(('127.105.0.2','127.105.0.3'),rate=150,warmup=1,seconds=2,concurrency=8,destination_port_base=port,destination_port_count=2)
        server=subprocess.Popen(spec.server_argv(self.binary,'127.105.0.1'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertTrue(server.stdout.readline().startswith('ready'))
            client=subprocess.run(spec.client_argv(self.binary,'127.105.0.1'),check=True,capture_output=True,text=True,timeout=8)
            data=json.loads(client.stdout);server.send_signal(signal.SIGINT);stdout,stderr=server.communicate(timeout=4)
            self.assertEqual(server.returncode,0,stderr);peer=json.loads(stdout.strip())
            self.assertTrue(validate_result(data,peer,spec)['pass']);self.assertGreaterEqual(sum(data['completion_counts_per_second']),440)
            for bad in [dict(peer,completed=449),dict(peer,errors=1),dict(peer,active=1)]:
                with self.assertRaises(ValueError):validate_result(data,bad,spec)
        finally:
            if server.poll() is None:server.kill();server.communicate()
            server.stdout.close();server.stderr.close()

    def test_server_sees_unique_explicit_client_tuples_and_client_active_close(self):
        peers=[];errors=[]
        with socket.socket() as listener:
            listener.bind(('127.106.0.1',0));listener.listen(32);listener.settimeout(5);port=listener.getsockname()[1]
            def receive():
                try:
                    for _ in range(60):
                        peer,address=listener.accept()
                        with peer:
                            peer.settimeout(2);body=b''
                            while len(body)<32:
                                part=peer.recv(32-len(body))
                                if not part:raise AssertionError('Early client EOF')
                                body+=part
                            peer.sendall(body)
                            if peer.recv(1)!=b'':raise AssertionError('Client did not actively close')
                            peers.append(address)
                except BaseException as e:errors.append(str(e))
            worker=threading.Thread(target=receive);worker.start()
            spec=PoolSpec(('127.106.0.2','127.106.0.3'),rate=60,warmup=0,seconds=1,source_port_low=13000,source_port_high=14000,tuple_offset=20,destination_port_base=port,destination_port_count=1)
            data=json.loads(subprocess.run(spec.client_argv(self.binary,'127.106.0.1'),check=True,capture_output=True,text=True,timeout=5).stdout)
            worker.join(timeout=6);self.assertFalse(worker.is_alive());self.assertFalse(errors)
            self.assertEqual(len(set(peers)),60);self.assertEqual({p[0] for p in peers},set(spec.sources))
            self.assertEqual(min(p[1] for p in peers),13010);self.assertEqual(max(p[1] for p in peers),13039);self.assertEqual(data['echo_success'],60)

    def test_program_rejects_insufficient_budget_before_connecting(self):
        spec=PoolSpec(('127.107.0.2',),rate=50,warmup=0,seconds=1,source_port_low=13000,source_port_high=14000,destination_port_base=40000,destination_port_count=1)
        argv=spec.client_argv(self.binary,'127.107.0.1');argv[11]='13001'
        result=subprocess.run(argv,capture_output=True,text=True,timeout=2)
        self.assertEqual(result.returncode,2);self.assertIn('budget exceeded',result.stderr);self.assertEqual(result.stdout,'')
