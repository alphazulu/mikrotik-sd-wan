#!/usr/bin/env python3
"""CHR ONLY: real ordered group/port/protocol/VLAN traffic and diagnostics."""
import contextlib,copy,importlib.util,io,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lab
from sdwan.config import load,validate
from sdwan.router import Router
from sdwan.diagnostics import read,explain
from stream_traffic import StreamTraffic
spec=importlib.util.spec_from_file_location('cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
 r=Router(ROOT,'api://127.0.0.1:18728');base=load(ROOT/'config/sdwan.json');backup=r.read_file('sdwan-backup.json');resources=[];traffic=None;remote=None;forward=False;report={'checks':[]}
 def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
 def add(node,menu,data):
  data=dict(data)
  if menu not in ('routing/table',):data.setdefault('comment','policies-acceptance-only')
  row=lab.api(node,menu,data,'PUT');resources.append((node,menu,row['.id']))
  if menu.startswith('ip/firewall/'):
   end=time.monotonic()+5
   while lab.api(node,menu+'/'+row['.id']).get('invalid')=='true':
    if time.monotonic()>end:raise AssertionError('Invalid fixture rule')
    time.sleep(.1)
  return row['.id']
 def wait(predicate,timeout=65):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   s=r.status()
   if s.get('error'):raise AssertionError(s)
   if predicate(s):return s
   time.sleep(.3)
  raise AssertionError(s)
 def healthy():return wait(lambda s:s.get('states') and all(x['state']=='healthy' for x in s['states'].values()))
 def apply(c):
  validate(c)
  with contextlib.redirect_stdout(io.StringIO()):cli.apply(r,c,'sdwan-edge')
  healthy()
 def udp():
  trace=lab.api('client','tool/traceroute',{'address':'203.0.113.200','src-address':'192.168.50.101','protocol':'udp','port':'33434','size':'64','max-hops':'3','count':'1','timeout':'300ms','use-dns':'no'},'POST')
  end=time.monotonic()+3
  while time.monotonic()<end:
   for row in r.call('ip/firewall/connection'):
    if row.get('src-address')=='192.168.50.101' and row.get('dst-address')=='203.0.113.200' and row.get('protocol')=='udp' and row.get('dst-port')=='33434':return row
   time.sleep(.1)
  raise AssertionError({'trace':trace,'classifiers':[x for x in r.call('ip/firewall/mangle') if x.get('comment','').startswith(('sdwan:v1:classify:udp-service:','sdwan:v1:guard:udp-service','sdwan:v1:classify:client101:'))]})

 try:
  assert all(lab.api(n,'system/identity')['name']=='sdwan-'+n for n in lab.NODES)
  for node,interface in (('edge','ether5'),('client','ether2')):add(node,'interface/vlan',{'name':'sdwan-test-voice-vlan','interface':interface,'vlan-id':'993'})
  add('edge','ip/address',{'address':'192.168.60.1/24','interface':'sdwan-test-voice-vlan'})
  add('client','ip/address',{'address':'192.168.60.101/24','interface':'sdwan-test-voice-vlan'})
  add('client','routing/table',{'name':'sdwan-test-client-vlan','fib':'true'})
  add('client','ip/route',{'dst-address':'0.0.0.0/0','gateway':'192.168.60.1%sdwan-test-voice-vlan','routing-table':'sdwan-test-client-vlan'})
  add('client','routing/rule',{'src-address':'192.168.60.101/32','table':'sdwan-test-client-vlan','action':'lookup-only-in-table'})
  add('edge','ip/firewall/filter',{'chain':'forward','in-interface':'sdwan-test-voice-vlan','out-interface-list':'WAN','action':'accept','place-before':'0'})
  for n in (1,2,3):add('isp'+str(n),'ip/firewall/nat',{'chain':'dstnat','dst-address':'203.0.113.200','protocol':'tcp','dst-port':'29100-29120','action':'dst-nat','to-addresses':f'10.77.{n}.2'})
  for node,data,menu in [('edge',{'chain':'input','in-interface':'ether4','src-address':'10.77.3.0/24','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0'},'ip/firewall/filter'),('isp3',{'chain':'forward','in-interface':'ether1','dst-address':'172.20.3.2','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0'},'ip/firewall/filter'),('isp3',{'chain':'dstnat','in-interface':'ether1','protocol':'tcp','dst-port':'29996','action':'dst-nat','to-addresses':'172.20.3.2','to-ports':'8728'},'ip/firewall/nat')]:add(node,menu,data)
  result=lab.qmp('isp3','human-monitor-command',{'command-line':'hostfwd_add mgmt tcp:127.0.0.1:18996-10.77.3.15:29996'});assert not result,result
  forward=True;remote=Router(ROOT,'api://127.0.0.1:18996');assert remote.call('system/identity')['name']=='sdwan-edge'
  cfg=copy.deepcopy(base);cfg['revision']='policies-v1';cfg['local_networks'].append('192.168.60.0/24');cfg['groups']={'phones':['192.168.50.101/32'],'services':['203.0.113.200/32']}
  for p in cfg['sla_profiles'].values():p['jitter_ms']=100
  for i,p in enumerate(cfg['policies'][1:],1):p['priority']=100+i*10
  def policy(name,**kw):return dict(name=name,source='0.0.0.0/0',table='sdwan-'+name,profile='default',mode='strict',wans=['wan3'],allow_degraded=False,**kw)
  cfg['policies'] += [policy('web',priority=10,source_group='phones',destination='203.0.113.0/24',destination_group='services',in_interface='ether5',protocol='tcp',src_ports='1-65535',dst_ports='29100-29110'),policy('udp-service',priority=20,source_group='phones',destination_group='services',in_interface='ether5',protocol='udp',dst_ports='33434'),policy('voice-vlan',priority=5,in_interface='sdwan-test-voice-vlan',protocol='tcp',dst_ports='29100-29120')]
  web=cfg['policies'][-3];web.update(mode='prefer',wans=['wan2','wan1'])
  apply(cfg)
  rules=r.call('ip/firewall/mangle');tags=[x.get('comment') for x in rules]
  assert tags.index('sdwan:v1:classify:voice-vlan:wan3')<tags.index('sdwan:v1:classify:web:wan2')<tags.index('sdwan:v1:classify:client101:wan1')<tags.index('sdwan:v1:classify:default:wan1')
  assert not any(x.get('comment')=='sdwan:v1:client:web' for x in r.call('routing/rule'))
  assert any(x.get('comment')=='sdwan:v1:policy-blackhole:web' and 'blackhole' in x for x in r.call('ip/route'))
  record('native priority order, address groups and exact fail-closed guards installed; composite selectors have no broad source rule')
  traffic=StreamTraffic(r,add)
  first=traffic.stream('192.168.50.101','wan2',29100,policy='web')['.id']
  ordinary=traffic.stream('192.168.50.101','wan1',29112)['.id']
  other=traffic.stream('192.168.50.102','wan2',29101)['.id']
  vlan=traffic.stream('192.168.60.101','wan3',29113,policy='voice-vlan')['.id']
  record('real concurrent TCP/NAT flows follow group+destination+port rules, unmatched ports/clients and tagged VLAN ingress')
  assert udp()['connection-mark']=='sdwan-out-udp-service:wan3'
  record('real UDP traceroute uses UDP-specific policy without inheriting the TCP application rule')
  snapshot,active=read(r);assert not snapshot['telemetry_stale'] and len(snapshot['wans'])==3 and len(snapshot['policies'])==7
  assert all(w['sample_age_seconds'] is not None and w['interface'] for w in snapshot['wans'])
  assert all(x['hold_remaining_seconds'] is not None and x['recover_windows_remaining'] is not None for x in snapshot['sla'])
  assert snapshot['events'] and len(snapshot['events'])<=100
  assert explain(active,snapshot,source='192.168.50.101',destination='203.0.113.200',protocol='tcp',src_port=50000,dst_port=29100,in_interface='ether5')['selected']=='wan2'
  (ROOT/'runtime/policies-active-config.json').write_text(json.dumps(cfg,indent=2)+'\n');(ROOT/'runtime/policies-diagnostics-snapshot.json').write_text(json.dumps(snapshot,indent=2)+'\n')
  record('read-only diagnostic view exposes ages, recovery timers, policy reasons and bounded events; new-flow explanation agrees with CHR')
  gui=subprocess.run(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-Command',r'& "E:\ProgramData\anaconda3\python.exe" "C:\Project\Mikrotik\SD-WAN\tests\gui_policies_diagnostics_smoke.py"'],capture_output=True,text=True,timeout=100)
  print(gui.stdout,flush=True);assert gui.returncode==0,gui.stderr
  record('Windows GUI reads live diagnostics, edits groups/ordered selectors, explains flows and exports without changing router configuration')
  old=[first,ordinary,other,vlan];cfg['groups']['phones']=['192.168.50.102/32'];apply(cfg)
  traffic.assert_sessions(absent=old);[traffic.stop_stream(cid) for cid in old];assert remote.call('system/identity')['name']=='sdwan-edge'
  first=traffic.stream('192.168.50.101','wan1',29100)['.id'];other=traffic.stream('192.168.50.102','wan2',29101,policy='web')['.id']
  record('group membership edit reclassifies managed outbound flows; incoming API survives and fresh clients use updated groups')
  apply(cfg);traffic.assert_sessions(retained=[first,other]);assert remote.call('system/identity')['name']=='sdwan-edge'
  record('idempotent reapply preserves established client connections when selector order/groups are unchanged')
  web['priority']=500;apply(cfg);traffic.stop_stream(first);traffic.stop_stream(other)
  changed=traffic.stream('192.168.50.102','wan2',29102)['.id'];traffic.stop_stream(changed)
  record('explicit rule reorder changes the winning policy before a new connection, including same-WAN cases')
  web.update(priority=10,protocol='any',dst_ports='',src_ports='');cfg['groups']['phones']=['192.168.50.101/32'];apply(cfg)
  row=next(x for x in r.call('ip/firewall/mangle') if x.get('comment')=='sdwan:v1:classify:web:wan2')
  assert not row.get('protocol') and not row.get('dst-port') and not row.get('src-port'),row
  assert udp()['connection-mark']=='sdwan-out-web:wan2'
  record('removing protocol/port restrictions leaves no stale native matcher; real UDP is reclassified by the updated higher rule')
  web.update(mode='strict',wans=['wan2']);apply(cfg)
  vlan=traffic.stream('192.168.60.101','wan3',29114,policy='voice-vlan')['.id']
  counters=[(n,add('isp'+str(n),'ip/firewall/raw',{'chain':'prerouting','protocol':'icmp','dst-address':'203.0.113.200','action':'passthrough'})) for n in (1,3)]
  lab.proxy_request({'wan':'wan2','set':{'blackhole':True}});wait(lambda s:s['selected']['web']=='none')
  rows=lab.api('client','ping',{'address':'203.0.113.200','src-address':'192.168.50.101','count':'2'},'POST');assert int(rows[-1]['received'])==0
  for n,counter in counters:assert lab.api('isp'+str(n),'ip/firewall/raw/'+counter).get('packets','0')=='0'
  assert int(next(x for x in r.call('ip/firewall/mangle') if x.get('comment')=='sdwan:v1:guard:web')['packets'])>0
  traffic.assert_sessions(retained=[vlan]);assert remote.call('system/identity')['name']=='sdwan-edge'
  record('strict composite policy fails closed without leakage to healthy WAN1/WAN3; VLAN traffic and incoming API survive')
  lab.proxy_request({'reset':True});healthy();wait(lambda s:s['selected']['web']=='wan2')
  events=r.status()['events'];assert any(x.get('type')=='policy' and x.get('policy')=='web' and x.get('to')=='none' for x in events)
  record('controller history records application outage and recovery using the local bounded RAM journal')
  previous_count=r.status()['conntrack_removed']
  removed=traffic.stream('192.168.50.101','wan2',29108,policy='web')['.id']
  cfg['policies']=[p for p in cfg['policies'] if p['name']!='web'];apply(cfg)
  traffic.assert_sessions(absent=[removed]);traffic.stop_stream(removed)
  assert r.status()['conntrack_removed']>previous_count and remote.call('system/identity')['name']=='sdwan-edge'
  record('removing a policy retires its exact outbound marks, counts the removed connections and preserves incoming API')
  traffic.close();traffic=None;remote.close();remote=None
  with contextlib.redirect_stdout(io.StringIO()):cli.rollback(r,'sdwan-edge')
  assert not any(x.get('comment','').startswith('sdwan:v1:group:') for x in r.call('ip/firewall/address-list'))
  assert not any(x.get('comment','').startswith('sdwan:v1:policy-blackhole:') for x in r.call('ip/route'))
  record('baseline rollback removes owned groups, selector rules and policy blackholes')
 except Exception as error:
  print('FAIL policy acceptance: '+str(error),flush=True)
  report['checks'].append({'check':'policy acceptance interrupted','pass':False,'detail':str(error)});raise
 finally:
  lab.proxy_request({'reset':True})
  if traffic:traffic.close()
  if remote:remote.close()
  if forward:lab.qmp('isp3','human-monitor-command',{'command-line':'hostfwd_remove mgmt tcp:127.0.0.1:18996'})
  r.close()
  try:apply(base);r.upload('sdwan-backup.json',backup)
  finally:
   for node,menu,identifier in reversed(resources):
    try:lab.api(node,menu+'/'+identifier,method='DELETE')
    except RuntimeError as error:
     if '404' not in str(error):raise
   (ROOT/'runtime/policies-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()

if __name__=='__main__':main()
