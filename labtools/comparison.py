"""Prepare and orchestrate a sequential lab comparison through an explicit DUT adapter."""
import argparse,copy,hashlib,importlib.util,json,math,os,statistics,sys
from pathlib import Path
from sdwan_lab.runtime import Lease,Run,atomic_json,install_signals

STAGES=('baseline-before','routeros','container','container-web','baseline-after')
WORKLOADS=[{'id':'tcp-forward','kind':'tcp','direction':'forward','offered_bps':20000000},
 {'id':'tcp-reverse','kind':'tcp','direction':'reverse','offered_bps':20000000},
 {'id':'tcp-bidir','kind':'tcp','direction':'bidir','offered_bps':20000000},
 {'id':'udp-small','kind':'udp','direction':'forward','payload_bytes':64,'offered_pps':3000},
 {'id':'udp-large','kind':'udp','direction':'reverse','payload_bytes':1472,'offered_pps':3000},
 {'id':'cps','kind':'cps','rate':1000,'concurrency':32}]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def gate(report):
 if not (report.get('status')=='passed' and report.get('pass') is True and report.get('kind')=='release' and report.get('elapsed_seconds',0)>=172800 and not report.get('failures') and all(report.get('phase_samples',{}).get(x,0)>0 for x in ('native','container'))):
  raise ValueError('Full original48h acceptance and restoration must finish before DUT comparison')

def build_plan(config,bindings,*,warmup=120,seconds=60,repeats=5):
 if type(warmup) is not int or not 120<=warmup<=600 or type(seconds) is not int or not 60<=seconds<=600 or type(repeats) is not int or not 3<=repeats<=5:raise ValueError('Require warmup120..600, seconds60..600, repeats3..5')
 workloads=copy.deepcopy(WORKLOADS)
 # CPS source-port budgets include warmup. Use a distinct address/port pool for each run.
 for w in workloads:
  if w['kind']=='cps':w['requires_source_pool']=True
 return {'schema_version':1,'stages':list(STAGES),'workloads':workloads,'warmup_seconds':warmup,'seconds':seconds,'repeats':repeats,
  'bindings':bindings,'topology_config_sha256':hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest(),
  'criteria':{'generator_cpu_p95_max_percent':80,'host_steal_p95_max_percent':2,'baseline_variation_max_percent':5},
  'web_load':{'poll_seconds':5,'concurrent_readers':1,'token_in_manifest':False},
  'switching':{'actions':['blackhole-primary','restore-primary'],'flows':['affected','pinned-other-wan'],'protocols':['udp','tcp'],'interval_ms':20,'observer':'sdwan_lab.continuity'},
  'capacity_validated':False,'scope':'virtual lab comparison; no automatic hardware recommendation',
  'imix_note':'L2 calibration EtherType88b5 is not routed through DUT. Routed IP IMIX needs a separate validated adapter.'}

def validate_measurement(record,mode):
 if record.get('observed_mode')!=mode or record.get('pass') is not True:raise ValueError('Failed measurement or wrong observed backend')
 fields=['receiver_rate','dut_cpu_mean_percent','dut_cpu_p95_percent','dut_memory_free_min_bytes','generator_cpu_p95_max_percent','host_steal_p95_percent','container_memory_peak_bytes']
 for key in fields:
  value=record.get(key)
  if type(value) not in (int,float) or not math.isfinite(value) or value<0:raise ValueError('Missing/invalid measurement '+key)
 for key in ['dut_cpu_mean_percent','dut_cpu_p95_percent','generator_cpu_p95_max_percent','host_steal_p95_percent']:
  if record[key]>100:raise ValueError('Invalid CPU percentage')
 if record['receiver_rate']<=0:raise ValueError('Zero receiver rate is not a valid comparison')
 if record.get('write_sectors_delta') is not None and (type(record['write_sectors_delta']) is not int or record['write_sectors_delta']<0):raise ValueError('Invalid write counter delta')
 return record

def compare_baselines(rows,limit):
 checks=[]
 for case in sorted({r['case'] for r in rows}):
  before=[r['metrics']['receiver_rate'] for r in rows if r['case']==case and r['stage']=='baseline-before']
  after=[r['metrics']['receiver_rate'] for r in rows if r['case']==case and r['stage']=='baseline-after']
  if not before or not after:raise ValueError('Missing before/after control')
  b=statistics.median(before);c=statistics.median(after);variation=abs(c-b)/max(b,c)*100 if max(b,c)>0 else 0
  checks.append({'case':case,'before_median':b,'after_median':c,'variation_percent':variation,'pass':variation<=limit})
 return checks

