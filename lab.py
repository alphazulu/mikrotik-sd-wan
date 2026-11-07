#!/usr/bin/env python3
"""Local CHR SD-WAN lab. Python standard library + QEMU, no root required."""
import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import grp
import json
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import shlex
import signal
import socket
import struct
import subprocess
import sys
import time
import pwd
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
RUN = ROOT / 'runtime'
IMG = ROOT / 'images'
VERSION = '7.24.5'
URL = f'https://download.mikrotik.com/routeros/{VERSION}/chr-{VERSION}.img.zip'
NODES = {'edge': (0, 18080, 12222, 18291, 1024),
         'isp1': (1, 18081, 12223, 18292, 512),
         'isp2': (2, 18082, 12224, 18293, 512),
         'isp3': (3, 18083, 12225, 18294, 512),
         'client': (10, 18090, 12230, 18301, 512)}


def save(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    tmp.replace(path)


def prepare():
    for binary in ('qemu-system-x86_64', 'qemu-img'):
        if not shutil.which(binary):
            raise RuntimeError(f'Missing {binary}; install qemu-system-x86 qemu-utils')
    IMG.mkdir(exist_ok=True)
    RUN.mkdir(exist_ok=True)
    archive = IMG / f'chr-{VERSION}.img.zip'
    raw = IMG / f'chr-{VERSION}.img'
    if not archive.exists():
        print(f'Downloading {URL}', flush=True)
        partial = archive.with_suffix('.zip.part')
        with urllib.request.urlopen(urllib.request.Request(URL, method='HEAD'), timeout=60) as response:
            total = int(response.headers['Content-Length'])
        prefix = partial.stat().st_size if partial.exists() else 0
        if prefix > total:
            raise RuntimeError('Partial download is larger than official archive')
        # The MikroTik server limits individual connections; preserve downloaded prefix,
        # fetch the remainder in up to six independent validated HTTP ranges.
        pieces = []
        piece_size = 4 * 1024 * 1024
        for start in range(prefix, total, piece_size):
            end = min(total, start + piece_size) - 1
            pieces.append((start, end, IMG / f'download-{start}-{end}.part'))
        def fetch(piece):
            start, end, dest = piece
            if dest.exists() and dest.stat().st_size == end - start + 1:
                return
            for attempt in range(5):
                offset = start + (dest.stat().st_size if dest.exists() else 0)
                if offset > end:
                    break
                req = urllib.request.Request(URL, headers={'Range': f'bytes={offset}-{end}'})
                with urllib.request.urlopen(req, timeout=60) as response:
                    expected = f'bytes {offset}-{end}/{total}'
                    if response.status != 206 or response.headers.get('Content-Range') != expected:
                        raise RuntimeError('Server did not honor requested download range')
                    with dest.open('ab') as out:
                        shutil.copyfileobj(response, out)
                if dest.stat().st_size == end - start + 1:
                    break
                print(f'Resuming truncated range {start}-{end}, attempt {attempt+1}', flush=True)
            if dest.stat().st_size != end - start + 1:
                raise RuntimeError('Truncated download range after retries')
            print(f'Downloaded range {start}-{end}', flush=True)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(fetch, pieces))
        with partial.open('ab') as out:
            for _, _, dest in pieces:
                with dest.open('rb') as source:
                    shutil.copyfileobj(source, out)
        with zipfile.ZipFile(partial) as z:
            if z.testzip():
                raise RuntimeError('ZIP CRC validation failed')
        partial.replace(archive)
        for _, _, dest in pieces:
            dest.unlink()
    if not raw.exists():
        with zipfile.ZipFile(archive) as z:
            member = next(x for x in z.infolist() if x.filename.endswith('.img'))
            with z.open(member) as source, raw.open('wb') as out:
                shutil.copyfileobj(source, out)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (archive, raw)}
    manifest = IMG / 'manifest.json'
    if manifest.exists() and json.loads(manifest.read_text())['sha256'] != hashes:
        raise RuntimeError('Base image hash changed; refusing to continue')
    save(manifest, {'url': URL, 'sha256': hashes,
                    'verification': 'HTTPS official origin + ZIP CRC; locally pinned SHA256, not vendor signature'})
    for name in NODES:
        disk = IMG / f'{name}.qcow2'
        if not disk.exists():
            subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'raw',
                            '-b', str(raw), str(disk), '512M'], check=True)
    if not (RUN / 'credentials.json').exists():
        save(RUN / 'credentials.json', {n: {'username': 'admin', 'password': secrets.token_urlsafe(24)} for n in NODES})
        (RUN / 'credentials.json').chmod(0o600)
    config_dir = ROOT / 'routeros'
    config_dir.mkdir(exist_ok=True)
    for name in NODES:
        (config_dir / f'{name}.rsc').write_text('# LAB ONLY: generated baseline for a clean CHR. Password is set separately.\n' + '\n'.join(config(name)) + '\n')
    print('Images and per-node writable overlays ready.', flush=True)


