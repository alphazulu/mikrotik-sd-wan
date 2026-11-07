"""Helpers for explicitly selected existing CHR labs; never starts another lab."""
import contextlib
import fcntl
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sdwan.router import Router

class NetworkLab:
    def __init__(self,root):
        self.root=Path(root).resolve();self.created=[];self.router=None;self.lock=None
        spec=importlib.util.spec_from_file_location('sdwan_selected_network_lab',self.root/'lab.py');self.lab=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.lab;spec.loader.exec_module(self.lab)
        spec=importlib.util.spec_from_file_location('sdwan_network_cli',ROOT/'sdwan.py');self.cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.cli)
    def __enter__(self):
        self.lock=(self.root/'runtime/network-acceptance.lock').open('w');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.router=Router(self.root,'api://127.0.0.1:18728')
        assert self.router.call('system/identity')['name']=='sdwan-edge'
        self.before=json.loads(self.router.read_file('sdwan-active.json'))
        return self
    def add(self,node,menu,data):
        data=dict(data,comment='sdwan-network-acceptance-only');row=self.lab.api(node,menu,data,'PUT');self.created.append((node,menu,row['.id']));return row['.id']
    def apply(self,cfg):
        from sdwan.config import validate
        validate(cfg)
        with (self.root/'runtime/network-acceptance-deploy.log').open('a') as log,contextlib.redirect_stdout(log):self.cli.apply(self.router,cfg,'sdwan-edge')
    def wait(self,predicate,timeout=50):
        end=time.monotonic()+timeout;last={}
        while time.monotonic()<end:
            last=self.router.status()
            if last.get('error'):raise AssertionError(last['error'])
            if predicate(last):return last
            time.sleep(.25)
        raise AssertionError({'timeout':last})
    def healthy(self):return self.wait(lambda s:bool(s.get('states')) and all(v['state']=='healthy' for v in s['states'].values()))
    def __exit__(self,*error):
        try:
            try:self.lab.proxy_request({'reset':True})
            finally:self.apply(self.before)
        finally:
            for node,menu,id in reversed(self.created):
                try:self.lab.api(node,menu+'/'+id,method='DELETE')
                except (RuntimeError,OSError):pass
            self.router.close();self.lock.close()
