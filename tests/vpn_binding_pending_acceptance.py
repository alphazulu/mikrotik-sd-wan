#!/usr/bin/env python3
"""CHR ONLY: deferred VPN FIB binding is isolated, polled and safely reverted."""
import argparse,contextlib,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);r=v.routers['sitea'];before=json.loads(r.read_file('sdwan-active.json'));cfg=json.loads((v.root/'config/overlay-sitea-container.json').read_text());name='vpn-pending-acceptance';created=[];applied=False;report={'pass':False};output='sdwanPendingAcceptanceJSON'
 spec=importlib.util.spec_from_file_location('vpn_pending_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 def apply(c):
  with (v.run/'vpn-pending-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(r,c,'sdwan-overlay-sitea')
 def wait(fn,timeout=60):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   value=fn()
   if value:return value
   time.sleep(.2)
  raise AssertionError('Deferred VPN binding condition timed out')
 try:
  assert not r.call('system/script/print',{'.proplist':'.id','.query':['name='+name]},'POST'),'Previous pending test must not be duplicated'
  applied=True;apply(cfg);wait(lambda:r.status().get('states',{}).get('default/vpn2',{}).get('state')=='healthy');prior_uptime=r.status()['uptime_seconds']
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+output]},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
  source='''/system/scheduler/disable [/system/scheduler/find where name="vpn-pending-acceptance"]
:global sdwanPendingAcceptanceJSON
:global sdwanRuntimeWANs
:global sdwanReconcileWANs
:global sdwanLinkPending
/system/scheduler/disable [/system/scheduler/find where name="sdwan-controller"]
:delay 1200ms
:onerror failure in={
 :local cfg [:deserialize from=json options=json.no-string-conversion value=[/file/get [/file/find where name="sdwan-active.json"] contents]]
 :local wans $sdwanRuntimeWANs
 :foreach index,wan in=$wans do={ :if (($wan->"name") = "vpn2") do={ :set ($wan->"route_gateway") "192.0.2.1%ether2@main"; :set ($wans->$index) $wan } }
 :local first [$sdwanReconcileWANs wans=$wans policies=($cfg->"policies") health=($cfg->"health")]
 :if (([:typeof ($sdwanLinkPending->"vpn2")] != "array") || ((($first->"vpn2")->"ready") != false)) do={ :error "unsafe VPN binding was not deferred" }
 :local pin [:tostr [/routing/rule/find where comment="sdwan:v1:pinrule:vpn2"]]
 :local probes [:tostr [/tool/netwatch/find where comment="sdwan:v1:icmp:vpn2"]]
 :local second [$sdwanReconcileWANs wans=$wans policies=($cfg->"policies") health=($cfg->"health")]
 :if (([:len $second] != 0) || ($pin != [:tostr [/routing/rule/find where comment="sdwan:v1:pinrule:vpn2"]]) || ($probes != [:tostr [/tool/netwatch/find where comment="sdwan:v1:icmp:vpn2"]])) do={ :error "pending VPN polling rebuilt bindings" }
 :set sdwanPendingAcceptanceJSON "{\\"pass\\":true}"
} do={ :set sdwanPendingAcceptanceJSON [:serialize to=json value={"error"=$failure} options=json.no-string-conversion] }
# The unchanged active geometry now replaces the synthetic pending geometry.
# The actual controller must rebuild it and apply its fresh-probe barrier.
/system/scheduler/enable [/system/scheduler/find where name="sdwan-controller"]
'''
  for menu,data in [('system/script',{'name':name,'source':source,'policy':'read,write,policy,test,sensitive','comment':name}),('system/scheduler',{'name':name,'interval':'1s','on-event':'/system/script/run '+name,'policy':'read,write,policy,test,sensitive','comment':name})]:
   done=r.call(menu+'/add',data,'POST');created.append((menu,done['ret']))
  def result():
   rows=r.call('system/script/environment/print',{'.proplist':'value','.query':['name='+output]},'POST');return json.loads(rows[0]['value']) if rows and rows[0].get('value','').startswith('{') else None
  result=wait(result);assert result.get('pass'),result;print('PASS unavailable VPN forwarding geometry is deferred without aborting other WAN reconciliation; repeated pending checks preserve binding/probe identities',flush=True)
  def recovered():
   s=r.status();return s.get('uptime_seconds',0)>prior_uptime+3 and s.get('states',{}).get('default/vpn2',{}).get('state')=='healthy' and s.get('selected',{}).get('default')=='wan1' and not s.get('samples',{}).get('vpn2',{}).get('warming',True)
  wait(recovered)
  assert '192.0.2.1' not in r.call('system/script/environment/print',{'.proplist':'value','.query':['name=sdwanLinkPending']},'POST')[0].get('value','')
  assert all(x['healthy'] for x in r.status()['overlay'].values());print('PASS reverting to the last published geometry clears pending state and requires fresh VPN SLA while main and private paths stay healthy',flush=True);report={'pass':True,'checks':2}
 finally:
  r.call('system/scheduler/set',{'numbers':'sdwan-controller','disabled':'false'},'POST')
  for menu,id in reversed(created):r.call(menu+'/'+id,method='DELETE')
  for row in r.call('system/script/environment/print',{'.proplist':'.id','.query':['name='+output]},'POST'):r.call('system/script/environment/'+row['.id'],method='DELETE')
  try:
   if applied:apply(before)
  finally:(v.run/'vpn-binding-pending-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
