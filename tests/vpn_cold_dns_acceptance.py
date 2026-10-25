#!/usr/bin/env python3
"""CHR ONLY: uncached external DNS bootstraps VPN while main Internet is closed.

The loopback DNS fixture deliberately withholds all answers through cold boot.
No DNS static overrides, production connections or extra virtual routers.
"""
import argparse,base64,contextlib,copy,fcntl,http.server,importlib.util,json,socket,ssl,struct,subprocess,sys,tempfile,threading,time,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic
from sdwan.diagnostics import seconds

class DNSFixture:
 def __init__(self):
  self.ready=threading.Event();self.stop=threading.Event();self.queries=0;self.answers=0;self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);self.socket.bind(('127.0.0.1',53553));self.socket.settimeout(.25);self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
 def run(self):
  while not self.stop.is_set():
   try:data,peer=self.socket.recvfrom(2048)
   except socket.timeout:continue
   except OSError:return
   self.queries+=1
   if not self.ready.is_set():continue
   try:self.socket.sendto(self.response(data),peer);self.answers+=1
   except (IndexError,OSError):pass
 @staticmethod
 def response(data):
  end=12
  while data[end]:end+=data[end]+1
  end+=5;kind=int.from_bytes(data[end-4:end-2],'big');answer=b'\xc0\x0c'+struct.pack('!HHIH',1,1,1,4)+socket.inet_aton('198.18.100.1') if kind==1 else b''
  return data[:2]+struct.pack('!HHHHH',0x8180,1,int(kind==1),0,0)+data[12:end]+answer
 def close(self):self.stop.set();self.socket.close();self.thread.join(timeout=2)


