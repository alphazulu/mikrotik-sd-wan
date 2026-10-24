#!/usr/bin/env python3
"""Live read-only discovery and native installation/rollback on the lab edge."""
import importlib.util
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sdwan.router import Router
from sdwan.discovery import discover,generate
from sdwan.config import load
spec=importlib.util.spec_from_file_location('deploy_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    rest=Router(ROOT);api=Router(ROOT,'api://127.0.0.1:18728')
    report={'checks':[]};temp_route=None;temp_filter=None
    backup_file=next(f for f in rest.call('file') if f['name']=='sdwan-backup.json')
    original_backup=rest.read_file('sdwan-backup.json')
    def record(name,detail=None):report['checks'].append({'check':name,'pass':True,'detail':detail});print('PASS '+name,flush=True)
    try:
        first=discover(rest);second=discover(api)
        relevant=lambda inv:[(c['interface'],c['addresses'],c['gateways'],c['suggested']) for c in inv['candidates']]
        assert relevant(first)==relevant(second);record('REST and native API inventory agree')
        choices=[{k:c[k] for k in ('interface','address','gateway','priority')} for c in second['candidates'] if c['suggested']]
        before=next(f for f in api.call('file/print',{'.proplist':'.id,name'},'POST') if f['name']=='sdwan-active.json')
        original=api.read_file('sdwan-active.json')
        cfg=generate(second,choices);assert len(cfg['wans'])==3
        assert api.read_file('sdwan-active.json')==original
        record('select WANs and generate without changing router configuration')
        # Unused fallback and nonmatching FastTrack rule test generic adoption safely.
        temp_route=rest.call('ip/route',{'dst-address':'0.0.0.0/0','gateway':'172.20.3.1','distance':'250'},'PUT')['.id']
        temp_filter=rest.call('ip/firewall/filter',{'chain':'forward','action':'fasttrack-connection','src-address':'198.18.255.255/32','comment':'wizard-acceptance-only'},'PUT')['.id']
        inventory=discover(api);cfg=generate(inventory,choices)
        assert temp_route in [x['.id'] for x in cfg['takeover_routes']]
        assert temp_filter in [x['.id'] for x in cfg['disable_fasttrack']]
        cli.apply(api,cfg,inventory['identity']['name'])
        assert rest.call('ip/route/'+temp_route).get('disabled')=='true'
        assert rest.call('ip/firewall/filter/'+temp_filter).get('disabled')=='true'
        record('native API installs generated files; native installer adopts uncommented route and FastTrack')
        cli.rollback(api,inventory['identity']['name'])
        assert rest.call('ip/route/'+temp_route).get('disabled','false')=='false'
        assert rest.call('ip/firewall/filter/'+temp_filter).get('disabled','false')=='false'
        record('native rollback restores adopted route and FastTrack flags')
    except Exception as e:
        report['checks'].append({'check':'wizard acceptance interrupted','pass':False,'detail':str(e)});raise
    finally:
        if temp_route:rest.call('ip/route/'+temp_route,method='DELETE')
        if temp_filter:rest.call('ip/firewall/filter/'+temp_filter,method='DELETE')
        rest.call('file/'+backup_file['.id'],{'contents':original_backup},'PATCH')
        try:
            cli.apply(api,load(ROOT/'config/sdwan.json'),'sdwan-edge')
            end=time.monotonic()+35
            while time.monotonic()<end:
                s=api.status()
                if s.get('selected',{}).get('client101')=='wan1' and s.get('selected',{}).get('client102')=='wan2':break
                time.sleep(1)
            else:raise AssertionError('Original SD-WAN did not recover')
        finally:
            (ROOT/'runtime/wizard-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');rest.close();api.close()

if __name__=='__main__':main()
