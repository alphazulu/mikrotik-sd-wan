"""Timestamp iperf3 JSON-stream events on the same monotonic clock as samplers."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from .runtime import atomic_json,process_start


def result(events):
    starts=[e['data'] for e in events if e.get('event')=='start'];ends=[e['data'] for e in events if e.get('event')=='end']
    if len(starts)!=1 or len(ends)!=1 or any(e.get('event')=='error' for e in events):raise ValueError('Incomplete/failed iperf3 stream')
    intervals=[]
    for event in events:
        if event.get('event')!='interval':continue
        row=event['data'].get('sum',{})
        if row.get('omitted') is False and isinstance(row.get('end'),(int,float)):
            intervals.append((event,row))
    phase_start=min((row.get('start',0) for _,row in intervals),default=0)
    # The terminal UDP interval can be emitted after the end-of-test control
    # exchange. Align resources to interior reports, not teardown latency.
    clock_intervals=intervals[:-1] if len(intervals)>1 else intervals
    offsets=[event['received_monotonic']-(row['end']-phase_start) for event,row in clock_intervals]
    if not offsets:raise ValueError('No non-omitted iperf intervals')
    origin=statistics.median(offsets);deviation=max(abs(v-origin) for v in offsets)
    if deviation>.2:raise ValueError('iperf interval delivery jitter exceeds sampler resolution')
    return {'start':starts[0],'end':ends[0],'measurement_origin_monotonic':origin,'first_non_omitted_interval_start':phase_start,'measurement_alignment_max_deviation_seconds':deviation,'resource_clock_interval_count':len(clock_intervals),'terminal_interval_excluded_from_clock_fit':len(intervals)>1,'terminal_interval_delivery_delay_seconds':intervals[-1][0]['received_monotonic']-(intervals[-1][1]['end']-phase_start)-origin,'resource_clock':'client CLOCK_MONOTONIC; origin estimated from force-flushed non-omitted interval events'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('argv',nargs=argparse.REMAINDER);a=p.parse_args();argv=a.argv[1:] if a.argv[:1]==['--'] else a.argv
    if not argv:raise ValueError('Missing iperf command')
    child=None;events=[];report={};code=1
    try:
        child=subprocess.Popen(argv,stdout=subprocess.PIPE,text=True)
        atomic_json(a.output.with_suffix('.process.json'),{'pid':child.pid,'start':process_start(child.pid),'group':os.getpgid(child.pid)})
        print('ready '+str(child.pid),flush=True)
        with a.output.with_suffix('.events.jsonl').open('x') as raw:
            for line in child.stdout:
                if len(line)>2*1024*1024:raise ValueError('Oversized iperf event')
                event=json.loads(line);event['received_monotonic']=time.monotonic();events.append(event);raw.write(json.dumps(event,separators=(',',':'))+'\n');raw.flush()
        code=child.wait(timeout=5);report=result(events)
        if code:raise RuntimeError('iperf client exit '+str(code))
    except BaseException as error:report={'error':type(error).__name__+': '+str(error)};code=1
    finally:
        if child is not None:
            if child.poll() is None:
                child.terminate()
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=2)
            child.stdout.close()
        report['exit_code']=code;atomic_json(a.output.with_suffix('.json'),report)
    return code

if __name__=='__main__':raise SystemExit(main())
