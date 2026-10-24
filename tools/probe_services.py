#!/usr/bin/env python3
"""Lab-only HTTP endpoints behind ISP forwarding; never makes routing decisions."""
import argparse
import http.server
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import urllib.request

ROOT=Path(__file__).resolve().parents[1]; RUN=ROOT/'runtime'; STATE=RUN/'probe-services.json'
PORTS={'a':28081,'b':28082,'c':28083}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        state=json.loads(STATE.read_text()) if STATE.exists() else {}
        name=next(k for k,v in PORTS.items() if v==self.server.server_port)
        ok=state.get(name,True)
        self.send_response(200 if ok else 503);self.send_header('Content-Type','text/plain');self.end_headers();self.wfile.write(b'healthy\n' if ok else b'failed\n')
    def log_message(self,*args):pass


def running():
    try:
        pid=int((RUN/'probe-services.pid').read_text())
        cmd=Path(f'/proc/{pid}/cmdline').read_bytes()
        return pid if b'probe_services.py' in cmd and b' serve' not in cmd and b'serve' in cmd else None
    except (OSError,ValueError):return None


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['start','stop','serve','status','fail','heal']);p.add_argument('endpoint',choices=list(PORTS),nargs='?');a=p.parse_args()
    RUN.mkdir(exist_ok=True)
    if a.command=='serve':
        (RUN/'probe-services.pid').write_text(str(os.getpid()))
        for port in PORTS.values():
            server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
        threading.Event().wait()
    elif a.command=='start':
        if not running():
            with (RUN/'probe-services.log').open('ab') as log:subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve'],stdout=log,stderr=log,start_new_session=True)
        print('Lab probe endpoints starting: 28081, 28082, 28083')
    elif a.command=='stop':
        pid=running()
        if pid:os.kill(pid,signal.SIGTERM)
    elif a.command in ('fail','heal'):
        if a.command=='fail' and not a.endpoint:p.error('fail requires an endpoint')
        state=json.loads(STATE.read_text()) if STATE.exists() else {}
        for n in ([a.endpoint] if a.endpoint else PORTS):state[n]=a.command=='heal'
        tmp=STATE.with_suffix('.tmp');tmp.write_text(json.dumps(state));tmp.replace(STATE)
    else:
        for name,port in PORTS.items():
            try:
                op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with op.open(f'http://127.0.0.1:{port}',timeout=2) as r: print(name,r.status)
            except OSError as e:print(name,str(e))

if __name__=='__main__':main()