class DoHFixture:
 def __init__(self,dns):
  self.answers=0;self.directory=tempfile.TemporaryDirectory(prefix='sdwan-test-doh-');path=Path(self.directory.name)
  subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=sdwan-lab-doh','-keyout',str(path/'key.pem'),'-out',str(path/'cert.pem')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  owner=self
  class Handler(http.server.BaseHTTPRequestHandler):
   protocol_version='HTTP/1.1'
   def log_message(self,*args):pass
   def answer(self,data):
    if not dns.ready.is_set():self.send_error(503);return
    if not 12<=len(data)<=2048:self.send_error(400);return
    try:body=dns.response(data)
    except IndexError:self.send_error(400);return
    self.send_response(200);self.send_header('Content-Type','application/dns-message');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);self.wfile.flush();owner.answers+=1
   def do_POST(self):
    size=int(self.headers.get('Content-Length','0'))
    if size>2048:self.send_error(413);return
    self.answer(self.rfile.read(size))
   def do_GET(self):
    value=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('dns',[''])[0]
    try:self.answer(base64.urlsafe_b64decode(value+'='*((-len(value))%4)))
    except ValueError:self.send_error(400)
  tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(path/'cert.pem',path/'key.pem');tls.set_alpn_protocols(['http/1.1']);self.server=http.server.ThreadingHTTPServer(('127.0.0.1',53554),Handler);self.server.socket=tls.wrap_socket(self.server.socket,server_side=True);self.server.daemon_threads=True;self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
 def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2);self.directory.cleanup()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);p.add_argument('--doh',action='store_true');args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];h=v.routers['hub'];before=json.loads(a.read_file('sdwan-active.json'));report={'pass':False,'checks':[]};created=[];blocks=[];traffic=None;dns=None;doh=None;peer=None;applied=False;original_dns=a.call('ip/dns/print',{'.proplist':'servers,use-doh-server,verify-doh-cert'},'POST')[0];hostname='cold-vpn-bootstrap-fixture.test';tag='vpn-cold-dns-acceptance';dns_ip='198.19.100.2'
 spec=importlib.util.spec_from_file_location('vpn_cold_dns_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'vpn-protected-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(a,c,'sdwan-overlay-sitea')
 def add(r,menu,fields):
  id=r.call(menu+'/add',dict(fields,comment=tag),'POST')['ret'];created.append((r,menu,id));return id
 def wait(fn,timeout=180,reconnect=False):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   try:
    value=fn()
    if value:return value
   except (ConnectionError,OSError,RuntimeError):
    if not reconnect:raise
    a.close()
   time.sleep(.3)
  raise AssertionError('Cold external-DNS VPN condition timed out')
 def record(label):report['checks'].append({'check':label,'pass':True});print('PASS '+label,flush=True)
 def healthy():
  s=a.status();assert not s.get('error'),s.get('error');return s.get('selected',{}).get('vpn-targets')=='vpn1'
 def guard_packets():return int(a.call('ip/firewall/mangle/print',{'.proplist':'packets,action','.query':['comment=sdwan:v1:guard:default']},'POST')[0]['packets'])
 try:
  traffic=VPNTraffic(v);n=traffic.n;dns=DNSFixture();dns.ready.set()
  add(n,'ip/address',{'address':dns_ip+'/32','interface':'probe-loopback'})
  add(n,'ip/firewall/nat',{'chain':'dstnat','dst-address':dns_ip,'protocol':'udp','dst-port':'53','action':'dst-nat','to-addresses':'10.78.3.2','to-ports':'53553','place-before':'0'})
  add(n,'ip/firewall/filter',{'chain':'forward','dst-address':'10.78.3.2','protocol':'udp','dst-port':'53553','action':'accept','place-before':'0'})
  a.call('ip/dns/set',{'servers':dns_ip,'use-doh-server':''},'POST')
  if args.doh:
   doh=DoHFixture(dns)
   add(n,'ip/firewall/nat',{'chain':'dstnat','dst-address':'198.18.100.1','protocol':'tcp','dst-port':'15443','action':'dst-nat','to-addresses':'10.78.3.2','to-ports':'53554','place-before':'0'})
   add(n,'ip/firewall/filter',{'chain':'forward','dst-address':'10.78.3.2','protocol':'tcp','dst-port':'53554','action':'accept','place-before':'0'})
   # The ephemeral fixture has a self-signed certificate. This test-only setting
   # is restored exactly; the controller never changes certificate validation.
   a.call('ip/dns/set',{'use-doh-server':'https://doh-bootstrap-fixture.test:15443/dns-query','verify-doh-cert':'no'},'POST')

  peer=a.call('interface/wireguard/peers/print',{'.proplist':'.id,endpoint-address','.query':['interface=vpn-exit-wg']},'POST')[0];assert peer['endpoint-address']=='198.18.100.1';a.call('interface/wireguard/peers/set',{'numbers':peer['.id'],'endpoint-address':hostname},'POST')
  cfg=copy.deepcopy(before);cfg['revision']='vpn-cold-external-dns';w=copy.deepcopy(cfg['wans'][0]);w.pop('address');w.pop('gateway');w.update(v.state['links']['wireguard']);w.update(name='vpn1',kind='vpn',vpn_endpoint=hostname,probe_table='sdwan-probe-vpn1',masquerade=True,allow_selected_forward=True);cfg['wans'].append(w);cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',destination_list='vpn-cold-dns-targets',priority=10,wans=['vpn1','wan1','wan2'],table='sdwan-vpn-targets',profile='default',mode='prefer',allow_degraded=False));add(a,'ip/firewall/address-list',{'list':'vpn-cold-dns-targets','address':'198.19.100.1'});applied=True;apply(cfg);wait(healthy)
  for wan in before['wans']:blocks.append(add(a,'ip/firewall/filter',{'chain':'output','src-address':wan['address'],'dst-address':wan['icmp_target'],'protocol':'tcp','dst-port':'58081-58083','action':'drop','place-before':'0'}))
  wait(lambda:a.status()['selected']['default']=='none');dns.ready.clear();old=seconds(a.call('system/resource')['uptime']);answers=dns.answers
  try:a.call('system/reboot',{},'POST')
  except (ConnectionError,OSError):pass
  a.close();wait(lambda:seconds(a.call('system/resource')['uptime'])<old,reconnect=True)
  wait(lambda:a.status().get('revision')==cfg['revision'] and a.status()['selected']['default']=='none')
  assert dns.answers==answers;assert a.status()['selected']['vpn-targets']=='none';assert not any(x.get('dynamic')=='true' and x.get('address')=='198.18.100.1' for x in a.call('ip/firewall/address-list/print',{'.proplist':'address,dynamic','.query':['list=sdwan-vpn-endpoint-vpn1']},'POST'));record('cold CHR has no cached endpoint or admitted main WAN while the external DNS fixture withholds all answers')
  dns.ready.set();a.call('ip/dns/cache/flush',{},'POST');wait(healthy);assert a.status()['selected']['default']=='none' and dns.answers>answers
  routes=a.call('ip/route/print',{'.proplist':'dst-address,active,gateway,distance','.query':['comment=sdwan:v1:dns-bootstrap']},'POST');assert any(x.get('dst-address')==dns_ip+'/32' and x.get('active')=='true' and x.get('distance')=='250' for x in routes)
  record('real uncached DNS restores VPN SLA while the ordinary main policy remains closed')
  # Inner SLA becoming healthy precedes both sides' OSPF adjacency convergence.
  wait(lambda:all(sum(x.get('state')=='Full' for x in router.call('routing/ospf/neighbor/print',{'.proplist':'state'},'POST'))==expected for router,expected in ((a,2),(h,4),(traffic.b,2))))
  traffic.prepare();connect_started=time.monotonic();traffic.stream(59410,'sdwan-out-vpn-targets:vpn1',timeout=60);report['cold_tcp_connect_seconds']=round(time.monotonic()-connect_started,3);branch=traffic.stream(59419,'no-mark',target='10.201.1.2');record('uncached real external DNS recovers the preferred VPN through a ready physical WAN while main remains SLA-closed; fresh VPN TCP and branch TCP work')
  packets=guard_packets()
  try:traffic.stream(59411,'sdwan-out-default:wan1',target=dns_ip)
  except AssertionError:pass
  else:raise AssertionError('Closed client policy leaked through the DNS bootstrap host route')
  assert guard_packets()>packets and a.status()['selected']['default']=='none';traffic.assert_sessions(retained=[branch]);record('active main DNS host route cannot bypass the closed default client policy; its unmarked packets hit the terminal drop guard')
  for id in blocks:a.call('ip/firewall/filter/'+id,method='DELETE');created.remove((a,'ip/firewall/filter',id))
  blocks=[];wait(lambda:a.status()['selected']['default']=='wan1');traffic.stream(59412,'sdwan-out-default:wan1',target=dns_ip);record('the same DNS-server destination admits ordinary TCP again after declared physical SLA recovers')

  if doh:
   assert doh.answers>0;assert a.call('ip/dns/print',{'.proplist':'use-doh-server'},'POST')[0]['use-doh-server']=='https://doh-bootstrap-fixture.test:15443/dns-query';report['doh_answers']=doh.answers;record('actual HTTPS DNS with a hostname and custom port bootstraps through existing resolver A cache without changing the configured DoH URL')
  report.update(pass_=True,dns_queries=dns.queries,dns_answers=dns.answers);report['pass']=report.pop('pass_')
 finally:
  try:
   if peer:a.call('interface/wireguard/peers/set',{'numbers':peer['.id'],'endpoint-address':peer['endpoint-address']},'POST')
   a.call('ip/dns/set',original_dns,'POST')
   for r,menu,id in reversed(created):
    try:r.call(menu+'/'+id,method='DELETE')
    except RuntimeError:pass
   if traffic:traffic.close()
   if applied:apply(before)
   assert a.call('ip/dns/print',{'.proplist':'servers,use-doh-server,verify-doh-cert'},'POST')[0]==original_dns
   report['original_dns_settings_restored']=True
  finally:
   if doh:doh.close()
   if dns:dns.close()
   (v.run/('vpn-cold-doh-validation.json' if args.doh else 'vpn-cold-dns-validation.json')).write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()
if __name__=='__main__':main()
