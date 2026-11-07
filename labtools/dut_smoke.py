"""Short functional DUT adapter checks, explicitly not the gated capacity matrix."""
import argparse,copy,json
from pathlib import Path
from sdwan_lab.dut_adapter import Adapter,source_bindings
from sdwan_lab.runtime import Lease,Run,atomic_json,install_signals


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--plan',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--seconds',type=int,default=5);p.add_argument('--skip-switching',action='store_true');a=p.parse_args()
    if not 2<=a.seconds<=10:raise ValueError('Functional smoke uses only2..10 seconds, never the full comparison')
    install_signals();plan=json.loads(a.plan.read_text());adapter=Adapter(a.config,a.plan);report={'pass':False,'capacity_validated':False,'scope':'short disposable DUT adapter functionality, not full comparison acceptance','runs':[],'switching':[]};snapshot=None
    with Lease(a.workspace) as lease:
        run=Run(lease,a.run_id,{'config_sha256':__import__('hashlib').sha256(a.config.read_bytes()).hexdigest()})
        try:
            adapter.preflight(plan,run);snapshot=adapter.snapshot(plan,run);short=copy.deepcopy(plan);short['warmup_seconds']=2;short['seconds']=a.seconds
            for mode in plan['stages']:
                report['stage']=mode;atomic_json(run.folder/'smoke.json',report);adapter.set_mode(mode,plan,run,snapshot)
                for case in plan['workloads']:
                    metrics=adapter.measure(mode,case,0,short,run,snapshot);report['runs'].append({'mode':mode,'case':case['id'],'metrics':metrics});atomic_json(run.folder/'smoke.json',report)
                if not a.skip_switching and mode not in ('baseline-before','baseline-after'):report['switching'].append({'mode':mode,'result':adapter.switching(mode,plan,run,snapshot)})
            report['pass']=True
        except BaseException as error:report['error']=type(error).__name__+': '+str(error)
        finally:
            if snapshot is not None:
                try:report['restore']=adapter.restore(plan,run,snapshot)
                except BaseException as error:report['restore']={'pass':False,'error':str(error)}
            failed=run.folder/'snapshot-failure-restoration.json'
            if snapshot is None and failed.exists():report['restore']=json.loads(failed.read_text())
            report['cleanup_pass']=run.cleanup() and (report.get('restore',{}).get('verified') is True or snapshot is None and not failed.exists());report['pass'] &=report['cleanup_pass'];atomic_json(run.folder/'smoke.json',report)
    print(json.dumps({key:report.get(key) for key in ['pass','stage','error','cleanup_pass']}));return 0 if report['pass'] else 1

if __name__=='__main__':raise SystemExit(main())
