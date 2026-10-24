"""Helpers scoped to the independent container CHR fabric."""
from pathlib import Path
import json
import importlib.util
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
import container_lab
from sdwan.router import Router

class Lab:
    def __init__(self):
        self.lab=container_lab.load()
        self.creds=json.loads((self.lab.RUN/'credentials.json').read_text())['edge']
        self.router=Router(ROOT,'api://127.0.0.1:38728',credentials_data=self.creds)
        identity=self.router.call('system/identity')
        if isinstance(identity,list):identity=identity[0]
        assert identity['name']=='sdwan-container-edge'
        self.resources=[]
    def status(self):
        value=self.router.status()
        assert not value.get('error'),value
        return value
    def wait(self,predicate,timeout=55):
        end=time.monotonic()+timeout
        value={}
        while time.monotonic()<end:
            value=self.status()
            if predicate(value):return value
            time.sleep(.25)
        raise AssertionError('Container condition timed out: '+json.dumps(value))
    def container(self):
        rows=self.lab.api('edge','container')
        assert len(rows)==1 and rows[0]['name']=='sdwan-container-controller'
        return rows[0]
    def command(self,name,**args):
        row=self.container()
        # kill uses .id in the API, whereas start/stop use numbers.
        payload=dict(args,**{'.id':row['.id']}) if name=='kill' else dict(numbers=row['.id'],**args)
        return self.lab.api('edge','container/'+name,payload,'POST')
    def start(self):
        if self.container().get('running')!='true':self.command('start')
        return self.wait(lambda s:s.get('container',{}).get('active') is True)
    def stop(self):
        if self.container().get('running')=='true':self.command('stop')
        end=time.monotonic()+20
        while self.container().get('stopped')!='true':
            if time.monotonic()>end:raise AssertionError('Container did not stop')
            time.sleep(.25)
        return self.wait(lambda s:not s.get('container',{}).get('active'),timeout=30)
    def add(self,node,menu,data):
        data=dict(data)
        data.setdefault('comment','sdwan-container-test')
        row=self.lab.api(node,menu,data,'PUT')
        self.resources.append((node,menu,row['.id']))
        return row['.id']
    def apply(self,config):
        from sdwan.container_backend import controller_source
        from sdwan.deployment import start,wait
        spec=importlib.util.spec_from_file_location('container_test_deploy',ROOT/'sdwan.py')
        deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)
        deploy.preflight(self.router,config,'sdwan-container-edge')
        package=deploy.bundle(config,ROOT/'runtime/container-lab/test-package')
        (package/'sdwan-controller.rsc').write_text(controller_source(ROOT,config))
        token=start(self.router,package,'sdwan-container-edge',revision=config['revision'],default_policy='default')
        return wait(self.router,token,'sdwan-container-edge')
    def close(self):
        self.lab.proxy_request({'reset':True})
        try:
            if self.container().get('running')=='true':
                try:self.command('kill',signal='18-SIGCONT')
                except RuntimeError:pass
            self.stop()
        finally:
            for node,menu,identifier in reversed(self.resources):
                if any(row['.id']==identifier for row in self.lab.api(node,menu)):
                    self.lab.api(node,menu+'/'+identifier,method='DELETE')
            self.router.close()

