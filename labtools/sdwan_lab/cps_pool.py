"""Fresh-tuple CPS workload and durable reservations, including source-NAT budget."""
from dataclasses import asdict,dataclass
import hashlib
import ipaddress
import json
import math
from pathlib import Path
from .runtime import atomic_json,checked

FRESH_PER_DESTINATION=20000


def integer(value,low,high,name):
    if type(value) is not int or not low<=value<=high:raise ValueError('Invalid '+name)
    return value


@dataclass(frozen=True)
class PoolSpec:
    sources:tuple
    rate:int=1000
    warmup:int=120
    seconds:int=60
    concurrency:int=32
    source_port_low:int=11000
    source_port_high:int=60999
    tuple_offset:int=0
    destination_port_base:int=30000
    destination_port_count:int=9

    @property
    def attempts(self):return self.rate*(self.warmup+self.seconds)

    def validate(self):
        if not isinstance(self.sources,tuple) or not 1<=len(self.sources)<=512:raise ValueError('Expected 1..512 explicit source addresses')
        parsed=[ipaddress.IPv4Address(value) for value in self.sources]
        if len(set(parsed))!=len(parsed) or any(p.is_multicast or p.is_unspecified for p in parsed):raise ValueError('Sources must be distinct unicast IPv4 addresses')
        integer(self.rate,1,20000,'rate');integer(self.warmup,0,600,'warmup');integer(self.seconds,1,600,'seconds');integer(self.concurrency,1,256,'concurrency')
        integer(self.source_port_low,1024,65535,'source port low');integer(self.source_port_high,self.source_port_low,65535,'source port high')
        integer(self.tuple_offset,0,40000000,'tuple offset');integer(self.destination_port_base,1024,65535,'destination port base');integer(self.destination_port_count,1,512,'destination port count')
        if self.destination_port_base+self.destination_port_count-1>65535:raise ValueError('Destination port range exceeds 65535')
        if self.attempts>10000000:raise ValueError('At most ten million attempts per case')
        if self.tuple_offset+self.attempts>len(self.sources)*(self.source_port_high-self.source_port_low+1):raise ValueError('Fresh source tuple budget exhausted')
        if math.ceil(self.attempts/self.destination_port_count)>FRESH_PER_DESTINATION:raise ValueError('Source-NAT destination port budget exhausted')
        return self

    def client_argv(self,binary,host):
        self.validate();host=str(ipaddress.IPv4Address(host))
        return list(map(str,[binary,'client',host,self.destination_port_base,self.destination_port_count,self.rate,self.warmup,self.seconds,self.concurrency,','.join(self.sources),self.source_port_low,self.source_port_high,self.tuple_offset]))

    def server_argv(self,binary,host):
        self.validate();return list(map(str,[binary,'server',str(ipaddress.IPv4Address(host)),self.destination_port_base,self.destination_port_count]))


def reserve(run,sources,*,rate=1000,warmup=120,seconds=60,concurrency=32):
    """Caller holds the Run lease. Reserve before spawn; never recycle on failure."""
    path=run.folder/'cps-pool-reservations.json';sources=tuple(sources)
    before={'sources':list(sources),'next_tuple_offset':0,'next_destination_port':30000,'reservations':[]}
    if path.exists():
        before=json.loads(path.read_text())
        if before['sources']!=list(sources):raise ValueError('Source pool changed during run')
    spec=PoolSpec(sources,rate,warmup,seconds,concurrency,tuple_offset=before['next_tuple_offset'],destination_port_base=before['next_destination_port'],destination_port_count=math.ceil(rate*(warmup+seconds)/FRESH_PER_DESTINATION)).validate()
    before['reservations'].append(asdict(spec));before['next_tuple_offset']+=spec.attempts;before['next_destination_port']+=spec.destination_port_count
    atomic_json(path,before);return spec


def build(run,cc='cc'):
    source=Path(__file__).with_name('cps_pool.c');binary=run.folder/'cps-pool'
    if binary.exists():raise FileExistsError('CPS binary already exists in this run')
    result=checked([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',source,'-o',binary],timeout=60)
    (run.folder/'cps-pool-compile.log').write_text(result.stdout+result.stderr)
    atomic_json(run.folder/'cps-pool-build.json',{'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()})
    return binary


def validate_result(client,server,spec):
    spec.validate()
    if client.get('interrupted') or client.get('attempts')!=spec.attempts or client.get('planned_attempts')!=spec.attempts:raise ValueError('Incomplete CPS offer window')
    if any(client.get(key)!=spec.attempts for key in ('connected','echo_success')) or client.get('error_count')!=0:raise ValueError('CPS client failed connections or payload verification')
    if server.get('accepted')!=spec.attempts or server.get('completed')!=spec.attempts or server.get('errors')!=0 or server.get('active')!=0:raise ValueError('CPS endpoint counts disagree or server has unfinished connections')
    if client.get('tuple_offset')!=spec.tuple_offset or client.get('next_tuple_offset')!=spec.tuple_offset+spec.attempts:raise ValueError('CPS tuple reservation mismatch')
    if client.get('destination_port_base')!=spec.destination_port_base or client.get('destination_port_count')!=spec.destination_port_count or client.get('source_count')!=len(spec.sources):raise ValueError('CPS pool identity mismatch')
    late=client.get('maximum_schedule_lateness_seconds')
    if type(late) not in (int,float) or not math.isfinite(late) or not 0<=late<=.1:raise ValueError('CPS generator fell behind its offer schedule')
    if not 1<=client.get('peak_active',0)<=spec.concurrency:raise ValueError('CPS concurrency limit violated')
    if client.get('successful_cps',0)<spec.rate*.995:raise ValueError('Measured CPS below declared generator criterion')
    return {'pass':True,'offered_cps':spec.rate,'successful_cps':client['successful_cps'],'attempts':spec.attempts,'fresh_source_tuples':True,'source_nat_destination_budget':True,'system_TIME_WAIT_settings_changed':False}
