"""Exclusive workspace, persistent resource ownership and bounded cleanup."""
from __future__ import annotations
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import tempfile
import time
import uuid


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    with temp.open('w') as stream:
        stream.write(json.dumps(value, indent=2) + '\n'); stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def process_start(pid):
    try:
        value = Path('/proc', str(pid), 'stat').read_text().rpartition(') ')[2].split()
        return None if value[0] == 'Z' else value[19]
    except (OSError, IndexError):
        return None


def checked(args, timeout=15):
    return subprocess.run(list(map(str, args)), capture_output=True, text=True,
                          timeout=timeout, check=True)


class Lease:
    def __init__(self, workspace, host_lock=None):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.handles = []
        host_lock = Path(host_lock or Path(tempfile.gettempdir()) / f'mikrotik-sdwan-lab-{os.getuid()}.lock')
        try:
            for path in (host_lock, self.workspace / '.lock'):
                handle = path.open('a'); self.handles.append(handle)
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.close()
            raise RuntimeError('Lab workspace is already in use')

    def close(self):
        for handle in reversed(self.handles): handle.close()

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class Run:
    def __init__(self, lease, name, config=None, recover=False):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', name):
            raise ValueError('Run id must contain 1–48 letters, digits, _ or -')
        self.workspace = lease.workspace
        self.folder = self.workspace / 'runs' / name
        self.owner = self.workspace / 'owner.json'
        self.children = {}
        if recover:
            self.data = json.loads((self.folder / 'journal.json').read_text())
            current = json.loads(self.owner.read_text())
            if current['run_id'] != name or current['token'] != self.data['token']:
                raise RuntimeError('Workspace owner does not match this recovery journal')
        else:
            if self.owner.exists() and json.loads(self.owner.read_text()).get('state') != 'clean':
                raise RuntimeError('Previous run needs explicit recovery; inspect owner.json')
            self.folder.mkdir(parents=True, exist_ok=False)
            self.data = {'run_id': name, 'token': uuid.uuid4().hex, 'pid': os.getpid(),
                         'process_start': process_start(os.getpid()), 'state': 'running',
                         'config': config, 'resources': [], 'pending': [], 'warnings': []}
            self.save()

    def save(self):
        atomic_json(self.folder / 'journal.json', self.data)
        atomic_json(self.owner, {k: self.data[k] for k in ('run_id', 'token', 'state', 'pid', 'process_start')})

    def _intent(self, kind, name):
        item = {'kind': kind, 'name': name}
        self.data['pending'].append(item)
        self.save()
        return item

    def _record(self, intent, resource):
        self.data['resources'].append(resource)
        self.data['pending'].remove(intent)
        self.save()

    def namespace(self, suffix):
        if suffix not in ('a', 'b'): raise ValueError('Unknown namespace suffix')
        name = 'sdw-' + self.data['token'][:12] + '-' + suffix
        intent = self._intent('namespace', name)
        checked(['ip', 'netns', 'add', name])
        stat = Path('/run/netns', name).stat()
        self._record(intent, {'kind': 'namespace', 'name': name, 'inode': stat.st_ino,
                              'device': stat.st_dev, 'boot_id': boot_id(), 'deleted': False})
        return name

    def tap(self):
        name = 'sdw-' + self.data['token'][:10]
        intent = self._intent('tap', name)
        checked(['ip', 'tuntap', 'add', 'dev', name, 'mode', 'tap'])
        alias = 'sdwan-lab:' + self.data['token']
        checked(['ip', 'link', 'set', 'dev', name, 'alias', alias])
        index = Path('/sys/class/net', name, 'ifindex').read_text().strip()
        self._record(intent, {'kind':'tap', 'name':name, 'ifindex':index, 'alias':alias, 'deleted':False})
        return name

    def spawn(self, args, label, *, pass_fds=()):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', label): raise ValueError('Invalid log label')
        pass_fds=tuple(pass_fds)
        for descriptor in pass_fds:
            if type(descriptor) is not int or descriptor<3:raise ValueError('Export only explicit nonstandard descriptors')
            os.fstat(descriptor)
        out_path = self.folder / (label + '.stdout'); err_path = self.folder / (label + '.stderr')
        if out_path.exists() or err_path.exists(): raise FileExistsError('Log label already used: ' + label)
        intent = self._intent('process', label)
        env = dict(os.environ, SDWAN_LAB_RUN_TOKEN=self.data['token'])
        try:
            with out_path.open('xb') as out, err_path.open('xb') as err:
                child = subprocess.Popen(list(map(str, args)), stdout=out, stderr=err,
                                         start_new_session=True, env=env, pass_fds=tuple(pass_fds))
        except OSError:
            self.data['pending'].remove(intent); self.save()
            raise
        start = process_start(child.pid)
        self.children[child.pid] = child
        self._record(intent, {'kind': 'process', 'name': label, 'pid': child.pid,
                              'start': start, 'boot_id': boot_id(), 'argv': list(map(str, args)), 'deleted': False})
        return child

    def stop(self, pid):
        resource = next((r for r in reversed(self.data['resources']) if r.get('pid') == pid and not r['deleted']), None)
        if resource is None: return
        if resource.get('boot_id') and resource['boot_id'] != boot_id():
            resource.update(deleted=True, released_by_reboot=True); self.save(); return
        child = self.children.get(pid)
        if child is not None and child.poll() is not None:
            resource['deleted'] = True; self.save(); return
        current = process_start(pid)
        if current is None:
            resource['deleted'] = True; self.save(); return
        if resource['start'] is None or current != resource['start'] or os.getpgid(pid) != pid:
            raise RuntimeError('Process identity changed; refusing to signal ' + str(pid))
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            if process_start(pid) is None: break
            os.killpg(pid, sig)
            deadline = time.monotonic() + 3
            while process_start(pid) is not None and time.monotonic() < deadline:
                if child is not None: child.poll()
                time.sleep(.05)
            if sig != signal.SIGINT:
                self.data['warnings'].append({'pid': pid, 'signal': sig.name})
        if process_start(pid) is not None: raise RuntimeError('Owned process did not exit')
        if child is not None: child.wait(timeout=2)
        resource['deleted'] = True; self.save()

    def cleanup(self):
        errors = []
        for item in reversed(self.data['resources']):
            if item['deleted']: continue
            try:
                if item['kind'] == 'process':
                    self.stop(item['pid'])
                elif item['kind'] == 'tap':
                    path = Path('/sys/class/net', item['name'])
                    if path.exists():
                        if (path/'ifindex').read_text().strip() != item['ifindex'] or (path/'ifalias').read_text().strip() != item['alias']:
                            raise RuntimeError('TAP identity changed: ' + item['name'])
                        checked(['ip', 'link', 'delete', 'dev', item['name']])
                    item['deleted'] = True; self.save()
                elif item['kind'] == 'namespace':
                    path = Path('/run/netns', item['name'])
                    if path.exists():
                        stat = path.stat()
                        if item.get('boot_id') != boot_id() or (stat.st_ino, stat.st_dev) != (item['inode'], item['device']):
                            raise RuntimeError('Namespace identity changed: ' + item['name'])
                        checked(['ip', 'netns', 'delete', item['name']])
                    item['deleted'] = True; self.save()
            except Exception as error:
                errors.append(str(error))
        if self.data['pending']:
            errors.append('Interrupted creation has uncertain ownership: inspect pending journal entries')
        self.data['cleanup_errors'] = errors
        self.data.setdefault('cleanup_attempts', []).append({'monotonic': time.monotonic(), 'errors': list(errors)})
        self.data['state'] = 'cleanup_failed' if errors else 'clean'
        self.save()
        return not errors


def check_ports(ports):
    sockets = []
    try:
        for port in ports:
            if type(port) is not int or not 1024 <= port <= 65535: raise ValueError('Invalid loopback port')
            sock = socket.socket()
            sockets.append(sock)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    finally:
        for sock in sockets: sock.close()


def interrupted(signum, frame):
    raise InterruptedError('Lab runner received signal ' + str(signum))


def install_signals():
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
