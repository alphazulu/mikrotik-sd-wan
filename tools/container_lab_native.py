#!/usr/bin/env python3
"""Install existing native SD-WAN on the isolated container fabric only."""
from pathlib import Path
import importlib.util
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tools'))
import container_lab
from sdwan.router import Router
from sdwan.config import load,validate

def main():
    lab=container_lab.load()
    credentials=json.loads((lab.RUN/'credentials.json').read_text())['edge']
    router=Router(ROOT,'api://127.0.0.1:38728',credentials_data=credentials)
    try:
        identity=router.call('system/identity')
        if isinstance(identity,list):identity=identity[0]
        assert identity['name']=='sdwan-container-edge'
        cfg=load(ROOT/'config/sdwan.json')
        cfg['revision']='container-lab-v1'
        cfg['local_networks'].append('172.31.255.0/30')
        for wan in cfg['wans']:
            for probe in wan['probes']:probe['port']+=20000
        validate(cfg)
        (lab.ROOT.parent/'sdwan.json').write_text(json.dumps(cfg,indent=2)+'\n')
        spec=importlib.util.spec_from_file_location('sdwan_deploy',ROOT/'sdwan.py')
        deploy=importlib.util.module_from_spec(spec);spec.loader.exec_module(deploy)
        deploy.apply(router,cfg,'sdwan-container-edge')
        print(json.dumps({'native_installed':True,'identity':'sdwan-container-edge','revision':cfg['revision']}))
    finally:router.close()

if __name__=='__main__':main()
