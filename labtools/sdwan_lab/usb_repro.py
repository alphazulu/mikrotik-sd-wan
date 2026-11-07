"""Bounded USB queue experiment on a disposable, network-isolated CHR."""
import argparse
import hashlib
import json
import importlib.util
from pathlib import Path
import socket
import struct
import secrets
import re
import sys
import time
import urllib.request

from .runtime import Lease,Run,atomic_json,checked,check_ports,install_signals
from .bench import wait_until


def redact_cli(body, password):
    body = re.sub(r'(password=)"[^"]*"', r'\1"<redacted>"', body, flags=re.S)
    return body.replace(password, '<redacted>')


def qmp(port,command,args=None):
    with socket.create_connection(('127.0.0.1',port),timeout=3) as sock:
        f=sock.makefile('rwb',buffering=0);json.loads(f.readline())
        for op in ({'execute':'qmp_capabilities'},{'execute':command,'arguments':args or {}}):
            f.write((json.dumps(op)+'\n').encode())
            while True:
                row=json.loads(f.readline())
                if 'error' in row:raise RuntimeError(str(row['error']))
                if 'return' in row:break
        return row['return']


def frame(size,seq):
    # Valid IPv4/UDP, zero UDP checksum permitted for IPv4. Only size varies.
    if size<60 or size>60000:raise ValueError('Frame size out of experiment bounds')
    data=struct.pack('!I',seq)+bytes(size-46)
    udp=struct.pack('!HHHH',50000,50001,len(data)+8,0)+data
    ip=struct.pack('!BBHHHBBH4s4s',0x45,0,len(udp)+20,seq&65535,0,64,17,0,socket.inet_aton('192.0.2.1'),socket.inet_aton('255.255.255.255'))
    total=sum(struct.unpack('!10H',ip));total=(total&65535)+(total>>16);checksum=(~((total&65535)+(total>>16)))&65535
    ip=ip[:10]+struct.pack('!H',checksum)+ip[12:]
    return bytes.fromhex('ffffffffffff0200005000010800')+ip+udp


