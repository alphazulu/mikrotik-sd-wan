#!/usr/bin/env python3
"""Install pinned container package and enable device mode on isolated CHR only."""
from pathlib import Path
import functools
import hashlib
import http.server
import json
import shlex
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import container_lab
lab=container_lab.load()
assert lab.ROOT==ROOT/'runtime/container-lab/project'

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args): pass

def wait_ready(timeout=100):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            info=lab.resource('edge',timeout=2)
            identity=lab.api('edge','system/identity',timeout=2)
            if isinstance(identity,list):identity=identity[0]
            assert identity['name']=='sdwan-container-edge'
            assert info['version'].split()[0]=='7.24.5'
            return
        except (OSError,RuntimeError):time.sleep(1)
    raise RuntimeError('Isolated container CHR did not become ready')

def request(path,data,timeout=2):
    try:lab.api('edge',path,data,'POST',timeout=timeout)
    except (OSError,RuntimeError) as error:
        # Reboot/interactive device-mode may close or hold the HTTP connection.
        if path not in ('system/reboot','system/device-mode/update'):raise

def main():
    wait_ready()
    package=ROOT/'runtime/container-packages/container-7.24.5.npk'
    assert package.is_file()
    entries=lab.api('edge','system/package')
    if not any(x['name']=='container' for x in entries):
        handler=functools.partial(Quiet,directory=str(package.parent))
        server=http.server.ThreadingHTTPServer(('127.0.0.1',48090),handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            lab.api('edge','tool/fetch',{'url':'http://10.77.0.2:48090/'+package.name,
                    'dst-path':package.name,'keep-result':'yes'},'POST')
        finally:server.shutdown();server.server_close();worker.join()
        print('Pinned package downloaded by isolated CHR',flush=True)
        request('system/reboot',{})
        time.sleep(5);wait_ready()
        entries=lab.api('edge','system/package')
    installed=next(x for x in entries if x['name']=='container')
    assert installed['version']=='7.24.5'
    mode=lab.api('edge','system/device-mode')
    if isinstance(mode,list):mode=mode[0]
    if mode.get('container')!='true':
        request('system/device-mode/update',{'container':'yes'})
        time.sleep(3)
        # QMP quit is physical power-off of this VM, not RouterOS soft reboot.
        try:lab.qmp('edge','quit')
        except (OSError,ValueError):
            # QEMU can close QMP before sending the final quit response.
            assert lab.alive('edge') is None
        time.sleep(1)
        subprocess.run(['sg','kvm','-c',shlex.join(lab.node_command('edge','kvm'))],check=True)
        wait_ready()
        mode=lab.api('edge','system/device-mode')
        if isinstance(mode,list):mode=mode[0]
    assert mode['container']=='true', 'Device mode not confirmed by isolated cold boot'
    result={'pass':True,'identity':'sdwan-container-edge','version':'7.24.5',
            'container_package':True,'device_mode_container':True,
            'package_sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
            'production_modified':False,'baseline_fabric_modified':False}
    (ROOT/'runtime/container-package-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
