"""Real SIGKILL recovery of already-journaled resources; dedicated Linux lab only."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from sdwan_lab.runtime import Lease,Run,atomic_json,process_start,checked
from sdwan_lab.bench import wait_until

p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--run-id',required=True);a=p.parse_args()
code='''
import sys,time
from sdwan_lab.runtime import Lease,Run,atomic_json
with Lease(sys.argv[1]) as lease:
 r=Run(lease,sys.argv[2],{})
 r.namespace('a');r.namespace('b')
 child=r.spawn([sys.executable,'-c','import time;time.sleep(300)'],'sleeper')
 atomic_json(r.folder/'report.json',{'status':'running','pass':False})
 atomic_json(r.folder/'ready.json',{'pid':child.pid})
 time.sleep(300)
'''
runner=subprocess.Popen([sys.executable,'-c',code,str(a.workspace),a.run_id])
folder=a.workspace/'runs'/a.run_id
try:
 wait_until(lambda:(folder/'ready.json').exists(),10)
 child_pid=json.loads((folder/'ready.json').read_text())['pid']
 original=(folder/'report.json').read_bytes();runner.kill();runner.wait(timeout=5)
 with Lease(a.workspace) as lease:
  r=Run(lease,a.run_id,recover=True);passed=r.cleanup()
 assert passed and process_start(child_pid) is None
 assert (folder/'report.json').read_bytes()==original
 names=checked(['ip','netns','list']).stdout
 assert all(resource['name'] not in names for resource in r.data['resources'] if resource['kind']=='namespace')
 result={'pass':True,'main_exitcode':runner.returncode,'registered_child_stopped':True,'namespaces_removed':True,'original_report_preserved':True,'scope':'SIGKILL after ownership journal committed; ambiguous creation remains a manual-review error'}
 atomic_json(folder/'integration-recovery.json',result);print(json.dumps(result))
finally:
 if runner.poll() is None:runner.kill();runner.wait()
