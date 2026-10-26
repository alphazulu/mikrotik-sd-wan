"""Diskless benchmark endpoints and bounded loopback serial command transport."""
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import shlex
import socket
import time
import uuid

ISO_NAME='alpine-virt-3.22.7-x86_64.iso'
ISO_SHA256='c345ec65055908734523e03e81137a2e2f82f0094eb2b6e99bc6e07a7d2a0556'
ISO_URL='https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/x86_64/'+ISO_NAME
GUESTS={'client':(24500,24501),'server':(24510,24511)}
INIT='''#!/bin/busybox sh
export PATH=/bin:/sbin:/usr/bin:/usr/sbin TERM=dumb PS1='# '
/bin/busybox mount -t proc proc /proc
/bin/busybox mount -t sysfs sysfs /sys
/bin/busybox mount -t devtmpfs devtmpfs /dev
exec </dev/console >/dev/console 2>&1
/bin/busybox --install -s /bin 2>/dev/null
mkdir -p /tmp /run /etc/apk /var/cache/apk
modprobe virtio_pci
modprobe virtio_net
ip link set lo up
stty -echo
printf '\\nSDWAN_GUEST_SHELL_READY\\n'
exec /bin/sh
'''


def qmp(port,name,command='query-name',arguments=None):
    with socket.create_connection(('127.0.0.1',port),3) as sock:
        sock.settimeout(5);stream=sock.makefile('rwb');stream.readline()
        operations=[{'execute':'qmp_capabilities'},{'execute':'query-name'}]
        if command!='query-name':operations.append({'execute':command,'arguments':arguments or {}})
        result=None
        for operation in operations:
            stream.write(json.dumps(operation).encode()+b'\n');stream.flush()
            while True:
                try:line=stream.readline()
                except OSError:
                    if operation['execute']=='quit':return {}
                    raise
                if not line:
                    if operation['execute']=='quit':return {}
                    raise ConnectionError('QMP closed before response')
                value=json.loads(line)
                if 'event' not in value:break
            if 'error' in value:raise RuntimeError(value['error'])
            result=value['return']
            if operation['execute']=='query-name' and result.get('name')!=name:raise ValueError('QMP ownership mismatch')
        return result


def cpio_file(name,data,mode=0o100755):
    if name.startswith('/') or '..' in name.split('/') or '\0' in name:raise ValueError('Unsafe CPIO name')
    encoded=name.encode()+b'\0'
    fields=[1,mode,0,0,1,0,len(data),0,0,0,0,len(encoded),0]
    header=b'070701'+b''.join(f'{value:08x}'.encode() for value in fields)
    item=header+encoded;item+=b'\0'*(-len(item)%4);item+=data
    return item+b'\0'*(-len(data)%4)


def build_initrd(images):
    images=Path(images);original=(images/'initramfs-virt').read_bytes()
    overlay=cpio_file('init',INIT.encode())+cpio_file('TRAILER!!!',b'',0)
    target=images/'sdwan-perf-initramfs.gz'
    target.write_bytes(original+gzip.compress(overlay,mtime=0))
    return {'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
            'original_sha256':hashlib.sha256(original).hexdigest(),'overlay_sha256':hashlib.sha256(overlay).hexdigest()}