def validate_plan(plan):
 if plan.get('stages')!=list(STAGES):raise ValueError('Fixed baseline-before/RSC/container/web/baseline-after sequence required')
 if plan.get('schema_version')!=1 or not plan.get('workloads'):raise ValueError('Invalid comparison plan')
 if len({w['id'] for w in plan['workloads']})!=len(plan['workloads']):raise ValueError('Duplicate workload id')
 if any(w.get('kind') not in ('tcp','udp','cps') for w in plan['workloads']):raise ValueError('Unsupported DUT workload; L2 IMIX is calibration only')
 if type(plan.get('repeats')) is not int or not 3<=plan['repeats']<=5:raise ValueError('Require 3..5 repeats')
 if plan.get('warmup_seconds',0)<120 or plan.get('seconds',0)<60:raise ValueError('Unstable measurement window')

def execute(plan,adapter,run,*,recover=False):
 report={'pass':False,'capacity_validated':False,'status':'preflight','runs':[],'switching':[],'plan_sha256':hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()};snapshot=None;error=None
 try:
  validate_plan(plan)
  if recover:
   snapshot=json.loads((run.folder/'adapter-snapshot.json').read_text())
  else:
   ready=adapter.preflight(plan,run)
   if ready.get('pass') is not True or ready.get('scope')!='owned-isolated-lab' or ready.get('source_matches_plan') is not True or ready.get('generator_calibration_pass') is not True or ready.get('cps_source_pool_validated') is not True:raise ValueError('DUT adapter preflight failed or ownership not confirmed')
   report['adapter_preflight']=ready
   snapshot=adapter.snapshot(plan,run)
   if not isinstance(snapshot,dict):raise ValueError('Adapter snapshot must be a durable JSON object')
   atomic_json(run.folder/'adapter-snapshot.json',snapshot)
   for mode in plan['stages']:
    report.update(status='configuring',stage=mode);atomic_json(run.folder/'report.json',report)
    adapter.set_mode(mode,plan,run,snapshot)
    report['status']='measuring';atomic_json(run.folder/'report.json',report)
    for case in plan['workloads']:
     for repeat in range(plan['repeats']):
      metrics=validate_measurement(adapter.measure(mode,case,repeat,plan,run,snapshot),mode)
      if metrics.get('rate_unit')!={'tcp':'bps','udp':'pps','cps':'cps'}[case['kind']]:raise ValueError('Wrong rate unit for workload')
      if metrics['generator_cpu_p95_max_percent']>plan['criteria']['generator_cpu_p95_max_percent'] or metrics['host_steal_p95_percent']>plan['criteria']['host_steal_p95_max_percent']:raise ValueError('Generator/host reserve invalidates comparison')
      report['runs'].append({'stage':mode,'case':case['id'],'repeat':repeat,'metrics':metrics});atomic_json(run.folder/'report.json',report)
    if mode not in ('baseline-before','baseline-after'):
     switching=adapter.switching(mode,plan,run,snapshot)
     if switching.get('pass') is not True or switching.get('pinned_flow_preserved') is not True or switching.get('observer')!='sdwan_lab.continuity':raise ValueError('Switching/independent flow acceptance failed')
     report['switching'].append({'stage':mode,'result':switching});atomic_json(run.folder/'report.json',report)
   report['baseline_checks']=compare_baselines(report['runs'],plan['criteria']['baseline_variation_max_percent'])
   report['pass']=all(c['pass'] for c in report['baseline_checks']);report['status']='completed' if report['pass'] else 'invalid_baseline_drift'
 except BaseException as exc:error=type(exc).__name__+': '+str(exc);report.update(status='failed',error=error)
 finally:
  restored=True
  if snapshot is not None:
   try:
    restoration=adapter.restore(plan,run,snapshot);report['restoration']=restoration;restored=restoration.get('pass') is True and restoration.get('verified') is True
   except BaseException as exc:restored=False;report['restore_error']=str(exc)
  cleaned=run.cleanup()
  if not restored:run.data['state']='cleanup_failed';run.data['cleanup_errors'].append('DUT adapter restore not verified');run.save()
  report['cleanup_pass']=cleaned and restored;report['pass'] &= report['cleanup_pass']
  if recover:report.update(recovery_pass=report['cleanup_pass'],original_report_preserved=True);atomic_json(run.folder/'comparison-recovery.json',report)
  else:atomic_json(run.folder/'report.json',report)
 return report