def qmp(name, command, arguments=None):
    with socket.socket(socket.AF_INET) as s:
        s.settimeout(10)
        s.connect(('127.0.0.1', 24100 + NODES[name][0]))
        f = s.makefile('rwb', buffering=0)
        json.loads(f.readline())
        for cmd in ({'execute': 'qmp_capabilities'},
                    {'execute': command, 'arguments': arguments or {}}):
            f.write(json.dumps(cmd).encode() + b'\n')
            while True:
                result = json.loads(f.readline())
                if 'error' in result:
                    raise RuntimeError(result['error'])
                if 'return' in result:
                    break
        return result['return']


def alive(name):
    try:
        return qmp(name, 'query-status')['status']
    except (OSError, ValueError, RuntimeError):
        return None


def api(name, path, data=None, method=None, timeout=45):
    cred = json.loads((RUN / 'credentials.json').read_text())[name]
    token = base64.b64encode(f"{cred['username']}:{cred['password']}".encode()).decode()
    req = urllib.request.Request(f'http://127.0.0.1:{NODES[name][1]}/rest/{path.lstrip("/")}',
                                 data=None if data is None else json.dumps(data).encode(),
                                 headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'},
                                 method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as response:
            body = response.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'{name} {path}: {e.code} {e.read().decode()}') from e


def node_command(name, accel):
    idx, http, ssh, winbox, ram = NODES[name]
    args = ['qemu-system-x86_64', '-name', f'sdwan-{name}', '-machine', 'q35',
            '-accel', accel, '-cpu', 'host' if accel == 'kvm' else 'max',
            '-m', str(ram), '-smp', '1', '-display', 'none',
            '-drive', f'file={IMG / (name + ".qcow2")},format=qcow2,if=virtio',
            '-serial', f'tcp:127.0.0.1:{25100+idx},server=on,wait=off',
            '-qmp', f'tcp:127.0.0.1:{24100+idx},server=on,wait=off',
            '-pidfile', str(RUN / f'{name}.pid'), '-daemonize',
            '-D', str(RUN / f'{name}.qemu.log')]
    def nic(ident, backend, number):
        args.extend(['-netdev', f'{backend},id={ident}', '-device',
                     f'virtio-net-pci,netdev={ident},id=nic{number},mac=52:54:00:77:{idx:02x}:{number:02x}'])
    nic('mgmt', f'user,net=10.77.{idx}.0/24,dhcpstart=10.77.{idx}.15,ipv6=off,'
        f'hostfwd=tcp:127.0.0.1:{http}-10.77.{idx}.15:80,'
        f'hostfwd=tcp:127.0.0.1:{ssh}-10.77.{idx}.15:22,'
        f'hostfwd=tcp:127.0.0.1:{winbox}-10.77.{idx}.15:8291,'
        f'hostfwd=tcp:127.0.0.1:{18728+idx}-10.77.{idx}.15:8728', 1)
    if name.startswith('isp'):
        nic('inside', f'socket,listen=127.0.0.1:{23100 + idx}', 2)
    elif name == 'client':
        nic('lan', 'socket,listen=127.0.0.1:23110', 2)
    else:
        for i in (1, 2, 3):
            nic(f'wan{i}', f'socket,connect=127.0.0.1:{22100 + i}', i + 1)
        nic('lan', 'socket,connect=127.0.0.1:23110', 5)
    if name == 'edge' and os.environ.get('LTE_RNDIS_EMU') == '1':
        # Emulator must print ready before QEMU starts; existing lifecycle stays
        # unchanged. Import lazily so other nodes have no emulator dependency.
        emulator_root = str(ROOT / 'lte-rndis-emu')
        sys.path.insert(0, emulator_root)
        try:
            from lte_rndis_emu.emulator import qemu_args
            args.extend(qemu_args())
        finally:
            sys.path.remove(emulator_root)
    return args


