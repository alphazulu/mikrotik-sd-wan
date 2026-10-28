import copy
import hashlib
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from sdwan_lab.config import validate
from sdwan_lab.runtime import Lease, Run, atomic_json, check_ports
from sdwan_lab.bench import pcap_metrics
from sdwan_lab.usb_repro import frame, redact_cli


class ConfigTests(unittest.TestCase):
    def setUp(self): self.cfg = {'schema_version':1,'workloads':[{'kind':'tcp'}]}
    def test_defaults_and_all_workload_types(self):
        for kind in ('tcp','udp','imix','cps'):
            self.cfg['workloads']=[{'kind':kind}]
            self.assertEqual(validate(self.cfg)['workloads'][0]['kind'],kind)
    def test_unknown_fields_and_nonfinite_limits_rejected(self):
        for update in ({'typo':1},{'seconds':True},{'seconds':61},{'subnet':'192.168.0.0/30'},
                       {'schema_version':True},{'workloads':[{'kind':'tcp','rate':1}]},
                       {'criteria':{'cpu_p95_max':float('nan')}},{'workloads':[]},
                       {'workloads':[{'kind':'udp','direction':'bidir'}]},
                       {'workloads':[{'kind':'cps','rate':20000}]},
                       {'workloads':[{'kind':'imix','frame_sizes_with_fcs':[63]}]}):
            with self.subTest(update=update), self.assertRaises((ValueError,TypeError)):
                validate(dict(self.cfg,**update))
    def test_rate_minimum_and_cps_budget(self):
        for w in ({'kind':'tcp','offered_bps':1,'minimum_bps':2},
                  {'kind':'udp','offered_pps':1,'minimum_pps':2},
                  {'kind':'cps','rate':100,'minimum_cps':200}):
            with self.assertRaises(ValueError):validate(dict(self.cfg,workloads=[w]))


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.lock=self.root/'host.lock'
    def lease(self, name='workspace'):return Lease(self.root/name,self.lock)
    def test_host_lock_also_excludes_other_workspaces(self):
        with self.lease():
            with self.assertRaises(RuntimeError):self.lease('other')
        with self.lease('other'):pass
    def test_results_never_overwrite_and_stale_journal_requires_recovery(self):
        with self.lease() as lease:
            first=Run(lease,'one',{})
            with self.assertRaises(RuntimeError):Run(lease,'two',{})
            self.assertTrue(first.cleanup())
            with self.assertRaises(FileExistsError):Run(lease,'one',{})
    def test_missing_executable_does_not_leave_unknown_process(self):
        with self.lease() as lease:
            run=Run(lease,'badexec',{})
            with self.assertRaises(FileNotFoundError):run.spawn(['/no/such/executable'],'child')
            self.assertTrue(run.cleanup())
    def test_owned_child_group_is_stopped(self):
        with self.lease() as lease:
            run=Run(lease,'child',{});child=run.spawn([sys.executable,'-c','import time;time.sleep(30)'],'sleep')
            self.assertTrue(run.cleanup());self.assertIsNotNone(child.poll())
    def test_pid_reuse_is_refused(self):
        with self.lease() as lease:
            run=Run(lease,'reuse',{});run.data['resources']=[{'kind':'process','pid':123,'start':'original','deleted':False}]
            with patch('sdwan_lab.runtime.process_start',return_value='different'),patch('sdwan_lab.runtime.os.killpg') as kill:
                self.assertFalse(run.cleanup());kill.assert_not_called()
    def test_pending_uncertain_creation_cannot_be_claimed_clean(self):
        with self.lease() as lease:
            run=Run(lease,'pending',{});run._intent('namespace','uncertain')
            self.assertFalse(run.cleanup())
    def test_duplicate_log_label_cannot_overwrite_raw_evidence(self):
        with self.lease() as lease:
            run=Run(lease,'duplicate',{});child=run.spawn([sys.executable,'-c','pass'],'once');child.wait(timeout=5)
            with self.assertRaises(FileExistsError):run.spawn([sys.executable,'-c','pass'],'once')
            self.assertTrue(run.cleanup())
    def test_rebooted_pid_is_never_signalled(self):
        with self.lease() as lease:
            run=Run(lease,'reboot',{});run.data['resources']=[{'kind':'process','pid':123,'start':'same','boot_id':'prior-boot','deleted':False}]
            with patch('sdwan_lab.runtime.os.killpg') as kill:
                self.assertTrue(run.cleanup());kill.assert_not_called()
    def test_foreign_namespace_is_not_deleted(self):
        from types import SimpleNamespace
        with self.lease() as lease:
            run=Run(lease,'foreign-ns',{});run.data['resources']=[{'kind':'namespace','name':'foreign','inode':1,'device':2,'deleted':False}]
            with patch('sdwan_lab.runtime.Path.exists',return_value=True),patch('sdwan_lab.runtime.Path.stat',return_value=SimpleNamespace(st_ino=9,st_dev=9)),patch('sdwan_lab.runtime.checked') as call:
                self.assertFalse(run.cleanup());call.assert_not_called()
    def test_recovery_preserves_original_report(self):
        with self.lease() as lease:
            run=Run(lease,'recover',{});atomic_json(run.folder/'report.json',{'status':'failed','pass':False})
        with self.lease() as lease:
            run=Run(lease,'recover',recover=True);self.assertTrue(run.cleanup())
            self.assertFalse(json.loads((run.folder/'report.json').read_text())['pass'])
    def test_foreign_workspace_owner_is_refused(self):
        with self.lease() as lease:
            run=Run(lease,'foreign',{});atomic_json(run.owner,dict(run.data,token='foreign'))
            with self.assertRaises(RuntimeError):Run(lease,'foreign',recover=True)
    def test_run_id_cannot_escape_workspace(self):
        with self.lease() as lease:
            for name in ('../oops','/tmp','a/b',''):
                with self.assertRaises(ValueError):Run(lease,name,{})


class PcapTests(unittest.TestCase):
    def test_guest_password_redaction_handles_wrapped_terminal_echo(self):
        self.assertEqual(redact_cli('password="sec\nret" secret', 'secret'), 'password="<redacted>" <redacted>')

    def test_repro_frames_have_actual_sizes_and_valid_ipv4_checksums(self):
        for size in (64,2598):
            blob=frame(size,42);self.assertEqual(len(blob),size)
            ip=blob[14:34];total=sum(struct.unpack('!10H',ip));total=(total&65535)+(total>>16)
            self.assertEqual(total,65535);self.assertEqual(int.from_bytes(ip[2:4],'big'),size-14)
    def test_measured_window_excludes_warmup_and_drain(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'input.pcap'
            with p.open('wb') as f:
                f.write(struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,65535,1))
                frame=bytes(12)+b'\x88\xb5'+bytes(46)
                for i in range(5):f.write(struct.pack('<IIII',i,0,len(frame),len(frame))+frame)
            r=pcap_metrics(p,1,2);self.assertEqual(r['capture_packets'],5);self.assertEqual(r['receiver_pps'],1)
            p.write_bytes(p.read_bytes()[:-3])
            with self.assertRaises(ValueError):pcap_metrics(p,1,2)
    def test_busy_port_is_not_reused(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));s.listen()
            with self.assertRaises(OSError):check_ports([s.getsockname()[1]])


if __name__=='__main__':unittest.main()