def iso_boot_files(path,directory):
    """Read exact Rock Ridge boot filenames from the pinned Alpine ISO."""
    path=Path(path);directory=Path(directory)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=ISO_SHA256:raise ValueError('Alpine ISO SHA256 mismatch')
    with path.open('rb') as stream:
        stream.seek(16*2048);pvd=stream.read(2048)
        if pvd[1:6]!=b'CD001':raise ValueError('Not an ISO9660 image')
        def entries(record):
            extent=int.from_bytes(record[2:6],'little');size=int.from_bytes(record[10:14],'little')
            stream.seek(extent*2048);data=stream.read(size);offset=0;result={}
            while offset<len(data):
                length=data[offset]
                if not length:offset=(offset//2048+1)*2048;continue
                rec=data[offset:offset+length];offset+=length
                name=rec[33:33+rec[32]].decode('ascii');su=rec[33+rec[32]+(rec[32]%2==0):];i=0
                while i+4<=len(su) and su[i+2]>=4:
                    tag=su[i:i+2];n=su[i+2]
                    if tag==b'NM':name=su[i+5:i+n].decode()
                    i+=n
                if name not in ('\0','\1'):result[name.split(';')[0].lower()]=rec
            return result
        boot=entries(entries(pvd[156:190])['boot']);directory.mkdir(parents=True,exist_ok=True)
        result={}
        for name in ('vmlinuz-virt','initramfs-virt'):
            record=boot[name];stream.seek(int.from_bytes(record[2:6],'little')*2048)
            data=stream.read(int.from_bytes(record[10:14],'little'));(directory/name).write_bytes(data)
            result[name]={'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        return result


def decode_frame(data,token):
    data=data.replace(b'\r',b'');begin=('__SDWAN_BEGIN_'+token+'__\n').encode();end=('\n__SDWAN_END_'+token+'__').encode()
    if begin not in data or end not in data:return None
    body=data.split(begin,1)[1].split(end,1)[0];rc,separator,encoded=body.partition(b'\n')
    if not separator or not re.fullmatch(rb'\d{1,3}',rc):raise ValueError('Invalid guest command status')
    decoded=base64.b64decode(b''.join(encoded.splitlines()),validate=True)
    return int(rc),decoded.decode('utf-8',errors='replace')


def command(node,code,timeout=60):
    if node not in GUESTS:raise ValueError('Unknown benchmark endpoint')
    port,serial=GUESTS[node];qmp(port,'sdwan-perf-'+node)
    token=uuid.uuid4().hex
    # Start the response AFTER the child exits. Kernel console messages during
    # a long transfer must not become part of the command status/base64 frame.
    request="stty -echo; /bin/sh -c "+shlex.quote(code)+" >/tmp/sdwan-command-output 2>&1; sdwan_command_rc=$?; printf '\\n__SDWAN_BEGIN_"+token+"__\\n%s\\n' \"$sdwan_command_rc\"; base64 /tmp/sdwan-command-output; printf '\\n__SDWAN_END_"+token+"__\\n'\n"
    with socket.create_connection(('127.0.0.1',serial),5) as sock:
        sock.settimeout(1);sock.sendall(request.encode());result=bytearray();deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:part=sock.recv(65536)
            except TimeoutError:continue
            if not part:raise ConnectionError('Guest serial closed')
            result.extend(part)
            if len(result)>4*1024*1024:raise ValueError('Guest output exceeds bound')
            try:frame=decode_frame(bytes(result),token)
            except ValueError as error:
                error.guest_transcript=bytes(result);raise
            if frame is not None:return frame
    raise TimeoutError('Guest command timed out: '+node)


def checked(node,code,timeout=60):
    rc,output=command(node,code,timeout)
    if rc:raise RuntimeError(f'{node} command failed ({rc}): '+output[-2000:])
    return output


def bootstrap(node):
    number=82 if node=='client' else 83
    checked(node,f'ip link set eth0 up\nip address replace 10.{number}.0.15/24 dev eth0\nip route replace default via 10.{number}.0.2\nprintf "nameserver 10.{number}.0.3\\n" >/etc/resolv.conf')
    checked(node,'apk --root / --initdb --no-scripts --no-cache --repository http://dl-cdn.alpinelinux.org/alpine/v3.22/main add iperf3',120)
    return {'version':checked(node,'iperf3 --version'),'packages':checked(node,'apk info -vv')}


def launch_args(root,node):
    """Fixed owned ports: data-plane socket links never bind outside loopback."""
    if node not in GUESTS:raise ValueError('Unknown benchmark endpoint')
    root=Path(root);run=root/'runtime';images=root/'images'
    qport,serial=GUESTS[node];number=82 if node=='client' else 83
    args=['qemu-system-x86_64','-name','sdwan-perf-'+node,'-machine','q35',
          '-accel','kvm','-cpu','host','-m','384','-smp','1','-display','none',
          '-no-reboot','-kernel',str(images/'vmlinuz-virt'),'-initrd',str(images/'sdwan-perf-initramfs.gz'),
          '-append','console=ttyS0,115200 rdinit=/init',
          '-serial',f'tcp:127.0.0.1:{serial},server=on,wait=off',
          '-qmp',f'tcp:127.0.0.1:{qport},server=on,wait=off',
          '-pidfile',str(run/(node+'.pid')),'-daemonize','-D',str(run/(node+'.qemu.log')),
          '-netdev',f'user,id=mgmt,net=10.{number}.0.0/24,dhcpstart=10.{number}.0.15,ipv6=off',
          '-device',f'virtio-net-pci,netdev=mgmt,mac=52:54:00:{number}:00:01']
    links=[('lan','connect',24431),('direct','connect',24530)] if node=='client' else [('wan1','listen',24532),('direct','listen',24530),('wan2','listen',24540)]
    for i,(name,mode,port) in enumerate(links,2):
        args+=['-netdev',f'socket,id={name},{mode}=127.0.0.1:{port}',
               '-device',f'virtio-net-pci,netdev={name},mac=52:54:00:{number}:00:{i:02x}']
    return args