def resource(name, timeout=45):
    result = api(name, 'system/resource', timeout=timeout)
    return result[0] if isinstance(result, list) else result


class Console:
    def __init__(self, name):
        self.name = name
        self.s = socket.socket(socket.AF_INET)
        self.s.settimeout(1)
        self.s.connect(('127.0.0.1', 25100 + NODES[name][0]))
        self.buffer = ''

    def send(self, value):
        self.s.sendall(value.encode() + b'\r')

    def expect(self, patterns, timeout=120):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for i, pattern in enumerate(patterns):
                match = re.search(pattern, self.buffer, re.I)
                if match:
                    old = self.buffer[:match.end()]
                    self.buffer = self.buffer[match.end():]
                    return i, old
            try:
                part = self.s.recv(65536)
                if not part:
                    raise RuntimeError('Serial console closed')
                self.buffer += re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', part.decode(errors='replace'))
            except socket.timeout:
                pass
        raise TimeoutError(f'{self.name} console timeout: {self.buffer[-400:]}')

    def configure(self, commands, password):
        progress_file = RUN / f'{self.name}.bootstrap.json'
        progress = json.loads(progress_file.read_text())['next'] if progress_file.exists() else 0
        self.send('')
        idx, _ = self.expect([r'Login:', r'\[[^\r\n]+@[^\r\n]+\] >'])
        if idx == 0:
            self.send('admin+ct')
            self.expect([r'Password:'])
            self.send(password if progress_file.exists() else '')
            while True:
                idx, _ = self.expect([r'new password>', r'repeat new password>',
                                      r'Do you want to see the software license\?.*\[Y/n\]:',
                                      r'\[[^\r\n]+@[^\r\n]+\] >', r'Change your password'])
                if idx in (0, 1):
                    self.send(password)
                elif idx == 2:
                    self.send('n')
                elif idx == 3:
                    break
        self.send(f'/user set [find name=admin] password="{password}"')
        self.expect([r'\[[^\r\n]+@[^\r\n]+\] >'])
        save(progress_file, {'next': progress})
        for index, cmd in enumerate(commands):
            if index < progress:
                continue
            self.send(cmd)
            _, result = self.expect([r'\[[^\r\n]+@[^\r\n]+\] >'], timeout=30)
            if re.search(r'(syntax error|expected end|bad command|failure:|invalid value|input does not match|no such item)', result, re.I):
                raise RuntimeError(f'{self.name}: {result}')
            save(progress_file, {'next': index + 1})
        self.send('/quit')
        self.s.close()


