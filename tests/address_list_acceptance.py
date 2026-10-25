#!/usr/bin/env python3
"""CHR ONLY: existing Address List membership, TTL, conntrack and ownership."""
import argparse,copy,json,time,http.server,threading
from pathlib import Path
from network_lab import NetworkLab
import stream_traffic

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',type=Path,required=True);args=p.parse_args();report={'checks':[],'pass':False};servers=[]
 def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
 class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):self.send_response(200);self.send_header('Content-Length','3');self.end_headers();self.wfile.write(b'ok\n')
 try:
  for port in (59311,59312,59316,59317,59318):
   server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
  with NetworkLab(args.lab_root) as env:
   r=env.router;cfg=copy.deepcopy(env.before);cfg['revision']='external-list-fixture'
   for profile in cfg['sla_profiles'].values():profile['jitter_ms']=100
   # Selector membership is independent of asynchronous body-probe scheduling.
   # The strict probe contract has its own dedicated CHR acceptance suite.
   from sdwan.probes import STRICT_FIELDS
   for wan in cfg['wans']:
    for probe in wan['probes']:
     for field in STRICT_FIELDS:probe.pop(field,None)
   for i,policy in enumerate(p for p in cfg['policies'] if p['source']):policy['priority']=20+i*10
   cfg['policies'].append(dict(name='targets',source='0.0.0.0/0',table='sdwan-targets',profile='default',mode='prefer',wans=['wan2','wan1'],allow_degraded=False,priority=10,destination_list='fixture-existing-destinations'))
   static=env.add('edge','ip/firewall/address-list',{'list':'fixture-existing-destinations','address':'203.0.113.200'})
   control=env.add('edge','ip/firewall/address-list',{'list':'fixture-existing-destinations','address':'203.0.113.202'})
   for n in (1,2,3):
    for target in ('203.0.113.200','198.19.0.1'):env.add('isp'+str(n),'ip/firewall/nat',{'chain':'dstnat','dst-address':target,'protocol':'tcp','dst-port':'59310-59319','action':'dst-nat','to-addresses':f'10.77.{n}.2'})
   if not any(x.get('address')=='192.168.50.103/24' for x in env.lab.api('client','ip/address')):env.add('client','ip/address',{'address':'192.168.50.103/24','interface':'ether2'})
   env.apply(cfg);env.healthy();rows=r.call('ip/firewall/address-list/print',{'.proplist':'.id,list,address,comment'},'POST');assert {static,control}<={x['.id'] for x in rows}
   print('MATCHERS',r.call('ip/firewall/mangle/print',{'.proplist':'comment,src-address,dst-address-list,disabled','.query':['dst-address-list=fixture-existing-destinations']},'POST'),flush=True)
   record('protected apply references the original list without deleting or adopting its entries')
   stream_traffic.lab=env.lab;traffic=stream_traffic.StreamTraffic(r,env.add)
   def finite(port,mark,destination="203.0.113.200",source="192.168.50.101"):
    reply=env.lab.api('client','tool/fetch',{'url':f'http://{destination}:{port}/','src-address':source,'output':'none'},'POST');reply=reply[-1] if isinstance(reply,list) else reply;assert reply.get('status')=='finished',reply
    rows=r.call('ip/firewall/connection/print',{'.proplist':'dst-port,connection-mark,seen-reply'},'POST');assert any(x.get('dst-port')==str(port) and x.get('connection-mark')==mark and x.get('seen-reply')=='true' for x in rows),(port,mark,[x for x in rows if x.get('dst-port')==str(port)],{k:v for k,v in r.status().items() if k in ('selected','states')})
   try:
    a=traffic.stream('192.168.50.101','wan2',59310,policy='targets')['.id']
    finite(59311,'sdwan-out-client101:wan1',destination='198.19.0.1')
    finite(59312,'sdwan-out-strict103:wan3',destination='198.19.0.1',source='192.168.50.103')
    record('matched destinations use the higher-priority list policy while unmatched and strict traffic keep their original paths')
    r.call('ip/firewall/address-list/'+static,method='DELETE');time.sleep(1);print('LIST after removal',r.call('ip/firewall/address-list/print',{'.proplist':'.id,list,address,dynamic','.query':['list=fixture-existing-destinations']},'POST'),flush=True);finite(59316,'sdwan-out-client101:wan1');traffic.assert_sessions(retained=[a])
    record('removing a list member affects new connections and preserves established marked sessions')
    timed=env.add('edge','ip/firewall/address-list',{'list':'fixture-existing-destinations','address':'203.0.113.200','timeout':'10s'})
    time.sleep(1);finite(59317,'sdwan-out-targets:wan2')
    end=time.monotonic()+45
    while time.monotonic()<end:
     entry=r.call('ip/firewall/address-list/print',{'.proplist':'.id,timeout','.query':['.id='+timed]},'POST')
     if not entry:break
     time.sleep(.2)
    else:raise AssertionError('RouterOS did not retire the timed list entry within45s')
    time.sleep(1);finite(59318,'sdwan-out-client101:wan1');traffic.assert_sessions(retained=[a])
    record('native timed list membership expires without polling/copying it; new connections return to the ordinary policy')
    assert r.call('ip/firewall/address-list/print',{'.proplist':'.id','.query':['.id='+control]},'POST');report['pass']=True
   finally:traffic.close()
 finally:
  for server in servers:server.shutdown();server.server_close()
  (args.lab_root/'runtime/address-list-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
