#!/usr/bin/env python3
"""Measure actual CHR container resources under the existing 3-WAN probe load."""
import json
import time
from statistics import median
from container_support import Lab,ROOT

def main():
    env=Lab();r=env.router;path='sdwan-container/config/controller.json'
    original=r.read_file(path);settings=json.loads(original);samples=[];resources=[]
    try:
        env.stop()
        baseline=[]
        for _ in range(3):
            row=r.call('system/resource');row=row[0] if isinstance(row,list) else row
            baseline.append({k:row.get(k) for k in ('cpu-load','free-memory')});time.sleep(1)
        settings['metrics_every_seconds']=2;r.upload(path,json.dumps(settings))
        row=env.container();env.lab.api('edge','container/'+row['.id'],{'logging':'yes'},'PATCH')
        old={x['.id'] for x in r.call('log')};env.start();start=time.monotonic()
        for _ in range(13):
            row=env.container();system=r.call('system/resource');system=system[0] if isinstance(system,list) else system
            samples.append({'elapsed_seconds':round(time.monotonic()-start,2),'container_memory_current':int(row.get('memory-current',0)),
                            'container_cpu_usage':row.get('cpu-usage'),'router_cpu_load':system.get('cpu-load'),'router_free_memory':system.get('free-memory')})
            time.sleep(5)
        for entry in r.call('log'):
            if entry['.id'] in old:continue
            text=entry.get('message','')
            if not text.startswith('sdwan-container-controller:'):continue
            offset=text.find('{')
            if offset<0:continue
            try:data=json.loads(text[offset:])
            except json.JSONDecodeError:continue
            if 'resources' in data:resources.append(dict(data['resources'],router_log_time=entry.get('time')))
        assert len(resources)>=20 and all(x['rss_bytes']>0 for x in resources)
        assert all(x['container_memory_current']>0 for x in samples)
        report={'pass':True,'platform':'RouterOS7.24.5 CHR amd64','base':'scratch','scenario':'three WANs, two SLA profiles, four policies; existing Netwatch probes running',
                'duration_seconds':round(time.monotonic()-start,2),'resource_samples':len(resources),
                'process_rss_min_bytes':min(x['rss_bytes'] for x in resources),'process_rss_max_bytes':max(x['rss_bytes'] for x in resources),
                'process_cpu_ticks_delta':resources[-1]['cpu_ticks']-resources[0]['cpu_ticks'],
                'container_memory_current_min_bytes':min(x['container_memory_current'] for x in samples),
                'container_memory_current_max_bytes':max(x['container_memory_current'] for x in samples),
                'baseline_router_samples':baseline,'active_samples':samples,'process_samples':resources,
                'limits':'Short CHR measurement; CPU counters are rounded; RSS/cgroup counters have different accounting and are not total router overhead; ARM hardware and long load/soak not measured'}
        (ROOT/'runtime/container-resources-validation.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:report[k] for k in ('pass','duration_seconds','process_rss_min_bytes','process_rss_max_bytes','process_cpu_ticks_delta','container_memory_current_max_bytes')}))
    finally:
        env.stop();r.upload(path,original)
        row=env.container();env.lab.api('edge','container/'+row['.id'],{'logging':'no'},'PATCH')
        env.start();r.close()

if __name__=='__main__':main()
