"""Real forwarded TCP fixture using existing branch CHRs, never another VM.

Two explicit test destinations traverse SiteB -> hub -> SiteA, whose normal
policy engine selects the exit. Narrow temporary bootstrap rules are unrelated
to the branch overlay control plane. All public peer ACLs are restored exactly.
"""
import http.server,json,threading,time
from sdwan.router import Router

def tcp_stream(baseline, rows):
    # RouterOS API handles can change while the original TCP transfer continues.
    # Bind to the complete original/reply tuples and policy, then require byte
    # continuity and a single live HTTP request in the observer loop.
    fields = ('src-address', 'src-port', 'dst-address', 'dst-port', 'reply-src-address', 'reply-src-port', 'reply-dst-address', 'reply-dst-port')
    matches = [row for row in rows if all(row.get(key) == baseline.get(key) for key in fields) and row.get('connection-mark', 'no-mark') == baseline.get('connection-mark', 'no-mark') and row.get('tcp-state') == 'established' and row.get('seen-reply') == 'true']
    assert len(matches) == 1, 'Original TCP tuple is missing or ambiguous'
    current = matches[0]
    assert all(int(current[key]) >= int(baseline[key]) for key in ('orig-bytes', 'repl-bytes')), 'Original TCP counters reset'
    return current


class Flow(str):
 """Opaque compatible test token; RouterOS API IDs are not stable identities."""
 def __new__(cls,row,stats):
  value=super().__new__(cls,row['.id']);value.snapshot=dict(row);value.last=dict(row);value.http=stats;return value

def same_path(flow,row):
 # A renamed API handle must not make a still-present old marked path disappear.
 fields=('src-address','src-port','dst-address','dst-port')
 return bool(row.get('tcp-state')) and all(row.get(k)==flow.snapshot.get(k) for k in fields) and row.get('connection-mark','no-mark')==flow.snapshot.get('connection-mark','no-mark')

