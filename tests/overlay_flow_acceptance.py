from pathlib import Path
import sys,json,time,threading,http.server,fcntl
import argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
p=argparse.ArgumentParser(description='CHR ONLY: real branch TCP survival and all-down blackhole');p.add_argument('--lab-root',type=Path,required=True);args=p.parse_args();root=args.lab_root.resolve();profile=root/'runtime/overlay-lab'
from sdwan.router import Router
credentials=json.loads((profile/'runtime/credentials.json').read_text());routers={n:Router(profile,'api://127.0.0.1:'+str(55728+i),credentials_data=credentials[n]) for n,i in [('hub',0),('sitea',1),('siteb',2)]};lock=(profile/'runtime/lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
report={'checks':[],'pass':False};stop=threading.Event();name='sdwan-overlay-flow-test';created=[];disabled=False;server=None;a=routers['sitea'];b=routers['siteb']
def record(check,**values):report['checks'].append({'check':check,'pass':True,**values});print('PASS '+check,flush=True)
def wait(predicate,timeout=50):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  if predicate():return
  time.sleep(.3)
 raise AssertionError('condition timed out')
def connections():return a.call('ip/firewall/connection/print',{'.proplist':'.id,src-address,dst-address,dst-port,connection-mark,tcp-state,seen-reply,orig-bytes,repl-bytes'},'POST')
def flow():return next((x for x in connections() if x.get('src-address')=='10.201.1.1' and x.get('dst-address')=='10.201.2.2' and x.get('dst-port')=='59090' and x.get('tcp-state')=='established' and x.get('seen-reply')=='true'),None)
def inner_route(router,prefix):
 rows=router.call('ip/route/print',{'.proplist':'dst-address,gateway,active,blackhole,ospf'},'POST');return [x for x in rows if x.get('dst-address')==prefix and x.get('active')=='true']
def route_via(wan):return any('sdwan-wg-hub-'+wan in x.get('gateway','') for x in inner_route(a,'10.201.2.0/24'))
try:
 for n,r in routers.items():assert r.call('system/identity')['name']=='sdwan-overlay-'+n
 assert len(routers['hub'].call('routing/ospf/neighbor'))==4
 assert not a.call('system/script/print',{'.proplist':'name','.query':['name='+name]},'POST'),'existing stream test must not be duplicated'
 assert route_via('wan1'),inner_route(a,'10.201.2.0/24')
 # An explicit lab-only LAN SNAT makes the QEMU user-network HTTP host return
 # this forwarded stream to the branch router, independently of guest routing.
 nat=b.call('ip/firewall/nat',{'chain':'srcnat','out-interface':'ether4','src-address':'10.201.1.0/24','dst-address':'10.201.2.2','protocol':'tcp','dst-port':'59090','action':'masquerade','comment':name},'PUT');created.append((b,'ip/firewall/nat',nat['.id']))
 class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   self.send_response(200);self.send_header('Content-Length','100000000');self.end_headers()
   try:
    while not stop.wait(.2):self.wfile.write(b'x'*256);self.wfile.flush()
   except (OSError,ConnectionError):pass
 server=http.server.ThreadingHTTPServer(('127.0.0.1',59090),Handler);server.daemon_threads=True;threading.Thread(target=server.serve_forever,daemon=True).start()
 source=':execute { /tool/fetch url="http://10.201.2.2:59090/stream" src-address=10.201.1.1 output=none idle-timeout=60s }'
 script=a.call('system/script',{'name':name,'source':source,'policy':'read,write,policy,test','comment':name},'PUT');created.append((a,'system/script',script['.id']));a.call('system/script/run',{'number':script['.id']},'POST')
 wait(lambda:flow() is not None);first=flow();identifier=first['.id'];assert first.get('connection-mark') in (None,'no-mark');record('real inner TCP stream uses OSPF through hub without an Internet WAN connection mark',connection_id=identifier)
 rows=a.call('interface/print',{'.proplist':'.id,name,disabled','.query':['name=ether2']},'POST');iface=rows[0]['.id'];assert rows[0]['disabled']=='false'
 a.call('interface/'+iface,{'disabled':'true'},'PATCH');disabled=True
 wait(lambda:a.status()['overlay']['hub-wan1']['healthy'] is False and route_via('wan2'))
 before=flow();assert before and before['.id']==identifier;received=int(before['repl-bytes']);wait(lambda:flow() is not None and flow()['.id']==identifier and int(flow()['repl-bytes'])>received+512)
 record('same established TCP connection receives new data after WAN1 failure and OSPF migration to WAN2',connection_id=identifier)
 a.call('interface/'+iface,{'disabled':'false'},'PATCH');disabled=False
 wait(lambda:a.status()['overlay']['hub-wan1']['healthy'] is True and route_via('wan1'))
 before=flow();assert before and before['.id']==identifier;received=int(before['repl-bytes']);wait(lambda:flow() is not None and flow()['.id']==identifier and int(flow()['repl-bytes'])>received+512)
 record('same inner TCP stream survives fresh-SLA recovery and preferred-path failback',connection_id=identifier)
 # Stop both physical underlays briefly. The remote prefix must become an
 # active blackhole rather than leaking through an Internet default.
 for ifname in ('ether2','ether3'):
  row=a.call('interface/print',{'.proplist':'.id','.query':['name='+ifname]},'POST')[0];a.call('interface/'+row['.id'],{'disabled':'true'},'PATCH')
 disabled=True
 wait(lambda:all(not row['healthy'] for row in a.status()['overlay'].values()) and any('blackhole' in row and row['blackhole'] in ('','true',True) for row in inner_route(a,'10.201.2.0/24')))
 record('all overlay underlays down withdraw OSPF and activate the exact remote-LAN blackhole')
 report['pass']=True
finally:
 if disabled:
  for ifname in ('ether2','ether3'):
   row=a.call('interface/print',{'.proplist':'.id','.query':['name='+ifname]},'POST')[0];a.call('interface/'+row['.id'],{'disabled':'false'},'PATCH')
 stop.set()
 try:
  jobs=a.call('system/script/job/print',{'.proplist':'.id,trace'},'POST')
  for job in jobs:
   if '/script:'+name+'/' in job.get('trace',''):
    try:a.call('system/script/job/'+job['.id'],method='DELETE')
    except RuntimeError:pass
 finally:
  for r,menu,id in reversed(created):
   try:r.call(menu+'/'+id,method='DELETE')
   except RuntimeError:pass
  if server:server.shutdown();server.server_close()
  for r in routers.values():r.close()
  lock.close();(profile/'runtime/overlay-flow-validation.json').write_text(json.dumps(report,indent=2)+'\n')