def prepare(source,config,artifacts,output,lan_interface,lan_source):
 sys.path.insert(0,str(source));from sdwan.config import validate
 from sdwan.container_config import settings
 cfg=validate(json.loads(config.read_text()));catalog=json.loads((source/'config/platform-benchmarks.json').read_text());build=json.loads((artifacts/'build-report.json').read_text())
 from tools.container_checks import source_digest
 if source_digest(source)!=catalog['controller_source_sha256']:raise ValueError('Current container source differs from covered artifact source')
 bindings={'routeros':'7.24.5','controller_source_sha256':catalog['controller_source_sha256'],'native_sources':{p.name:sha(p) for p in sorted((source/'native').glob('*.rsc'))},'images':{}}
 for profile in ('base','web'):
  row=next(r for r in build if r['architecture']=='amd64' and r['profile']==profile)
  archive=artifacts/('sdwan-controller-'+('web-' if profile=='web' else '')+'amd64.tar.gz')
  if sha(archive)!=row['gzip_sha256'] or row['unit_coverage_source_sha256']!=bindings['controller_source_sha256']:raise ValueError('Container artifact/coverage source mismatch')
  bindings['images'][profile]={'file':archive.name,'sha256':sha(archive),'image_config_sha256':row['image_config_sha256']}
 output.mkdir(parents=True,exist_ok=False)
 for mode in ('routeros','container','container-web'):
  variant=copy.deepcopy(cfg);variant.pop('controller_backend',None);variant.pop('container',None)
  if mode!='routeros':
   variant['controller_backend']='container';variant['container']=settings(variant);variant['container']['image_file']=bindings['images']['web' if mode=='container-web' else 'base']['file']
   subnet=variant['container']['subnet']
   if subnet not in variant['local_networks']:variant['local_networks'].append(subnet)
   if mode=='container-web':variant['container']['telemetry']={'enabled':True,'allowed_sources':[lan_source],'allowed_interfaces':[lan_interface]}
  validate(variant);atomic_json(output/(mode+'.json'),variant)
 plan=build_plan(cfg,bindings);plan['variant_sha256']={mode:sha(output/(mode+'.json')) for mode in ('routeros','container','container-web')};atomic_json(output/'comparison-plan.json',plan);return plan

def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 q=sub.add_parser('prepare');q.add_argument('--source',type=Path,required=True);q.add_argument('--config',type=Path,required=True);q.add_argument('--artifacts',type=Path,required=True);q.add_argument('--output',type=Path,required=True);q.add_argument('--lan-interface',required=True);q.add_argument('--lan-source',required=True)
 q=sub.add_parser('run');q.add_argument('--plan',type=Path,required=True);q.add_argument('--adapter',type=Path,required=True);q.add_argument('--soak-report',type=Path,required=True);q.add_argument('--workspace',type=Path,required=True);q.add_argument('--run-id',required=True);q.add_argument('--recover',action='store_true')
 args=p.parse_args()
 if args.command=='prepare':
  plan=prepare(args.source.resolve(),args.config.resolve(),args.artifacts.resolve(),args.output,args.lan_interface,args.lan_source);print(json.dumps({'prepared':True,'stages':plan['stages'],'measurements':len(plan['stages'])*len(plan['workloads'])*plan['repeats'],'capacity_validated':False}));return 0
 if not args.recover:gate(json.loads(args.soak_report.read_text()))
 spec=importlib.util.spec_from_file_location('comparison_adapter',args.adapter.resolve());adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
 plan=json.loads(args.plan.read_text());validate_plan(plan)
 for mode,digest in plan['variant_sha256'].items():
  if sha(args.plan.parent/(mode+'.json'))!=digest:raise ValueError('Mode configuration changed after preparation')
 install_signals()
 with Lease(args.workspace) as lease:
  run=Run(lease,args.run_id,{'adapter_sha256':sha(args.adapter),'plan_sha256':sha(args.plan)},recover=args.recover)
  if run.data['config']!={'adapter_sha256':sha(args.adapter),'plan_sha256':sha(args.plan)}:raise ValueError('Recovery requires exact adapter and plan')
  result=execute(plan,adapter,run,recover=args.recover);print(json.dumps({k:result[k] for k in ('pass','status','cleanup_pass')}));return 0 if result.get('recovery_pass',result['pass']) else 1

if __name__=='__main__':raise SystemExit(main())
