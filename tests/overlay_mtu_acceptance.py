#!/usr/bin/env python3
"""CHR ONLY: DF path MTU and actual SYN clamp counters on existing CGNAT links."""
import argparse,fcntl,http.server,json,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];traffic=None;report={'pass':False,'checks':[],'ping':{}}
 def record(label):report['checks'].append({'check':label,'pass':True});print('PASS '+label,flush=True)
 def clamp(router):return router.call('ip/firewall/mangle/print',{'.proplist':'packets,new-mss,chain,tcp-mss,out-interface-list','.query':['comment=sdwan:v1:overlay:mss']},'POST')[0]
 try:
  cfg=json.loads(a.read_file('sdwan-active.json'));mtu=cfg['overlay'].get('mtu',1380);assert cfg['overlay']['mss_clamp'] and all(x['healthy'] for x in a.status()['overlay'].values());traffic=VPNTraffic(v)
  for label,size in [('small',64),('boundary',mtu),('oversize',mtu+1)]:
   rows=a.call('ping',{'address':'10.201.2.1','src-address':'10.201.1.1','size':str(size),'do-not-fragment':'yes','count':'3','interval':'1s'},'POST');report['ping'][label]=rows
   received=max([int(x.get('received',0)) for x in rows]+[0])
   if label!='oversize':assert received>0,(label,rows)
   else:assert received==0 and any('fragment' in x.get('status','').lower() or 'too large' in x.get('status','').lower() for x in rows),rows
  record('real routed branch DF packets pass through the configured inner MTU boundary and the next byte receives an explicit fragmentation error')
  before={name:clamp(r) for name,r in [('sitea',a),('siteb',traffic.b)]};traffic.prepare();branch=traffic.stream(59419,'no-mark',target='10.201.1.2');after={name:clamp(r) for name,r in [('sitea',a),('siteb',traffic.b)]}
  # The first client runs on SiteB itself, so its SYN is output traffic. Reverse
  # the client/server roles to exercise the forward SYN-ACK clamp on SiteB too.
  port=traffic.base+20;served=threading.Event()
  class Handler(http.server.BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_GET(self):
    body=b'healthy\n';self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);served.set()
  server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;traffic.servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
  traffic.add(traffic.b,'ip/firewall/nat',{'chain':'srcnat','src-address':'10.201.1.1','dst-address':'10.201.2.2','protocol':'tcp','dst-port':str(port),'out-interface':'ether4','action':'masquerade'})
  name=traffic.prefix+'-reverse-'+str(port);traffic.tasks.append(name);script=traffic.add(a,'system/script',{'name':name,'source':f':execute {{ /tool/fetch url="http://10.201.2.2:{port}/" src-address=10.201.1.1 output=none idle-timeout=5s }}','policy':'read,write,policy,test'});a.call('system/script/run',{'number':script},'POST');assert served.wait(20),'Reverse branch HTTP must actually reach its server'
  after={name:clamp(r) for name,r in [('sitea',a),('siteb',traffic.b)]}
  for name,row in after.items():assert int(row['packets'])>int(before[name]['packets']) and int(row['new-mss'])==mtu-40 and row['out-interface-list']=='sdwan-overlay' and row['chain']=='forward'
  traffic.assert_sessions(retained=[branch]);report['mss']={'before':before,'after':after};record('actual forwarded TCP SYN traffic increments both owned overlay clamp rules at MTU minus 40 and the private TCP connection receives data')
  report['pass']=True
 finally:
  try:
   if traffic:traffic.close()
  finally:(v.run/'overlay-mtu-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()
if __name__=='__main__':main()