class VPNTraffic:
 def __init__(self,fixture):
  self.fixture=fixture;self.a=fixture.routers['sitea'];self.h=fixture.routers['hub'];creds=json.loads((fixture.run/'credentials.json').read_text());self.b=Router(fixture.root,'api://127.0.0.1:55730',credentials_data=creds['siteb']);self.n=Router(fixture.root,'api://127.0.0.1:55731',credentials_data=creds['nata']);self.created=[];self.changed=[];self.servers=[];self.stop=threading.Event();self.prefix='vpn-egress-client-only';self.tasks=[];self.stream_specs={};self.stream_stats={};self.stream_generations={};counter=fixture.run/'vpn-flow-counter.json';value=int(json.loads(counter.read_text()).get('counter',0)) if counter.exists() else 0;counter.write_text(json.dumps({'counter':value+1})+'\n');self.base=60000+(value%100)*40
 def add(self,r,menu,data):
  if r is self.a and menu=='ip/firewall/filter' and data.get('chain')=='forward' and data.get('place-before')=='0':
   rules=r.call(menu+'/print',{'.proplist':'.id,chain,comment'},'POST');barriers=[i for i,x in enumerate(rules) if x.get('comment') in ('sdwan-container:no-forward','sdwan-container:no-forward-to-container')]
   if barriers:
    anchor=next((x['.id'] for i,x in enumerate(rules) if i>max(barriers) and x.get('chain')=='forward' and not x.get('comment','').startswith('sdwan-container:')),None);data=dict(data);data.pop('place-before')
    if anchor:data['place-before']=anchor
  row=r.call(menu,dict(data,comment=self.prefix),'PUT');self.created.append((r,menu,row['.id']));return row['.id']
 def prepare(self):
  assert self.b.call('system/identity')['name']=='sdwan-overlay-siteb';assert self.n.call('system/identity')['name']=='sdwan-overlay-nata'
  assert not self.b.call('system/script/print',{'.proplist':'name','.query':['comment='+self.prefix]},'POST'),'previous TCP fixture must not be duplicated'
  for r,ifaces in [(self.b,['sdwan-wg-hub-wan1','sdwan-wg-hub-wan2']),(self.h,['sdwan-wg-sitea-wan1','sdwan-wg-sitea-wan2'])]:
   # The explicit outbound fixture uses WAN1, while legitimate OSPF return
   # traffic may use either leg during convergence/failover. Authorize its two
   # public source addresses on BOTH peers, then restore all original ACLs.
   for iface in ifaces:
    row=r.call('interface/wireguard/peers/print',{'.proplist':'.id,allowed-address','.query':['interface='+iface]},'POST')[0];value=row['allowed-address'];old=value if isinstance(value,str) else ','.join(value);self.changed.append((r,row['.id'],old));r.call('interface/wireguard/peers/set',{'.id':row['.id'],'allowed-address':old+',198.19.100.1/32,198.19.100.2/32'},'POST')
   for target in ('198.19.100.1','198.19.100.2'):self.add(r,'ip/route',{'dst-address':target+'/32','gateway':ifaces[0],'routing-table':'main','distance':'1'})
  self.add(self.h,'ip/firewall/mangle',{'chain':'prerouting','src-address':'10.201.2.0/24','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','action':'accept','place-before':'0'})
  self.add(self.h,'ip/firewall/filter',{'chain':'forward','src-address':'10.201.2.0/24','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','out-interface':'sdwan-wg-sitea-wan1','action':'accept','place-before':'0'})
  self.add(self.a,'ip/firewall/filter',{'chain':'forward','src-address':'10.201.2.0/24','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','out-interface-list':'WAN','action':'accept','place-before':'0'})
  self.add(self.a,'ip/firewall/nat',{'chain':'srcnat','src-address':'10.201.2.1','dst-address':'10.201.1.2','protocol':'tcp','dst-port':str(self.base+9),'out-interface':'ether4','action':'masquerade'})
  self.add(self.n,'ip/firewall/nat',{'chain':'dstnat','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','action':'dst-nat','to-addresses':'10.78.3.2'})
  self.add(self.n,'ip/firewall/filter',{'chain':'forward','dst-address':'10.78.3.2','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','action':'accept','place-before':'0'})
  time.sleep(1) # allow RouterOS to publish the updated peer/address classifiers
 def connections(self):return self.a.call('ip/firewall/connection/print',{'.proplist':'.id,src-address,src-port,dst-address,dst-port,connection-mark,tcp-state,seen-reply,orig-bytes,repl-bytes,srcnat,reply-src-address,reply-src-port,reply-dst-address,reply-dst-port,timeout'},'POST')
 def _generation(self,spec):
  generation=len(self.stream_generations[spec['port']])+1
  stats={'generation':generation,'requests':0,'active':0,'sent_bytes':0,'error':None}
  spec['stats']=stats;spec['stop']=threading.Event();spec['connections']=set()
  self.stream_stats[spec['port']]=stats;self.stream_generations[spec['port']].append(stats)
  return stats
 def stream(self,port,mark,target='198.19.100.1',source='10.201.2.1',timeout=20,content_length=100000000):
  port=self.base+(port-59410)
  assert port not in self.stream_specs,'Do not duplicate an existing stream endpoint'
  spec={'port':port,'target':target,'source':source,'lock':threading.Lock()}
  self.stream_specs[port]=spec;self.stream_generations[port]=[];self._generation(spec)
  owner=self
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    with spec['lock']:
     stats=spec['stats'];stop=spec['stop'];connections=spec['connections']
     stats['requests']+=1;stats['active']+=1;connections.add(self.connection)
    try:
     self.send_response(200);self.send_header('Content-Length',str(content_length));self.end_headers()
     while not owner.stop.is_set() and not stop.wait(.2):
      self.wfile.write(b'x'*256);self.wfile.flush();stats['sent_bytes']+=256
    except (OSError,ConnectionError) as error:stats['error']=type(error).__name__
    finally:
     with spec['lock']:stats['active']-=1;connections.discard(self.connection)
  server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;self.servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
  name=self.prefix+'-'+str(port);self.tasks.append(name);spec['name']=name
  spec['script']=self.add(self.b,'system/script',{'name':name,'source':f':execute {{ /tool/fetch url="http://{target}:{port}/stream" src-address={source} output=none idle-timeout=60s }}','policy':'read,write,policy,test'})
  return self._launch_stream(spec,mark,timeout)
 def _launch_stream(self,spec,mark,timeout):
  self.b.call('system/script/run',{'number':spec['script']},'POST')
  if timeout is None:return None
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   rows=[x for x in self.connections() if x.get('src-address')==spec['source'] and x.get('dst-port')==str(spec['port'])]
   flow=self.find_stream(spec['port'],mark,rows)
   if flow is not None:return flow
   time.sleep(.2)
  raise AssertionError({'port':spec['port'],'mark':mark,'flows':rows,'http_generation':dict(spec['stats']),'selected':self.a.status().get('selected')})
 def find_stream(self,port,mark,rows):
  spec=self.stream_specs[port];stats=spec['stats']
  matches=[row for row in rows if row.get('src-address')==spec['source'] and row.get('dst-port')==str(port) and row.get('tcp-state')=='established' and row.get('seen-reply')=='true' and row.get('connection-mark','no-mark')==mark]
  assert len(matches)<=1,'Replacement TCP tuple is ambiguous'
  if matches and stats['requests']==1 and stats['active']==1 and stats['error'] is None:
   flow=Flow(matches[0],stats);flow.port=port;return flow
  return None
 def stop_stream(self,flow):
  import socket
  spec=self.stream_specs[flow.port]
  assert flow.http is spec['stats'],'Cannot stop a different HTTP generation'
  # Delete only the RAM job of this pre-created script. No script/file rewrite.
  for job in self.b.call('system/script/job/print',{'.proplist':'.id,trace'},'POST'):
   if '/script:'+spec['name']+'/' in job.get('trace',''):
    self.b.call('system/script/job/'+job['.id'],method='DELETE')
  with spec['lock']:
   spec['stop'].set()
   for connection in list(spec['connections']):
    try:connection.shutdown(socket.SHUT_RDWR)
    except OSError:pass
  end=time.monotonic()+5
  while spec['stats']['active'] and time.monotonic()<end:time.sleep(.05)
  assert spec['stats']['active']==0,'Retired HTTP generation did not close'
 def restart_stream(self,flow,mark,timeout=20):
  assert not any(same_path(flow,row) for row in self.connections()),'Prove old marked tuple retirement before restarting'
  spec=self.stream_specs[flow.port];self.stop_stream(flow)
  with spec['lock']:self._generation(spec)
  return self._launch_stream(spec,mark,timeout)
 def assert_sessions(self,absent=(),retained=()):
  end=time.monotonic()+3;problem={}
  while time.monotonic()<end:
   rows=self.connections();unexpected=[row for flow in absent for row in rows if same_path(flow,row)];current=[]
   try:
    for flow in retained:
     row=tcp_stream(flow.last,rows);assert flow.http['requests']==1 and flow.http['active']==1 and flow.http['error'] is None,'Retained HTTP request closed or restarted';current.append((flow,row))
    if not unexpected:break
    problem={'unexpected':unexpected}
   except AssertionError as error:problem={'retained':str(error)}
   time.sleep(.1)
  else:raise AssertionError(dict(problem,cleanup=self.a.status().get('last_cleanup')))
  before=[(flow,int(row['repl-bytes'])) for flow,row in current];end=time.monotonic()+20
  while time.monotonic()<end:
   rows=self.connections();updated=[]
   try:
    for flow,size in before:
     row=tcp_stream(flow.last,rows);assert int(row['repl-bytes'])>size,'Retained TCP stalled';assert flow.http['requests']==1 and flow.http['active']==1 and flow.http['error'] is None,'Retained HTTP request closed or restarted';updated.append((flow,row))
    for flow,row in updated:flow.last=dict(row)
    return
   except AssertionError as error:problem={'retained':str(error)}
   time.sleep(.2)
  raise AssertionError(dict(problem,cleanup=self.a.status().get('last_cleanup')))
 def close(self):
  self.stop.set()
  try:
   for origin in (self.b,self.a):
    for job in origin.call('system/script/job/print',{'.proplist':'.id,trace'},'POST'):
     if any('/script:'+name+'/' in job.get('trace','') for name in self.tasks):
      try:origin.call('system/script/job/'+job['.id'],method='DELETE')
      except RuntimeError:pass
   for r in (self.b,self.h,self.a,self.n):
    for row in r.call('ip/firewall/connection/print',{'.proplist':'.id,dst-address,dst-port'},'POST'):
     if row.get('dst-address') in ('198.19.100.1','198.19.100.2','10.201.1.2') and str(row.get('dst-port','')).isdigit() and self.base<=int(row['dst-port'])<self.base+30:
      try:r.call('ip/firewall/connection/'+row['.id'],method='DELETE')
      except RuntimeError:pass
   for r,menu,id in reversed(self.created):
    try:r.call(menu+'/'+id,method='DELETE')
    except RuntimeError:pass
   for r,id,value in reversed(self.changed):r.call('interface/wireguard/peers/set',{'.id':id,'allowed-address':value},'POST')
  finally:
   for server in self.servers:server.shutdown();server.server_close()
   self.b.close();self.n.close()
