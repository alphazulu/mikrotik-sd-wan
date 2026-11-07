"""Window-aligned, read-only DUT and generator resource observations."""
import math
import os
from pathlib import Path
import socket
import statistics
import threading
import time
from .bench import cpu_snapshot


def percentile(values):
    if not values:raise ValueError('Missing samples')
    values=sorted(values);return values[math.ceil(.95*len(values))-1]


def proc_cpu(pid):
    try:
        fields=Path('/proc',str(pid),'stat').read_text().rpartition(') ')[2].split()
        return {'start':fields[19],'ticks':int(fields[11])+int(fields[12])}
    except (OSError,IndexError):return None


class GeneratorSampler:
    def __init__(self):self.rows=[];self.targets={};self.previous={};self.lock=threading.Lock();self.done=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True);self.errors=[]
    def add(self,pid,label):
        value=proc_cpu(pid)
        if value is None:raise ValueError('Generator process exited before sampling')
        with self.lock:self.targets[label]=(pid,value['start']);self.previous[label]=(time.monotonic(),value['ticks'])
    def loop(self):
        before=cpu_snapshot();ticks=os.sysconf('SC_CLK_TCK')
        try:
            while not self.done.wait(.2):
                stamp=time.monotonic();values={};steal={};after=cpu_snapshot()
                for core in before.keys()&after.keys():
                    delta=[b-a for a,b in zip(before[core],after[core])];total=sum(delta);steal[core]=100*delta[7]/total if total else 0
                before=after
                with self.lock:
                    for label,(pid,start) in self.targets.items():
                        value=proc_cpu(pid)
                        if value is None:continue
                        if value['start']!=start:raise ValueError('Generator PID was reused')
                        previous,used=self.previous[label];values[label]=100*(value['ticks']-used)/(ticks*(stamp-previous));self.previous[label]=(stamp,value['ticks'])
                self.rows.append({'monotonic':stamp,'process_cpu_percent':values,'host_steal_percent':steal})
        except BaseException as error:self.errors.append(type(error).__name__+': '+str(error))
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.done.set();self.thread.join(timeout=2)


class RouterSampler:
    def __init__(self,fixture):self.fixture=fixture;self.rows=[];self.errors=[];self.done=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True);self.router=None
    def loop(self):
        try:
            self.router=self.fixture.connect();self.router.native.sock.settimeout(2)
            while not self.done.is_set():
                resource=self.router.call('system/resource/print',{'.proplist':'cpu-load,free-memory,write-sect-total,uptime'},'POST')[0]
                containers=self.router.call('container/print',{'.proplist':'name,memory-current,running'},'POST')
                self.rows.append({'monotonic':time.monotonic(),'resource':resource,'containers':containers})
                self.done.wait(1)
        except BaseException as error:self.errors.append(type(error).__name__+': '+str(error))
        finally:
            if self.router is not None:self.router.close()
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):
        self.done.set();self.thread.join(timeout=5)
        if self.thread.is_alive():
            try:self.router.native.sock.shutdown(socket.SHUT_RDWR)
            except (OSError,AttributeError):pass
            self.thread.join(timeout=3)
            if self.thread.is_alive():raise RuntimeError('DUT resource sampler did not stop')


def summarize(generator,router,start,seconds,mode):
    end=start+seconds;gr=[r for r in generator.rows if start<=r['monotonic']<end];rr=[r for r in router.rows if start<=r['monotonic']<end]
    if generator.errors or router.errors:raise ValueError('Resource sampler errors: '+str(generator.errors+router.errors))
    if len(gr)<max(2,seconds*2) or len(rr)<max(1,seconds//2):raise ValueError('Incomplete resource observation window')
    roles=set().union(*(r['process_cpu_percent'] for r in gr));cpus={role:percentile([r['process_cpu_percent'][role] for r in gr if role in r['process_cpu_percent']]) for role in roles}
    if not {'client','server'}<=roles:raise ValueError('Client/server CPU observations are missing')
    cores=set().union(*(r['host_steal_percent'] for r in gr));steal=max(percentile([r['host_steal_percent'][core] for r in gr if core in r['host_steal_percent']]) for core in cores)
    cpu=[int(r['resource']['cpu-load']) for r in rr];memory=[int(r['resource']['free-memory']) for r in rr];writes=[int(r['resource']['write-sect-total']) for r in rr if 'write-sect-total' in r['resource']]
    container=[int(c['memory-current']) for r in rr for c in r['containers'] if c.get('name')=='sdwan-container-controller' and c.get('running')=='true' and 'memory-current' in c]
    if mode in ('container','container-web') and (not container or min(container)<=0):raise ValueError('Active container memory observations missing')
    return {'dut_cpu_mean_percent':statistics.mean(cpu),'dut_cpu_p95_percent':percentile(cpu),'dut_memory_free_min_bytes':min(memory),'generator_cpu_p95_max_percent':max(cpus.values()),'generator_cpu_p95_by_process':cpus,'host_steal_p95_percent':steal,'container_memory_peak_bytes':max(container) if container else 0,'container_memory_scope':'max sampled cgroup memory-current at 1Hz, not process RSS or kernel memory.peak','write_sectors_delta':writes[-1]-writes[0] if len(writes)>1 and all(b>=a for a,b in zip(writes,writes[1:])) else None,'router_samples':len(rr),'generator_samples':len(gr),'measurement_start_monotonic':start,'measurement_seconds':seconds,'write_sector_scope':'RouterOS logical counter, not NAND erase cycles','generator_cpu_scope':'owned endpoint processes; excludes QEMU DUT; 100%=one logical CPU'}


def receiver_metrics(value,case):
    if 'error' in value:raise ValueError('iperf failed: '+str(value['error']))
    end=value['end'];row=end['sum_received']
    if case['kind']=='tcp':
        primary=float(row['bits_per_second'])
        forward=0 if case['direction']=='reverse' else primary
        reverse=primary if case['direction']=='reverse' else float(end['sum_received_bidir_reverse']['bits_per_second']) if case['direction']=='bidir' else 0
        return {'receiver_rate':forward+reverse,'rate_unit':'bps','forward_receiver_bps':forward,'reverse_receiver_bps':reverse,'tcp_retransmits':end.get('sum_sent',{}).get('retransmits')}
    seconds=float(row['seconds']);lost=int(row['lost_packets']);packets=int(row['packets'])
    if not seconds>0 or not 0<=lost<=packets:raise ValueError('Invalid UDP receiver counters')
    return {'receiver_rate':(packets-lost)/seconds,'rate_unit':'pps','udp_received_packets':packets-lost,'udp_lost_packets':lost,'udp_loss_percent':row['lost_percent'],'udp_payload_bytes':case['payload_bytes'],'udp_receiver_seconds':seconds}
