"""Privileged FD/TAP transport check entirely within two owned namespaces."""
import argparse,json,os,select,threading,time
from pathlib import Path
from sdwan_lab.namespace_tap import open_tap
from sdwan_lab.runtime import Lease,Run,atomic_json,checked,install_signals

p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--run-id',required=True);a=p.parse_args();install_signals()
with Lease(a.workspace) as lease:
 run=Run(lease,a.run_id,{});fds=[];stop=threading.Event();thread=None;errors=[];counts=[0,0];report={'pass':False,'scope':'Linux namespace TAP descriptor transport only; no DUT/performance claim'}
 try:
  names=[run.namespace('a'),run.namespace('b')]
  for i,name in enumerate(names):
   descriptor=open_tap(run,name,'eth0');fds.append(descriptor);os.set_blocking(descriptor,False)
   checked(['ip','netns','exec',name,'sysctl','-qw','net.ipv6.conf.eth0.disable_ipv6=1'])
   checked(['ip','-n',name,'link','set','lo','up']);checked(['ip','-n',name,'addr','add',f'198.18.252.{i+1}/30','dev','eth0']);checked(['ip','-n',name,'link','set','eth0','up'])
   checked(['ip','netns','exec',name,'ethtool','-K','eth0','tso','off','gso','off','gro','off'])
  def relay():
   try:
    while not stop.is_set():
     readable,_,_=select.select(fds,[],[],.05)
     for fd in readable:
      frame=os.read(fd,65536);index=fds.index(fd)
      if frame:os.write(fds[1-index],frame);counts[index]+=1
   except BaseException as e:errors.append(type(e).__name__+': '+str(e))
  thread=threading.Thread(target=relay,daemon=True);thread.start()
  ping=run.spawn(['ip','netns','exec',names[0],'ping','-c','3','-i','.2','-W','2','198.18.252.2'],'ping')
  assert ping.wait(timeout=10)==0,(run.folder/'ping.stdout').read_text()
  assert min(counts)>0 and not errors;report.update(**{'pass':True,'frames_each_direction':counts,'ping':(run.folder/'ping.stdout').read_text()})
 except BaseException as e:report['error']=type(e).__name__+': '+str(e)
 finally:
  stop.set()
  if thread is not None:thread.join(timeout=2)
  for descriptor in fds:os.close(descriptor)
  report['relay_errors']=errors;report['cleanup_pass']=run.cleanup();report['pass'] &= report['cleanup_pass'] and not errors;atomic_json(run.folder/'report.json',report)
 print(json.dumps(report,indent=2));raise SystemExit(0 if report['pass'] else 1)
