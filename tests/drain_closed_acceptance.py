#!/usr/bin/env python3
"""CHR ONLY: deliberately close admission on a single-WAN public test hub."""
import argparse
import contextlib
import copy
import fcntl
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from overlay_lab import Lab
from sdwan.router import Router

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',type=Path,required=True);args=p.parse_args();lab=Lab(args.lab_root)
    lock=(lab.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    router=Router(lab.root,'api://127.0.0.1:55728',credentials_data=json.loads((lab.run/'credentials.json').read_text())['hub'])
    spec=importlib.util.spec_from_file_location('closed_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli);report={'checks':[],'pass':False}
    assert router.call('system/identity')['name']=='sdwan-overlay-hub';before=json.loads(router.read_file('sdwan-active.json'))
    def apply(cfg):
        with (lab.run/'closed-drain-deploy.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(router,cfg,'sdwan-overlay-hub')
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    try:
        cfg=copy.deepcopy(before);cfg['revision']='single-wan-prepare';cfg['wans'][0]['admin_state']='enabled';apply(cfg);assert router.status()['default_admission_closed'] is False
        cfg['revision']='single-wan-drain';cfg['wans'][0].update(admin_state='drain',drain_timeout_seconds=0);apply(cfg);s=router.status()
        assert s['selected']['default']=='none' and s['default_admission_closed'] is True and s['maintenance']['wan1']['effective']=='drain'
        assert s['states']['default/wan1']['state']=='healthy';time.sleep(3);assert router.status()['uptime_seconds']>s['uptime_seconds']
        record('explicit single-WAN drain commits through a fresh management session while default admission is closed and probes stay healthy')
        cfg['revision']='single-wan-down';cfg['wans'][0]['admin_state']='down';apply(cfg);s=router.status();assert s['selected']['default']=='none' and s['default_admission_closed'] is True
        record('emergency down can intentionally close the final default WAN without watchdog undoing the requested state')
        cfg['revision']='single-wan-enabled';cfg['wans'][0]['admin_state']='enabled';apply(cfg);s=router.status();assert s['selected']['default']=='wan1' and s['default_admission_closed'] is False
        record('enabling the WAN restores default admission and clears the explicit-closure evidence');report['pass']=True
    finally:
        try:apply(before)
        finally:router.close();lock.close();(lab.run/'closed-drain-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
