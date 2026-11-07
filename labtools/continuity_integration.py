"""Dedicated namespace control and real egress blackhole. No MikroTik configuration."""
import json,sys,time
from pathlib import Path
from sdwan_lab.runtime import Lease,Run,atomic_json,install_signals
from sdwan_lab.bench import Network,wait_until

workspace=Path(sys.argv[1]);name=sys.argv[2];install_signals()
with Lease(workspace) as lease:
 run=Run(lease,name,{'scope':'external generator control/drop integration only'})
 result={'pass':False,'cases':[]}
 try:
  net=Network(run,'198.18.251.0/30')
  server=run.spawn(net.argv(1,[sys.executable,'-W','error::ResourceWarning','-m','sdwan_lab.continuity','serve','--listen',net.ips[1],'--port','25351']),'echo-server')
  wait_until(lambda:'ready' in (run.folder/'echo-server.stdout').read_text(),5)
  for label,drop in ([('reconnect',False)] if len(sys.argv)>3 and sys.argv[3]=='reconnect' else [('control',False),('blackhole',True)]):
   path=run.folder/(label+'.json')
   child=run.spawn(net.argv(0,[sys.executable,'-W','error::ResourceWarning','-m','sdwan_lab.continuity','measure','--host',net.ips[1],'--port','25351','--seconds','8','--interval-ms','20','--output',path]),label)
   wait_until(lambda:'ESTAB' in net.call(0,['ss','-Htn']).stdout,5)
   markers={}
   if drop:
    time.sleep(1);net.call(0,['tc','qdisc','replace','dev','eth0','root','netem','loss','100%']);markers['drop_start']=time.monotonic_ns()
    time.sleep(2);net.call(0,['tc','qdisc','del','dev','eth0','root']);markers['drop_end']=time.monotonic_ns()
   if label=='reconnect':
    time.sleep(1);run.stop(server.pid)
    time.sleep(.5);server=run.spawn(net.argv(1,[sys.executable,'-m','sdwan_lab.continuity','serve','--listen',net.ips[1],'--port','25351']),'echo-restarted')
   assert child.wait(timeout=20)==0
   data=json.loads(path.read_text());udp=data['protocols']['udp'];tcp=data['protocols']['tcp']
   assert udp['received']>0 and tcp['received']>0
   if label=='reconnect':
    assert tcp['established_sessions']>=2 and tcp['disconnects']>=1
    assert any(e['protocol']=='tcp' and e['event']=='received' and e['session']>=2 for e in data['events'])
   else:assert tcp['established_sessions']==1 and tcp['disconnects']==0
   if drop:
    assert udp['unanswered']>30 and udp['max_success_gap_ms']>=1500 and tcp['max_success_gap_ms']>=1500
    end=markers['drop_end']-data['origin_monotonic_ns']
    assert all(any(e['protocol']==proto and e['event']=='received' and e['ns']>end for e in data['events']) for proto in ['udp','tcp'])
   elif label=='control':assert udp['unanswered']==0 and tcp['unanswered']==0
   result['cases'].append({'name':label,'pass':True,'markers_monotonic_ns':markers,'protocols':data['protocols']})
  result['pass']=True
 except BaseException as error:result['error']=type(error).__name__+': '+str(error)
 finally:
  result['cleanup_pass']=run.cleanup();result['pass'] &= result['cleanup_pass'];atomic_json(run.folder/'report.json',result)
 print(json.dumps(result,indent=2));raise SystemExit(0 if result['pass'] else 1)
