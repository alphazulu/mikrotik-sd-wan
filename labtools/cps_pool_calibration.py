"""Long CPS calibration in owned namespaces; no RouterOS/DUT configuration."""
import argparse,hashlib,json,math,statistics,sys,time
from dataclasses import asdict
from pathlib import Path
from sdwan_lab.bench import Network,Sampler,wait_until,wait_child
from sdwan_lab.cps_pool import build,reserve,validate_result
from sdwan_lab.runtime import Lease,Run,atomic_json,install_signals


def calibration(run,*,rate=1000,warmup=120,seconds=60,repeats=3,delay_ms=5):
    report={'schema_version':1,'pass':False,'status':'preparing','scope':'owned namespace generator calibration, no DUT capacity claim','runs':[],'controller_modified':False,'system_TIME_WAIT_settings_changed':False}
    path=run.folder/'report.json'
    def save():atomic_json(path,report)
    try:
        if not 1<=repeats<=5 or not 0<=delay_ms<=100:raise ValueError('Invalid repetitions or delay')
        binary=build(run);report['build']=json.loads((run.folder/'cps-pool-build.json').read_text())
        net=Network(run,'198.18.248.0/30');sources=tuple('198.19.64.'+str(i) for i in range(1,129))
        for address in sources:net.call(0,['ip','addr','add',address+'/32','dev','eth0'])
        net.call(1,['ip','route','add','198.19.64.0/24','via',net.ips[0]])
        net.delay(delay_ms)
        tcp_keys=['net.ipv4.tcp_tw_reuse','net.ipv4.ip_local_port_range','net.ipv4.tcp_max_tw_buckets']
        report['tcp_settings_before']=[net.call(i,['sysctl']+tcp_keys).stdout for i in range(2)]
        report['network']={'source_addresses':list(sources),'destinations':net.ips,'delay_ms_per_interface':delay_ms,'offloads':[net.call(i,['ethtool','-k','eth0']).stdout for i in range(2)]}
        report['status']='running';save()
        for repeat in range(repeats):
            spec=reserve(run,sources,rate=rate,warmup=warmup,seconds=seconds,concurrency=32);label='case'+str(repeat)
            report['current_repeat']=repeat;save()
            server=run.spawn(net.argv(1,spec.server_argv(binary,net.ips[1])),label+'-server')
            wait_until(lambda:server.poll() is None and 'ready' in (run.folder/(label+'-server.stdout')).read_text(),5)
            with Sampler() as cpu:
                child=run.spawn(net.argv(0,spec.client_argv(binary,net.ips[1])),label+'-client')
                wait_child(child,warmup+seconds+15);run.stop(server.pid)
            client=json.loads((run.folder/(label+'-client.stdout')).read_text());peer=json.loads((run.folder/(label+'-server.stdout')).read_text().splitlines()[-1]);result=validate_result(client,peer,spec)
            origin=client['origin_monotonic_seconds'];samples=[r for r in cpu.rows if origin+warmup<=r['monotonic']<origin+warmup+seconds]
            if not samples:raise ValueError('No CPU samples in CPS measurement window')
            core_p95=[];steals=[]
            for core in samples[0]['cores']:
                values=sorted(r['cores'][core]['busy'] for r in samples);core_p95.append(values[math.ceil(.95*len(values))-1]);steals.extend(r['cores'][core]['steal'] for r in samples)
            steal=sorted(steals)[math.ceil(.95*len(steals))-1];atomic_json(run.folder/(label+'-cpu.json'),cpu.rows)
            result.update(spec=asdict(spec),generator_cpu_p95_max_percent=max(core_p95),host_steal_p95_percent=steal,raw_client=label+'-client.stdout',raw_server=label+'-server.stdout')
            result['pass'] &= max(core_p95)<=80 and steal<=2;report['runs'].append(result);save()
            if not result['pass']:raise ValueError('Generator/host reserve criterion failed')
        report['tcp_settings_after']=[net.call(i,['sysctl']+tcp_keys).stdout for i in range(2)]
        if report['tcp_settings_after']!=report['tcp_settings_before']:raise ValueError('TCP settings unexpectedly changed')
        values=[r['successful_cps'] for r in report['runs']];variation=(max(values)-min(values))/statistics.median(values)*100
        report.update(variation_percent=variation,status='completed',**{'pass':variation<=5})
    except BaseException as error:report.update(status='failed',error=type(error).__name__+': '+str(error))
    finally:
        report['cleanup_pass']=run.cleanup();report['pass'] &= report['cleanup_pass'];save()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--rate',type=int,default=1000);p.add_argument('--warmup',type=int,default=120);p.add_argument('--seconds',type=int,default=60);p.add_argument('--repeats',type=int,default=3);p.add_argument('--delay-ms',type=int,default=5);a=p.parse_args();install_signals()
    with Lease(a.workspace) as lease:
        run=Run(lease,a.run_id,{'rate':a.rate,'warmup':a.warmup,'seconds':a.seconds,'repeats':a.repeats,'delay_ms':a.delay_ms});result=calibration(run,rate=a.rate,warmup=a.warmup,seconds=a.seconds,repeats=a.repeats,delay_ms=a.delay_ms)
    print(json.dumps({k:result[k] for k in ['pass','status','cleanup_pass']}));return 0 if result['pass'] else 1

if __name__=='__main__':raise SystemExit(main())
