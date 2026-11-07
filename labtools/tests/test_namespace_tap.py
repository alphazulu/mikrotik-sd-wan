import array,os,socket,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
from sdwan_lab.namespace_tap import receive_fd,open_tap,TAG
from sdwan_lab.runtime import Lease,Run

class DescriptorTests(unittest.TestCase):
 def test_received_descriptor_is_usable_and_not_inheritable(self):
  with tempfile.TemporaryFile() as original:
   original.write(b'owned-fd');original.seek(0)
   a,b=socket.socketpair()
   try:
    a.sendmsg([TAG],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[original.fileno()]))])
    descriptor=receive_fd(b,expected_pid=os.getpid(),expected_uid=os.geteuid())
    try:self.assertEqual(os.read(descriptor,8),b'owned-fd');self.assertFalse(os.get_inheritable(descriptor))
    finally:os.close(descriptor)
   finally:a.close();b.close()
 def test_extra_received_descriptors_are_closed_on_rejection(self):
  with tempfile.TemporaryFile() as original:
   a,b=socket.socketpair()
   try:
    before=len(os.listdir('/proc/self/fd'));a.sendmsg([TAG],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[original.fileno(),original.fileno()]))])
    with self.assertRaises(ValueError):receive_fd(b,expected_pid=os.getpid(),expected_uid=os.geteuid())
    self.assertEqual(len(os.listdir('/proc/self/fd')),before)
   finally:a.close();b.close()
 def test_wrong_peer_identity_is_rejected_before_receiving(self):
  a,b=socket.socketpair()
  try:
   with self.assertRaises(RuntimeError):receive_fd(b,expected_pid=os.getpid(),expected_uid=os.geteuid()+1)
  finally:a.close();b.close()
 def test_unknown_namespace_is_rejected_before_helper_spawn(self):
  run=Mock();run.data={'resources':[]}
  with self.assertRaises(ValueError):open_tap(run,'foreign','eth0')
  run.spawn.assert_not_called()
 def test_exported_descriptor_reaches_owned_child(self):
  with tempfile.TemporaryDirectory() as root,tempfile.TemporaryFile() as source:
   source.write(b'owned-fd');source.seek(0)
   with Lease(Path(root)/'workspace',Path(root)/'host.lock') as lease:
    run=Run(lease,'descriptor',{})
    try:
     child=run.spawn([sys.executable,'-c','import os,sys;print(os.read(int(sys.argv[1]),8).decode())',str(source.fileno())],'reader',pass_fds=(source.fileno(),))
     self.assertEqual(child.wait(timeout=5),0);self.assertEqual((run.folder/'reader.stdout').read_text().strip(),'owned-fd')
     with self.assertRaises(ValueError):run.spawn([sys.executable,'-c','pass'],'bad',pass_fds=(1,))
    finally:self.assertTrue(run.cleanup())