def config(name):
    idx = NODES[name][0]
    cmds = [f'/system identity set name=sdwan-{name}',
            '/ip dhcp-client remove [find]',
            f'/ip address add address=10.77.{idx}.15/24 interface=ether1 comment=lab-management',
            '/ip service disable [find where dynamic=no]',
            '/ip service set [find where name=www and dynamic=no] disabled=no',
            '/ip service set [find where name=ssh and dynamic=no] disabled=no',
            '/ip service set [find where name=winbox and dynamic=no] disabled=no',
            '/ip service set [find where name=api and dynamic=no] disabled=no',
            '/tool mac-server set allowed-interface-list=none',
            '/tool mac-server mac-winbox set allowed-interface-list=none',
            '/ip neighbor discovery-settings set discover-interface-list=none',
            '/ip firewall filter add chain=input connection-state=established,related action=accept',
            '/ip firewall filter add chain=input connection-state=invalid action=drop',
            '/ip firewall filter add chain=input in-interface=ether1 action=accept comment=lab-management',
            '/ip firewall filter add chain=input protocol=icmp action=accept',
            '/ip firewall filter add chain=input action=drop',
            '/ip firewall filter add chain=forward connection-state=established,related action=accept',
            '/ip firewall filter add chain=forward connection-state=invalid action=drop']
    if name.startswith('isp'):
        cmds += [f'/ip route add dst-address=0.0.0.0/0 gateway=10.77.{idx}.2',
                 f'/ip address add address=172.20.{idx}.1/30 interface=ether2',
                 f'/ip address add address=198.18.{idx}.1/32 interface=lo comment=deterministic-probe',
                 '/ip address add address=198.19.0.1/32 interface=lo comment=shared-probe',
                 '/ip firewall filter add chain=input dst-address=198.19.0.1 protocol=icmp action=accept comment=path-proof place-before=0',
                 '/ip firewall nat add chain=srcnat out-interface=ether1 action=masquerade',
                 '/ip firewall filter add chain=forward in-interface=ether2 out-interface=ether1 action=accept']
    elif name == 'client':
        cmds += ['/ip address add address=192.168.50.101/24 interface=ether2',
                 '/ip address add address=192.168.50.102/24 interface=ether2',
                 '/ip route add dst-address=0.0.0.0/0 gateway=192.168.50.1']
    else:
        cmds += ['/interface list add name=WAN',
                 '/ip address add address=192.168.50.1/24 interface=ether5',
                 '/routing table add name=prefer-wan2 fib']
        for i in (1, 2, 3):
            cmds += [f'/ip address add address=172.20.{i}.2/30 interface=ether{i+1}',
                     f'/interface list member add list=WAN interface=ether{i+1}',
                     f'/ip route add dst-address=198.18.{i}.1/32 gateway=172.20.{i}.1 comment=probe-wan{i}',
                     f'/ip route add dst-address=0.0.0.0/0 gateway=172.20.{i}.1 distance={i} check-gateway=ping comment=baseline-wan{i}',
                     f'/routing table add name=probe-wan{i} fib',
                     f'/ip route add dst-address=0.0.0.0/0 gateway=172.20.{i}.1@main routing-table=probe-wan{i} comment=pinned-wan{i}',
                     f'/ip route add dst-address=0.0.0.0/0 gateway=172.20.{i}.1@main routing-table=prefer-wan2 distance={ {1:2,2:1,3:3}[i]} check-gateway=ping comment=client102-wan{i}']
        cmds += ['/routing rule add src-address=192.168.50.102/32 action=lookup-only-in-table table=prefer-wan2',
                 '/ip firewall nat add chain=srcnat out-interface-list=WAN action=masquerade',
                 '/ip firewall filter add chain=forward in-interface=ether5 out-interface-list=WAN action=accept']
    cmds += dns_config(name)
    cmds += ['/ip firewall filter add chain=forward action=drop']
    return cmds


def dns_config(name):
    if name.startswith('isp'):
        idx = NODES[name][0]
        return [f'/ip dns set servers=10.77.{idx}.3 allow-remote-requests=yes',
                '/ip firewall filter add chain=input in-interface=ether2 protocol=udp dst-port=53 action=accept comment=lab-dns place-before=0',
                '/ip firewall filter add chain=input in-interface=ether2 protocol=tcp dst-port=53 action=accept comment=lab-dns place-before=0']
    if name == 'edge':
        return ['/ip dns set servers=172.20.1.1,172.20.2.1,172.20.3.1 allow-remote-requests=yes',
                '/ip firewall filter add chain=input in-interface=ether5 protocol=udp dst-port=53 action=accept comment=lab-dns place-before=0',
                '/ip firewall filter add chain=input in-interface=ether5 protocol=tcp dst-port=53 action=accept comment=lab-dns place-before=0']
    return ['/ip dns set servers=192.168.50.1 allow-remote-requests=no']


