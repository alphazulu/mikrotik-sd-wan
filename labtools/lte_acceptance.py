"""Fresh CHR DUT + fresh CHR ISP, current RNDIS candidate, TLS IN/OUT and gate."""
import argparse,datetime,hashlib,importlib.util,json,os,re,secrets,socket,ssl,subprocess,sys,threading,time,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from sdwan_lab.runtime import Lease,Run,atomic_json,checked,check_ports,install_signals

from sdwan_lab.usb_repro import qmp,redact_cli

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--image',type=Path,required=True);p.add_argument('--workspace',type=Path,required=True);p.add_argument('--run-id',required=True);p.add_argument('--port-base',type=int,default=25500);a=p.parse_args();a.source=a.source.resolve();a.image=a.image.resolve();sys.path.insert(0,str(a.source))
from sdwan.router import Router
install_signals()
def wait_until(predicate, seconds=10):
 deadline=time.monotonic()+seconds;last=''
 while time.monotonic()<deadline:
  try:
   value=predicate()
   if value:return value
  except (OSError,RuntimeError,ValueError,KeyError) as error:last=str(error)
  time.sleep(.2)
 raise RuntimeError('Readiness deadline expired: '+last)

with Lease(a.workspace) as lease:
 run=Run(lease,a.run_id,{'source':str(a.source),'image':str(a.image),'port_base':a.port_base});folder=run.folder
 report={'pass':False,'steps':[],'scope':'isolated CHR LTE functional test; not controller/performance/RF acceptance','source_files_sha256':{str(p.relative_to(a.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((a.source/'lte-rndis-emu/lte_rndis_emu').glob('*.py'))},'image_sha256':hashlib.sha256(a.image.read_bytes()).hexdigest()}
 passwords=[];routers=[];server=None;server_thread=None
 def save():atomic_json(folder/'report.json',report)
 def step(name,detail=None):report['steps'].append({'name':name,'detail':detail});save();print(name,flush=True)
 def safe(text):
  for password in passwords:text=redact_cli(text,password)
  return text
 def control(data=None):
  req=urllib.request.Request(f'http://127.0.0.1:{a.port_base+4}/lte',data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=5) as response:return json.load(response)
 def vm(name,index,extra):
  disk=folder/(name+'.qcow2');checked(['qemu-img','create','-f','qcow2','-F','raw','-b',a.image,disk,'512M'])
  base=a.port_base+index
  args=['qemu-system-x86_64','-name','sdwan-lte52-'+name+'-'+run.data['token'][:6],'-machine','q35','-accel','kvm','-cpu','host','-m','512','-smp','1','-display','none',
    '-drive',f'file={disk},format=qcow2,if=virtio','-qmp',f'tcp:127.0.0.1:{base},server=on,wait=off','-serial',f'tcp:127.0.0.1:{base+1},server=on,wait=off',
    '-netdev',f'user,id=mgmt,net=10.88.{index}.0/24,dhcpstart=10.88.{index}.15,ipv6=off,hostfwd=tcp:127.0.0.1:{base+2}-10.88.{index}.15:80','-device',f'virtio-net-pci,netdev=mgmt,mac=52:54:00:88:{index:02x}:01']+extra
  atomic_json(folder/(name+'-command.json'),args);return run.spawn(args,name)
 def bootstrap(name,index,commands):
  spec=importlib.util.spec_from_file_location('bootstrap52',a.source/'lab.py');lab=importlib.util.module_from_spec(spec);spec.loader.exec_module(lab);lab.RUN=folder
  password=secrets.token_urlsafe(24);passwords.append(password)
  credentials_path=folder/'credentials.json';credentials=json.loads(credentials_path.read_text()) if credentials_path.exists() else {};credentials[name]={'username':'admin','password':password};credentials_path.write_text(json.dumps(credentials));credentials_path.chmod(0o600)
  con=lab.Console.__new__(lab.Console);con.name=name;con.buffer=''
  def connect():
   try:con.s=socket.create_connection(('127.0.0.1',a.port_base+index+1),timeout=1);return True
   except OSError:return False
  wait_until(connect,10);con.s.settimeout(1)
  try:con.configure(['/system/identity/set name=sdwan-lte52-'+name,'/ip/dhcp-client/remove [find where dynamic=no]',f'/ip/address/add address=10.88.{index}.15/24 interface=ether1',f'/ip/service/set www disabled=no address=10.88.{index}.0/24']+commands,password)
  finally:con.s.close()
  router=Router(folder,f'http://127.0.0.1:{a.port_base+index+2}',credentials_data={'username':'admin','password':password});routers.append(router)
  wait_until(lambda:router.call('system/resource'),30);return router
 try:
  save();check_ports([a.port_base+i for i in (0,1,2,3,4,6,10,11,12)])
  probe=subprocess.run([sys.executable,'-m','lte_rndis_emu','probe'],cwd=a.source/'lte-rndis-emu',capture_output=True,text=True,check=True,timeout=15)
  atomic_json(folder/'probe.json',json.loads(probe.stdout));assert json.loads(probe.stdout)['decision']['path']=='usbredir-userspace'
  enum=subprocess.run([sys.executable,'-m','lte_rndis_emu','enumerate','--json'],cwd=a.source/'lte-rndis-emu',capture_output=True,text=True,check=True,timeout=15);(folder/'enumerate.json').write_text(enum.stdout)
  tap=run.tap();checked(['sh',a.source/'lte-rndis-emu/scripts/prepare-uplink.sh',tap]);report['tap']=tap;save()
  # Start the actual candidate; all endpoints loopback. No gadget/usbip path.
  emu_args=[sys.executable,'-u',str(folder/'emu-entry.py')]
  (folder/'emu-entry.py').write_text('import sys\nsys.path.insert(0,'+repr(str(a.source/'lte-rndis-emu'))+')\nfrom lte_rndis_emu.emulator import main\nraise SystemExit(main('+repr(['serve','--uplink',tap,'--listen',f'127.0.0.1:{a.port_base+3}','--control',f'127.0.0.1:{a.port_base+4}','--gate'])+'))\n')
  emu=run.spawn(emu_args,'emulator');wait_until(lambda:emu.poll() is None and 'ready usbredir=' in (folder/'emulator.stdout').read_text(),15);step('serve ready before either new QEMU',control())
  capture=run.spawn(['tcpdump','-n','-U','-i',tap,'-w',folder/'traffic.pcap'],'capture')
  offload='csum=off,gso=off,guest_csum=off,guest_tso4=off,guest_tso6=off,guest_ecn=off,guest_ufo=off,host_tso4=off,host_tso6=off,host_ecn=off,host_ufo=off'
  isp_process=vm('isp',10,['-netdev',f'tap,id=lte,ifname={tap},script=no,downscript=no,vnet_hdr=off','-device','virtio-net-pci,netdev=lte,mac=52:54:00:88:0a:02,'+offload])
  isp=bootstrap('isp',10,['/ip/route/add dst-address=0.0.0.0/0 gateway=10.88.10.2','/ip/address/add address=192.0.2.1/24 interface=ether2','/ip/address/add address=198.18.80.1/32 interface=lo','/ip/pool/add name=lte ranges=192.0.2.10-192.0.2.50','/ip/dhcp-server/network/add address=192.0.2.0/24 gateway=192.0.2.1','/ip/dhcp-server/add name=lte interface=ether2 address-pool=lte disabled=no','/ip/firewall/nat/add chain=srcnat out-interface=ether1 action=masquerade'])
  step('ISP bootstrap completed')
  dut_process=vm('dut',0,['-device','qemu-xhci,id=xhci','-chardev',f'socket,id=lteusb,host=127.0.0.1,port={a.port_base+3}','-device','usb-redir,chardev=lteusb,id=lte-rndis,bus=xhci.0'])
  dut=bootstrap('dut',0,[]);lte=[];step('DUT bootstrap completed')
  def find_lte():
   return [r for r in dut.call('interface/lte') if r.get('running')=='true' and r.get('inactive')=='false']
  lte=wait_until(find_lte,90);assert len(lte)==1;iface=lte[0]
  atomic_json(folder/'router-lte.json',lte);atomic_json(folder/'qemu-usb.json',qmp(a.port_base,'human-monitor-command',{'command-line':'info usb'}))
  for name,path in [('usb','system/resource/usb'),('hardware','system/resource/hardware')]:
   try:answer=dut.call(path+'/print',{},'POST')
   except RuntimeError as error:answer={'unsupported':str(error)}
   atomic_json(folder/('router-'+name+'.json'),answer)
  hw=dut.call('system/resource/hardware');assert any(r.get('type')=='usb' and r.get('vendor-id')=='0x12d1' and r.get('device-id')=='0x14db' for r in hw)
  profile=dut.call('interface/lte/apn',{'name':'sdwan-lte52','apn':'internet','add-default-route':'no','use-peer-dns':'no'},'PUT')
  dut.call('interface/lte/'+iface['.id'],{'apn-profiles':'sdwan-lte52'},'PATCH')
  def bound():
   rows=dut.call('ip/dhcp-client');atomic_json(folder/'dhcp-observation.json',rows)
   return next((r for r in rows if r.get('interface')==iface['name'] and r.get('status')=='bound'),None)
  wait_until(bound,90);address=bound();assert address['dynamic']=='true' and address.get('add-default-route') in ('false','no',False) and address.get('use-peer-dns') in ('false','no',False),address;atomic_json(folder/'dynamic-dhcp.json',address);src=address['address'].split('/')[0]
  for dst in ['198.18.80.1/32','1.1.1.1/32','10.88.10.2/32']:dut.call('ip/route',{'dst-address':dst,'gateway':'192.0.2.1%'+iface['name'],'comment':'sdwan-lte52'},'PUT')
  def ping():
   rows=dut.call('ping',{'address':'198.18.80.1','interface':iface['name'],'count':'3','interval':'200ms'},'POST');return sum('time' in r and not r.get('status') for r in rows)
  wait_until(lambda:ping()==3,30);step('CHR USB/LTE/APN-controlled DHCP and ICMP proven',address)
  before=control()['counters']
  internet=dut.call('tool/fetch',{'url':'https://1.1.1.1/cdn-cgi/trace','src-address':src,'output':'none','duration':'15s','idle-timeout':'10s'},'POST');assert any(r.get('status')=='finished' for r in (internet if isinstance(internet,list) else [internet]));step('public HTTPS fetch through pinned LTE source/route',internet)
  checked(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',folder/'test-key.pem','-out',folder/'test-cert.pem','-days','1','-subj','/CN=lte-bench.example.test']);(folder/'test-key.pem').chmod(0o600)
  class Handler(BaseHTTPRequestHandler):
   protocol_version='HTTP/1.1'
   def do_GET(self):
    blob=b'synthetic-lte-test-'*8192;self.send_response(200);self.send_header('Content-Length',str(len(blob)));self.end_headers();self.wfile.write(blob);self.server.get_count+=1;self.server.sent_bytes+=len(blob)
   def do_POST(self):
    data=self.rfile.read(int(self.headers.get('Content-Length','0')))
    if data!=b'x'*32768:self.server.bad_body+=1;self.send_error(400);return
    self.server.post_count+=1;self.server.received_bytes+=len(data);self.send_response(200);self.send_header('Content-Length','2');self.end_headers();self.wfile.write(b'ok')
   def log_message(self,*args):pass
  server=ThreadingHTTPServer(('127.0.0.1',a.port_base+6),Handler)
  server.get_count=server.post_count=server.sent_bytes=server.received_bytes=server.bad_body=0
  ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(folder/'test-cert.pem',folder/'test-key.pem');server.socket=ctx.wrap_socket(server.socket,server_side=True)
  server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
  report['tls_runs']=[]
  for i in range(40):
   for method in ['get','post']:
    attrs={'url':f'https://10.88.10.2:{a.port_base+6}/data','src-address':src,'output':'none','http-method':method,'check-certificate':'no'}
    if method=='post':attrs['http-data']='x'*32768
    value=dut.call('tool/fetch',attrs,'POST');assert any(r.get('status')=='finished' for r in (value if isinstance(value,list) else [value]));report['tls_runs'].append({'iteration':i,'method':method,'result':value});save()
  assert server.get_count==40 and server.post_count==40 and server.bad_body==0
  step('TLS bulk IN and OUT body-validated',{'get_count':server.get_count,'post_count':server.post_count,'sent_bytes':server.sent_bytes,'received_bytes':server.received_bytes,'bad_body':server.bad_body,'test_certificate_validation':'disabled only for local synthetic certificate'})
  after=control()['counters'];assert after['rx_frames']>before['rx_frames'] and after['tx_frames']>before['tx_frames'];step('real TAP/RNDIS frames both directions',{'before':before,'after':after})
  control({'registration_status':'searching'});time.sleep(1);blocked=ping();assert blocked==0;step('gate blocks traffic',{'received':blocked})
  control({'registration_status':'registered'});wait_until(lambda:ping()==3,60);step('gate recovery',{'received':3});report['pass']=True
 except BaseException as error:
  report['error']=safe(type(error).__name__+': '+str(error))
  for label,router in zip(['isp','dut'],routers):
   for menu in ['ip/address','ip/dhcp-client','ip/dhcp-server','ip/dhcp-server/lease','interface/lte/apn','interface/lte']:
    try:atomic_json(folder/(label+'-'+menu.replace('/','-')+'.json'),router.call(menu))
    except Exception:pass
  try:atomic_json(folder/'emulator-final.json',control())
  except Exception:pass
 finally:
  if server is not None:server.shutdown();server.server_close()
  if server_thread is not None:server_thread.join(timeout=2)
  for router in routers:router.close()
  report['cleanup_pass']=run.cleanup();report['pass'] &= report['cleanup_pass'];report['image_unchanged']=hashlib.sha256(a.image.read_bytes()).hexdigest()==report['image_sha256'];save();print(json.dumps({k:v for k,v in report.items() if k not in ('source_files_sha256','tls_runs','steps')},indent=2))
 raise SystemExit(0 if report['pass'] else 1)
