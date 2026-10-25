"""Real forwarded TCP fixture using existing branch CHRs, never another VM.

Two explicit test destinations traverse SiteB -> hub -> SiteA, whose normal
policy engine selects the exit. Narrow temporary bootstrap rules are unrelated
to the branch overlay control plane. All public peer ACLs are restored exactly.
"""
import http.server,json,threading,time
from sdwan.router import Router

class VPNTraffic:
 def __init__(self,fixture):
  self.fixture=fixture;self.a=fixture.routers['sitea'];self.h=fixture.routers['hub'];creds=json.loads((fixture.run/'credentials.json').read_text());self.b=Router(fixture.root,'api://127.0.0.1:55730',credentials_data=creds['siteb']);self.n=Router(fixture.root,'api://127.0.0.1:55731',credentials_data=creds['nata']);self.created=[];self.changed=[];self.servers=[];self.stop=threading.Event();self.prefix='vpn-egress-client-only';self.tasks=[];counter=fixture.run/'vpn-flow-counter.json';value=int(json.loads(counter.read_text()).get('counter',0)) if counter.exists() else 0;counter.write_text(json.dumps({'counter':value+1})+'\n');self.base=60000+(value%100)*40
 def add(self,r,menu,data):
  row=r.call(menu,dict(data,comment=self.prefix),'PUT');self.created.append((r,menu,row['.id']));return row['.id']
 def prepare(self):
  assert self.b.call('system/identity')['name']=='sdwan-overlay-siteb';assert self.n.call('system/identity')['name']=='sdwan-overlay-nata'
  assert not self.b.call('system/script/print',{'.proplist':'name','.query':['comment='+self.prefix]},'POST'),'previous TCP fixture must not be duplicated'
  for r,iface in [(self.b,'sdwan-wg-hub-wan1'),(self.h,'sdwan-wg-sitea-wan1')]:
   row=r.call('interface/wireguard/peers/print',{'.proplist':'.id,allowed-address','.query':['interface='+iface]},'POST')[0];value=row['allowed-address'];old=value if isinstance(value,str) else ','.join(value);self.changed.append((r,row['.id'],old));r.call('interface/wireguard/peers/'+row['.id'],{'allowed-address':old+',198.19.100.1/32,198.19.100.2/32'},'PATCH')
   for target in ('198.19.100.1','198.19.100.2'):self.add(r,'ip/route',{'dst-address':target+'/32','gateway':iface,'routing-table':'main','distance':'1'})
  self.add(self.h,'ip/firewall/mangle',{'chain':'prerouting','src-address':'10.201.2.1','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','action':'accept','place-before':'0'})
  self.add(self.h,'ip/firewall/filter',{'chain':'forward','src-address':'10.201.2.1','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','out-interface':'sdwan-wg-sitea-wan1','action':'accept','place-before':'0'})
  self.add(self.a,'ip/firewall/filter',{'chain':'forward','src-address':'10.201.2.1','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','out-interface-list':'WAN','action':'accept','place-before':'0'})
  self.add(self.a,'ip/firewall/nat',{'chain':'srcnat','src-address':'10.201.2.1','dst-address':'10.201.1.2','protocol':'tcp','dst-port':str(self.base+9),'out-interface':'ether4','action':'masquerade'})
  self.add(self.n,'ip/firewall/nat',{'chain':'dstnat','dst-address':'198.19.100.0/30','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','action':'dst-nat','to-addresses':'10.78.3.2'})
  self.add(self.n,'ip/firewall/filter',{'chain':'forward','dst-address':'10.78.3.2','protocol':'tcp','dst-port':f'{self.base}-{self.base+29}','action':'accept','place-before':'0'})
  time.sleep(1) # allow RouterOS to publish the updated peer/address classifiers
 def connections(self):return self.a.call('ip/firewall/connection/print',{'.proplist':'.id,src-address,dst-address,dst-port,connection-mark,tcp-state,seen-reply,orig-bytes,repl-bytes,srcnat,reply-src-address,reply-src-port,reply-dst-address,reply-dst-port,timeout'},'POST')
 def stream(self,port,mark,target='198.19.100.1'):
  port=self.base+(port-59410)
  stop=self.stop
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    self.send_response(200);self.send_header('Content-Length','100000000');self.end_headers()
    try:
     while not stop.wait(.2):self.wfile.write(b'x'*256);self.wfile.flush()
    except (OSError,ConnectionError):pass
  server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;self.servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
  name=self.prefix+'-'+str(port);self.tasks.append(name)
  script=self.add(self.b,'system/script',{'name':name,'source':f':execute {{ /tool/fetch url="http://{target}:{port}/stream" src-address=10.201.2.1 output=none idle-timeout=60s }}','policy':'read,write,policy,test'})
  self.b.call('system/script/run',{'number':script},'POST');end=time.monotonic()+20
  while time.monotonic()<end:
   rows=[x for x in self.connections() if x.get('src-address')=='10.201.2.1' and x.get('dst-port')==str(port)]
   for row in rows:
    if row.get('tcp-state')=='established' and row.get('seen-reply')=='true' and row.get('connection-mark','no-mark')==mark:return row['.id']
   time.sleep(.2)
  raise AssertionError({'port':port,'mark':mark,'flows':rows})
 def assert_sessions(self,absent=(),retained=()):
  end=time.monotonic()+3
  while time.monotonic()<end:
   rows={x['.id']:x for x in self.connections()}
   if not set(absent)&rows.keys() and set(retained)<=rows.keys():break
   time.sleep(.1)
  else:raise AssertionError({'unexpected':{id:rows[id] for id in set(absent)&rows.keys()},'missing':list(set(retained)-rows.keys()),'cleanup':self.a.status().get('last_cleanup')})
  before={id:int(rows[id].get('repl-bytes',0)) for id in retained};end=time.monotonic()+20
  while time.monotonic()<end:
   rows={x['.id']:x for x in self.connections()}
   if all(id in rows and int(rows[id].get('repl-bytes',0))>size for id,size in before.items()):return
   time.sleep(.2)
  raise AssertionError({'stalled':{id:rows.get(id) for id,size in before.items() if id not in rows or int(rows[id].get('repl-bytes',0))<=size},'cleanup':self.a.status().get('last_cleanup')})
 def close(self):
  self.stop.set()
  try:
   for job in self.b.call('system/script/job/print',{'.proplist':'.id,trace'},'POST'):
    if any('/script:'+name+'/' in job.get('trace','') for name in self.tasks):
     try:self.b.call('system/script/job/'+job['.id'],method='DELETE')
     except RuntimeError:pass
   for r in (self.b,self.h,self.a,self.n):
    for row in r.call('ip/firewall/connection/print',{'.proplist':'.id,dst-address,dst-port'},'POST'):
     if row.get('dst-address') in ('198.19.100.1','198.19.100.2','10.201.1.2') and str(row.get('dst-port','')).isdigit() and self.base<=int(row['dst-port'])<self.base+30:
      try:r.call('ip/firewall/connection/'+row['.id'],method='DELETE')
      except RuntimeError:pass
   for r,menu,id in reversed(self.created):
    try:r.call(menu+'/'+id,method='DELETE')
    except RuntimeError:pass
   for r,id,value in reversed(self.changed):r.call('interface/wireguard/peers/'+id,{'allowed-address':value},'PATCH')
  finally:
   for server in self.servers:server.shutdown();server.server_close()
   self.b.close();self.n.close()
