"""Summarize completed benchmark observations without turning them into capacity claims."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean,median


def rates(end):
    keys=('sum_sent','sum_received','sum_sent_bidir_reverse','sum_received_bidir_reverse','sum')
    return {key:{field:row[field] for field in ('bytes','seconds','bits_per_second','retransmits','jitter_ms','lost_packets','packets','lost_percent') if field in row}
            for key in keys if isinstance((row:=end.get(key)),dict)}


def observations(run):
    samples=run.get('router_samples',[])
    resources=[r['resource'] for r in samples if isinstance(r.get('resource'),dict)]
    cpu=[int(r['cpu-load']) for r in resources if 'cpu-load' in r]
    free=[int(r['free-memory']) for r in resources if 'free-memory' in r]
    writes=[int(r['write-sect-total']) for r in resources if 'write-sect-total' in r]
    quality={};errors=[];selected={};ticks=[];container_memory=[]
    for row in samples:
        state=row.get('sdwan',{})
        if state.get('error'):errors.append(state['error'])
        if 'uptime_seconds' in state:ticks.append(state['uptime_seconds'])
        for key,value in state.get('states',{}).items():
            group=quality.setdefault(key,{})
            verdict=value.get('state','unknown');group[verdict]=group.get(verdict,0)+1
        for key,value in state.get('selected',{}).items():
            group=selected.setdefault(key,{});group[value]=group.get(value,0)+1
        for item in row.get('container',[]):
            if item.get('name')=='sdwan-container-controller' and 'memory-current' in item:container_memory.append(int(item['memory-current']))
    end=run.get('iperf',{}).get('end',{})
    return {'mode':run['mode'],'label':run['label'],'measurement_complete':run.get('measurement_complete',False),
      'exit_status':run.get('exit_status'),'iperf_error':run.get('iperf',{}).get('error'),
      'rates':rates(end),'endpoint_cpu_percent':end.get('cpu_utilization_percent'),
      'router_cpu_mean_percent':mean(cpu) if cpu else None,'router_cpu_peak_percent':max(cpu) if cpu else None,
      'router_free_memory_min_bytes':min(free) if free else None,
      'disk_sectors_delta':writes[-1]-writes[0] if len(writes)>1 else None,
      'container_cgroup_peak_bytes':max(container_memory) if container_memory else None,
      'controller_tick_first':ticks[0] if ticks else None,'controller_tick_last':ticks[-1] if ticks else None,
      'controller_errors':sorted(set(errors)),'quality_sample_counts':quality,'selection_sample_counts':selected,
      'telemetry_errors':run.get('sampler_errors',[])}


def summarize(report,sha256):
    runs=[observations(r) for r in report.get('runs',[])]
    full=report.get('seconds',0)>=10 and report.get('repeats',0)>=2
    modes={mode:sum(r['mode']==mode for r in runs) for mode in ('baseline-before','native','container','baseline-after')}
    expected=13*report.get('repeats',0)+1
    labels=['tcp-forward','tcp-reverse','tcp-bidir','tcp-parallel4']+[f'udp-{length}-{rate}' for length in (64,512,1472) for rate in ('5M','20M','50M')]
    wanted={label+'-'+str(repeat+1) for repeat in range(report.get('repeats',0)) for label in labels}|{'strict-wan2-tcp'}
    matrix_complete=all(count==expected and {r['label'] for r in runs if r['mode']==mode}==wanted for mode,count in modes.items())
    direct_complete=all({r['label'] for r in runs if r['mode']==mode}=={'endpoint-headroom-forward','endpoint-headroom-reverse'} for mode in ('direct','direct-after'))
    faults=report.get('failover_load',[])
    faults_complete=len(faults)==2 and {r.get('backend') for r in faults}=={'native','container'} and all(r.get('pass') is True for r in faults)
    complete=bool(report.get('pass') and report.get('cleanup',{}).get('pass') and full and matrix_complete and direct_complete and faults_complete and all(r['measurement_complete'] for r in runs))
    grouped={}
    for row in runs:
        label=row['label'].rsplit('-',1)
        label=label[0] if len(label)==2 and label[1].isdigit() else row['label']
        group=grouped.setdefault(row['mode']+'/'+label,[]);group.append(row)
    medians={}
    for key,group in grouped.items():
        received=[r['rates'].get('sum_received',r['rates'].get('sum',{})).get('bits_per_second') for r in group]
        received=[value for value in received if value is not None]
        cpu=[r['router_cpu_mean_percent'] for r in group if r['router_cpu_mean_percent'] is not None]
        medians[key]={'count':len(group),'received_mbit_s_median':median(received)/1e6 if received else None,'router_cpu_mean_percent_median':median(cpu) if cpu else None}
    return {'comparison_complete':complete,'source_report_sha256':sha256,'run_id':report.get('run_id'),
      'environment':report.get('environment'),'matrix_run_counts':modes,'expected_per_mode':expected,
      'fault_tests_complete':faults_complete,'observations':runs,'medians':medians,
      'limits':['Rates and UDP lengths describe iperf application payload, not Ethernet wire rate.',
                'DUT, generator and hypervisor limits are different; direct headroom does not prove a physical router capacity.',
                'A complete matrix may contain packet loss or SLA degradation under offered overload; inspect every observation.',
                'Disk counters include delayed RouterOS configuration commits; short runs alone do not establish steady flash wear.',
                'Container cgroup memory is not process RSS. These base-image runs do not expose RSS.',
                'CPS and physical ARM/ARM64 performance are unmeasured.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('report',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    data=args.report.read_bytes();result=summarize(json.loads(data),hashlib.sha256(data).hexdigest())
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('comparison_complete','matrix_run_counts','fault_tests_complete')}))


if __name__=='__main__':main()
