"""Open TAPs inside owned network namespaces and export FDs to an owned QEMU.

The QEMU process may stay in the host namespace for loopback management while
its packet interfaces belong entirely to the disposable peer namespaces.
"""
import array
import os
from pathlib import Path
import re
import socket
import struct
import sys
import tempfile
from .runtime import boot_id

TAG=b'SDWAN_TAP_FD_V1'
HELPER=r'''
import array,fcntl,os,socket,struct,sys
fd=os.open('/dev/net/tun',os.O_RDWR|os.O_CLOEXEC)
try:
 fcntl.ioctl(fd,0x400454ca,struct.pack('16sH22x',sys.argv[1].encode(),0x0002|0x1000))
 with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as peer:
  peer.connect(bytes.fromhex(sys.argv[2]))
  peer.sendmsg([b'SDWAN_TAP_FD_V1'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))])
  if peer.recv(2)!=b'OK':raise RuntimeError('Descriptor export not acknowledged')
finally:os.close(fd)
'''

def receive_fd(peer,*,expected_pid,expected_uid):
    pid,uid,_=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))
    if (pid,uid)!=(expected_pid,expected_uid):raise RuntimeError('Descriptor peer identity mismatch')
    received=[]
    try:
        data,ancillary,flags,_=peer.recvmsg(256,socket.CMSG_SPACE(4*4),socket.MSG_CMSG_CLOEXEC)
        for level,kind,content in ancillary:
            if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:
                fds=array.array('i');fds.frombytes(content[:len(content)-len(content)%fds.itemsize]);received.extend(fds)
        if data!=TAG or flags&socket.MSG_CTRUNC or len(received)!=1:raise ValueError('Expected one complete owned TAP descriptor')
        descriptor=received[0];os.set_inheritable(descriptor,False);received.clear();return descriptor
    finally:
        for descriptor in received:os.close(descriptor)

def open_tap(run,namespace,name):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,14}',name) or name=='lo':raise ValueError('Invalid TAP name')
    resource=next((r for r in run.data['resources'] if r.get('kind')=='namespace' and r.get('name')==namespace and not r['deleted']),None)
    if resource is None:raise ValueError('Namespace does not belong to this run')
    state=Path('/run/netns',namespace).stat()
    if resource.get('boot_id')!=boot_id() or (state.st_ino,state.st_dev)!=(resource['inode'],resource['device']):raise RuntimeError('Namespace identity changed')
    descriptor=None;child=None
    # Abstract UNIX sockets belong to a network namespace. A private filesystem
    # socket is reachable from both the host and the owned network namespace.
    with tempfile.TemporaryDirectory(prefix='sdwtap-') as folder, socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as server:
        address=os.fsencode(str(Path(folder)/'fd.sock'))
        server.bind(address);server.listen(1);server.settimeout(10)
        try:
            child=run.spawn(['ip','netns','exec',namespace,sys.executable,'-c',HELPER,name,address.hex()],'tap-export-'+name+'-'+namespace[-1])
            peer,_=server.accept()
            with peer:
                peer.settimeout(5);descriptor=receive_fd(peer,expected_pid=child.pid,expected_uid=os.geteuid());peer.sendall(b'OK')
            if child.wait(timeout=5)!=0:raise RuntimeError('Namespace TAP export helper failed')
            return descriptor
        except BaseException:
            if descriptor is not None:os.close(descriptor)
            if child is not None:run.stop(child.pid)
            raise