def experiment(run,source,image,port,scenario,debugger=False):
    result={'scope':'Disposable CHR USB queue diagnosis only; not modem acceptance',
            'scenario':scenario,'reproduced':False,'completed':False,'steps':[]}
    path=run.folder/'report.json';guest=None;upstream=None
    try:
        check_ports(list(range(port,port+5)))
        # Probe the selected source without importing or changing the frozen checkout.
        import subprocess
        probe=subprocess.run([sys.executable,'-m','lte_rndis_emu','probe'],cwd=source/'lte-rndis-emu',capture_output=True,text=True,timeout=15,check=True)
        atomic_json(run.folder/'probe.json',json.loads(probe.stdout))
        if json.loads(probe.stdout)['decision']['path']!='usbredir-userspace':raise RuntimeError('Unproven/other USB path: stop and inspect probe JSON')
        result['source_usbredir_sha256']=hashlib.sha256((source/'lte-rndis-emu/lte_rndis_emu/usbredir.py').read_bytes()).hexdigest()
        result['source_files_sha256']={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((source/'lte-rndis-emu/lte_rndis_emu').glob('*.py'))}
        result['image_sha256']=hashlib.sha256(image.read_bytes()).hexdigest()
        emu=run.spawn([sys.executable,'-m','sdwan_lab.trace_emu','--source',source,'--trace',run.folder/'usb-trace.json','--port-base',port],'emulator')
        wait_until(lambda: emu.poll() is None and 'ready usbredir=' in (run.folder/'emulator.stdout').read_text(),15)
        upstream=socket.create_connection(('127.0.0.1',port+4),timeout=2)
        result['steps'].append('serve ready before QEMU');atomic_json(path,result)
        disk=run.folder/'chr.qcow2';checked(['qemu-img','create','-f','qcow2','-F','raw','-b',image,disk,'512M'])
        args=['qemu-system-x86_64','-name','sdwan-usb-repro-'+run.data['token'][:8],'-machine','q35','-accel','kvm','-cpu','host','-m','512','-smp','1','-display','none','-net','none',
              '-drive',f'file={disk},format=qcow2,if=virtio','-qmp',f'tcp:127.0.0.1:{port},server=on,wait=off','-serial',f'tcp:127.0.0.1:{port+1},server=on,wait=off',
              '-device','qemu-xhci,id=xhci','-chardev',f'socket,id=lteusb,host=127.0.0.1,port={port+2}',
              '-device','usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0']
        if debugger:
            args=['gdb','--batch','-iex','set debuginfod enabled off','-ex','set print frame-arguments none','-ex','handle SIGUSR1 nostop noprint pass','-ex','run','-ex','bt','--args']+args
            result['launcher']='gdb'
        atomic_json(run.folder/'qemu-command.json',args);guest=run.spawn(args,'qemu')
        def state():
            with urllib.request.urlopen(f'http://127.0.0.1:{port+3}/lte',timeout=3) as response:return json.load(response)
        def ready():
            if guest.poll() is not None:raise RuntimeError('Guest exited before USB initialization')
            s=state();return s['usb']['rndis_initialized'] and s['usb']['packet_filter']!=0
        wait_until(ready,120)
        # A bare CHR with no Ethernet NIC does not open RX URBs until LTE is enabled.
        spec=importlib.util.spec_from_file_location('usb_repro_bootstrap',source/'lab.py')
        lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab);lab.RUN=run.folder
        password=secrets.token_urlsafe(24);serial=[]
        con=lab.Console.__new__(lab.Console);con.name='repro';con.buffer=''
        con.s=socket.create_connection(('127.0.0.1',port+1),timeout=5);con.s.settimeout(1)
        original=con.expect
        def capture(*args,**kwargs):
            index,body=original(*args,**kwargs)
            serial.append(redact_cli(body,password));return index,body
        con.expect=capture
        try:
            con.configure(['/interface/lte/disable [find]','/interface/lte/apn/set [find where name=default] add-default-route=no use-peer-dns=no',
                           '/interface/lte/enable [find]','/interface/lte/print detail without-paging','/ip/dhcp-client/print detail without-paging'],password)
        except Exception as error:
            raise RuntimeError(redact_cli(str(error),password)) from None
        finally:
            con.s.close();(run.folder/'guest-cli.txt').write_text('\n'.join(serial))
        wait_until(lambda:ready() and state()['counters']['tx_frames']>0,45)
        result['steps'].append('CHR driver initialized RNDIS and packet filter')
        result['qemu_usb']=qmp(port,'human-monitor-command',{'command-line':'info usb'});atomic_json(path,result)
        with upstream as uplink:
            for seq in range(600):
                if guest.poll() is not None:break
                size=64 if scenario=='normal' or seq%4 else 2598
                packet=frame(size,seq);uplink.sendall(struct.pack('!I',len(packet))+packet)
                if scenario=='reset' and seq in (150,350):
                    qmp(port,'system_reset');time.sleep(.5)
                time.sleep(.002)
        time.sleep(2);result['state_after']=state();result['qemu_returncode']=guest.poll()
        result['completed']=True
    except BaseException as error:
        result['error']=type(error).__name__+': '+str(error)
    finally:
        if guest is not None:result['qemu_returncode_before_cleanup']=guest.poll()
        result['cleanup_pass']=run.cleanup()
        if upstream is not None:upstream.close()
        errors=(run.folder/'qemu.stderr').read_text() if (run.folder/'qemu.stderr').exists() else ''
        result['reproduced']='usb_packet_complete_one' in errors and 'Assertion' in errors
        if (run.folder/'usb-trace.json').exists():
            trace=json.loads((run.folder/'usb-trace.json').read_text());result['protocol_trace_summary']=trace['counts'];result['trace_truncated']=trace['trace_truncated']
            result['receive_queue_exercised']=trace['counts'].get('bulk_in_requests',0)>0
            if not result['receive_queue_exercised']:result['completed']=False;result['inconclusive']='No bulk IN requests; queue assertion was not exercised'
        if 'image_sha256' in result:result['backing_image_unchanged']=hashlib.sha256(image.read_bytes()).hexdigest()==result['image_sha256']
        atomic_json(path,result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,required=True);p.add_argument('--run-id',required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--chr-image',type=Path,required=True)
    p.add_argument('--port-base',type=int,default=24650);p.add_argument('--scenario',choices=('normal','mixed','reset'),default='mixed')
    p.add_argument('--gdb',action='store_true',help='Collect a function-only backtrace on an assertion')
    a=p.parse_args();source=a.source.resolve();image=a.chr_image.resolve()
    if not (source/'lte-rndis-emu/lte_rndis_emu/usbredir.py').is_file() or not image.is_file():p.error('Source or raw CHR image not found')
    install_signals()
    with Lease(a.workspace) as lease:
        run=Run(lease,a.run_id,{'source':str(source),'image':str(image),'scenario':a.scenario,'port_base':a.port_base})
        result=experiment(run,source,image,a.port_base,a.scenario,a.gdb);print(json.dumps(result,indent=2))
        return 0 if result['completed'] and result['cleanup_pass'] else 1


if __name__=='__main__':raise SystemExit(main())