def proxy_request(request):
    with socket.socket(socket.AF_INET) as s:
        s.settimeout(5)
        s.connect(('127.0.0.1', 24099))
        s.sendall(json.dumps(request).encode() + b'\n')
        f = s.makefile('rb')
        result = json.loads(f.readline())
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result


async def proxy_daemon():
    """QEMU socket-netdev framing; independent per-direction packet queues."""
    defaults = dict(loss=0.0, delay=0.0, jitter=0.0, rate=0.0, blackhole=False)
    state = {f'wan{i}': dict(defaults, frames=0, dropped=0, connected=False) for i in (1, 2, 3)}
    async def pipe(reader, writer, wan):
        q = asyncio.Queue(maxsize=4096)
        async def receive():
            next_slot = 0.0
            last_due = 0.0
            while True:
                header = await reader.readexactly(4)
                length = struct.unpack('!I', header)[0]
                if length > 65536:
                    raise ValueError('Invalid Ethernet frame length')
                frame = header + await reader.readexactly(length)
                st = state[wan]
                st['frames'] += 1
                if st['blackhole'] or random.random() * 100 < st['loss'] or q.full():
                    st['dropped'] += 1
                    continue
                now = asyncio.get_running_loop().time()
                next_slot = max(now, next_slot) + (length * 8 / (st['rate'] * 1000) if st['rate'] else 0)
                due = max(last_due, next_slot + max(0, st['delay'] + random.uniform(-st['jitter'], st['jitter'])) / 1000)
                last_due = due
                q.put_nowait((due, frame))
        async def transmit():
            while True:
                due, frame = await q.get()
                await asyncio.sleep(max(0, due - asyncio.get_running_loop().time()))
                if state[wan]['blackhole']:
                    state[wan]['dropped'] += 1
                else:
                    writer.write(frame)
                    await writer.drain()
        tasks = [asyncio.create_task(receive()), asyncio.create_task(transmit())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def connect(reader, writer, i):
        wan = f'wan{i}'
        if state[wan]['connected']:
            writer.close()
            await writer.wait_closed()
            return
        upstream = None
        tasks = []
        try:
            upstream_reader, upstream = await asyncio.open_connection('127.0.0.1', 23100+i)
            state[wan]['connected'] = True
            tasks = [asyncio.create_task(pipe(reader, upstream, wan)),
                     asyncio.create_task(pipe(upstream_reader, writer, wan))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            state[wan]['connected'] = False
            writer.close()
            if upstream:
                upstream.close()

    async def control(reader, writer):
        try:
            req = json.loads(await reader.readline())
            if req.get('reset'):
                for st in state.values():
                    st.update(defaults)
            elif 'wan' in req:
                st = state[req['wan']]
                for key, value in req.get('set', {}).items():
                    if key not in defaults:
                        raise ValueError(f'Unknown fault field: {key}')
                    if key != 'blackhole' and (not isinstance(value, (int, float)) or not 0 <= value <= (100 if key == 'loss' else 1000000)):
                        raise ValueError(f'Invalid {key}')
                    if key == 'blackhole' and not isinstance(value, bool):
                        raise ValueError('blackhole must be a boolean')
                    st[key] = value
            result = state
        except (ValueError, KeyError, TypeError) as e:
            result = {'error': str(e)}
        writer.write(json.dumps(result).encode() + b'\n')
        await writer.drain()
        writer.close()
    servers = [await asyncio.start_server(control, '127.0.0.1', 24099)]
    for i in (1, 2, 3):
        async def handler(r, w, number=i):
            await connect(r, w, number)
        servers.append(await asyncio.start_server(handler, '127.0.0.1', 22100+i))
    save(RUN / 'proxy.pid.json', {'pid': os.getpid()})
    print('Fault emulator ready', flush=True)
    await asyncio.Event().wait()


def up(accel):
    prepare()
    # These are simulated Internet services, not an external decision controller.
    services = ROOT / 'tools/probe_services.py'
    if services.exists():
        subprocess.run([sys.executable, str(services), 'start'], check=True)
    kvm_group = grp.getgrnam('kvm') if Path('/dev/kvm').exists() else None
    kvm_member = bool(kvm_group and (kvm_group.gr_gid in os.getgroups() or pwd.getpwuid(os.getuid()).pw_name in kvm_group.gr_mem))
    if accel == 'auto':
        accel = 'kvm' if os.access('/dev/kvm', os.R_OK | os.W_OK) or kvm_member else 'tcg'
    print(f'Accelerator: {accel}', flush=True)
    def launch(name):
        command = node_command(name, accel)
        if accel == 'kvm' and kvm_member and kvm_group.gr_gid not in os.getgroups():
            command = ['sg', 'kvm', '-c', shlex.join(command)]
        subprocess.run(command, check=True)
    for name in ('isp1', 'isp2', 'isp3', 'client'):
        if not alive(name):
            launch(name)
    try:
        proxy_request({})
    except (OSError, ValueError):
        with (RUN / 'proxy.log').open('ab') as log:
            subprocess.Popen([sys.executable, str(Path(__file__)), '_proxy'],
                             stdout=log, stderr=log, start_new_session=True)
        for _ in range(100):
            try:
                proxy_request({})
                break
            except (OSError, ValueError):
                time.sleep(.1)
        else:
            raise RuntimeError('Fault proxy did not start; see runtime/proxy.log')
    if not alive('edge'):
        launch('edge')
    credentials = json.loads((RUN / 'credentials.json').read_text())
    for name in NODES:
        marker = RUN / f'{name}.configured'
        if not marker.exists():
            print(f'Bootstrapping {name}...', flush=True)
            Console(name).configure(config(name), credentials[name]['password'])
        for _ in range(30):
            try:
                info = resource(name, timeout=2)
                if info['version'].split()[0] != VERSION:
                    raise RuntimeError(f'Unexpected RouterOS version: {info["version"]}')
                marker.write_text(VERSION + '\n')
                print(f'{name}: RouterOS {info["version"]}, REST ready', flush=True)
                break
            except (OSError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError(f'{name}: REST did not become ready')
    status()


def status():
    for name, (_, http, ssh, winbox, _) in NODES.items():
        print(f'{name:7} {str(alive(name)):10} Web/REST=127.0.0.1:{http} SSH=:{ssh} WinBox=:{winbox} API=:{18728+NODES[name][0]}')
    try:
        print(json.dumps(proxy_request({}), indent=2))
    except OSError:
        print('Fault emulator: stopped')


def down():
    for name in NODES:
        if alive(name):
            # RouterOS flushes its filesystem on shutdown; wait before QEMU quit fallback.
            try:
                api(name, 'system/shutdown', {}, 'POST')
            except (OSError, RuntimeError):
                qmp(name, 'system_powerdown')
    end = time.monotonic() + 30
    while any(alive(n) for n in NODES) and time.monotonic() < end:
        time.sleep(.5)
    remaining = [n for n in NODES if alive(n)]
    if remaining:
        raise RuntimeError(f'Guests did not shut down: {remaining}; left running to avoid data loss')
    try:
        pid = json.loads((RUN / 'proxy.pid.json').read_text())['pid']
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes()
        if str(Path(__file__)).encode() in cmd and b'_proxy' in cmd:
            os.kill(pid, signal.SIGTERM)
    except (FileNotFoundError, ProcessLookupError):
        pass
    print('Lab stopped. Disks and credentials preserved.')


def ping(name, address, source=None, count=4):
    data = {'address': address, 'count': str(count), 'interval': '200ms'}
    if source:
        data['src-address'] = source
    result = api(name, 'ping', data, 'POST')
    return result, any('time' in row and not row.get('status') for row in result)


def verify():
    report = {'timestamp_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'checks': []}
    def check(label, success, detail):
        report['checks'].append({'check': label, 'pass': success, 'detail': detail})
        print(f'{"PASS" if success else "FAIL"} {label}', flush=True)
    for n in NODES:
        info = resource(n)
        check(n + ' version', info['version'].split()[0] == VERSION, info['version'])
    for i in (1, 2, 3):
        result, ok = ping('edge', f'198.18.{i}.1')
        check(f'WAN{i} deterministic probe', ok, result)
    for src in ('192.168.50.101', '192.168.50.102'):
        result, ok = ping('client', '192.168.50.1', src)
        check(src + ' LAN gateway', ok, result)
        result, ok = ping('client', '198.19.0.1', src)
        check(src + ' routed WAN probe', ok, result)
    # Baseline route selection assertions are separate from future SLA acceptance.
    routes = api('edge', 'ip/route')
    native = bool(api('edge', 'system/scheduler?name=sdwan-controller'))
    expectations = [('main', 'sdwan:v1:route:default:wan1'), ('sdwan-client102', 'sdwan:v1:route:client102:wan2')] if native else [('main', 'baseline-wan1'), ('prefer-wan2', 'client102-wan2')]
    for table, comment in expectations:
        active = [r for r in routes if r.get('routing-table') == table and r.get('active') == 'true' and r.get('comment') == comment]
        check(table + (' native preference' if native else ' baseline preference'), bool(active), active)
    save(RUN / 'verification.json', report)
    if not all(c['pass'] for c in report['checks']):
        raise RuntimeError('Verification failed; see runtime/verification.json')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('prepare')
    u = sub.add_parser('up'); u.add_argument('--accel', choices=['auto', 'kvm', 'tcg'], default='auto')
    sub.add_parser('down'); sub.add_parser('status'); sub.add_parser('verify'); sub.add_parser('_proxy')
    f = sub.add_parser('fault'); f.add_argument('wan', choices=['wan1', 'wan2', 'wan3'])
    for field in ('loss', 'delay', 'jitter', 'rate'):
        f.add_argument('--' + field, type=float)
    f.add_argument('--blackhole', choices=['on', 'off'])
    sub.add_parser('heal')
    link = sub.add_parser('link'); link.add_argument('wan', choices=['wan1', 'wan2', 'wan3']); link.add_argument('state', choices=['up', 'down'])
    a = sub.add_parser('api'); a.add_argument('node', choices=NODES); a.add_argument('path'); a.add_argument('--data'); a.add_argument('--method')
    s = sub.add_parser('export'); s.add_argument('node', choices=NODES, default='edge', nargs='?')
    args = p.parse_args()
    if args.command == 'prepare': prepare()
    elif args.command == 'up': up(args.accel)
    elif args.command == 'down': down()
    elif args.command == 'status': status()
    elif args.command == 'verify': verify()
    elif args.command == '_proxy': asyncio.run(proxy_daemon())
    elif args.command == 'fault':
        values = {k: getattr(args, k) for k in ('loss', 'delay', 'jitter', 'rate') if getattr(args, k) is not None}
        if args.blackhole is not None: values['blackhole'] = args.blackhole == 'on'
        print(json.dumps(proxy_request({'wan': args.wan, 'set': values}), indent=2))
    elif args.command == 'heal':
        proxy_request({'reset': True})
        for i in (1, 2, 3): qmp('edge', 'set_link', {'name': f'nic{i+1}', 'up': True})
        print('All WAN links and impairment settings restored.')
    elif args.command == 'link': qmp('edge', 'set_link', {'name': f'nic{int(args.wan[-1])+1}', 'up': args.state == 'up'})
    elif args.command == 'api':
        print(json.dumps(api(args.node, args.path, None if args.data is None else json.loads(args.data), args.method), indent=2, ensure_ascii=False))
    elif args.command == 'export':
        result = api(args.node, 'export', {}, 'POST')
        save(RUN / f'{args.node}-export.json', result)
        print(f'Export saved: runtime/{args.node}-export.json (RouterOS hides sensitive values by default)')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        message = str(exc)
        if (RUN / 'credentials.json').exists():
            for cred in json.loads((RUN / 'credentials.json').read_text()).values():
                message = message.replace(cred['password'], '<redacted>')
        print(f'ERROR: {message}', file=sys.stderr)
        sys.exit(1)
