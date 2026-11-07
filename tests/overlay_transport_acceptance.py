#!/usr/bin/env python3
"""CHR ONLY: CGNAT port roaming retires only the prior owned outer UDP tuple.

Reuse the existing five-node lab, keys and branch TCP fixture. No production
access, global conntrack flush, new VMs, or changed VPN authentication.
"""
import argparse,fcntl,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from vpn_lab import VPNLab
from vpn_traffic import VPNTraffic

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];h=v.routers['hub'];traffic=None;nat=None;script=None;scheduler=None;report={'pass':False,'checks':[]};tag='sdwan-overlay-rebind-acceptance'
 def wait(fn,timeout=60):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   value=fn()
   if value:return value
   time.sleep(.2)
  raise AssertionError('Overlay transport condition timed out')
 def record(label):report['checks'].append({'check':label,'pass':True});print('PASS '+label,flush=True)
 def peers():return h.call('interface/wireguard/peers/print',{'.proplist':'interface,current-endpoint-address,current-endpoint-port'},'POST')
 def port():return next(x for x in peers() if x['interface']=='sdwan-wg-sitea-wan1').get('current-endpoint-port')
 def udp(r):return r.call('ip/firewall/connection/print',{'.proplist':'.id,protocol,src-address,src-port,dst-address,dst-port,timeout,connection-mark,orig-bytes,repl-bytes'},'POST')
 def hub_flow(listen,remote_port=None):
  for x in udp(h):
   if x.get('protocol')!='udp':continue
   if x.get('dst-address')=='198.18.100.1' and x.get('dst-port')==str(listen) and x.get('src-address')=='198.18.100.2' and (remote_port is None or x.get('src-port')==str(remote_port)):return x
   if x.get('src-address')=='198.18.100.1' and x.get('src-port')==str(listen) and x.get('dst-address')=='198.18.100.2' and (remote_port is None or x.get('dst-port')==str(remote_port)):return x
  return None
 def clear_nat_binding():
  # Only the selected SiteA WireGuard socket on the emulated ISP. Exact remote
  # and both ports exclude SiteB and unrelated application UDP.
  for x in udp(traffic.n):
   if x.get('protocol')=='udp' and x.get('src-address')=='100.64.10.2' and x.get('src-port')=='51821' and x.get('dst-address')=='198.18.100.1' and x.get('dst-port')=='51821':traffic.n.call('ip/firewall/connection/'+x['.id'],method='DELETE')
 try:
  assert not a.status().get('container',{}).get('active'),'Use native restored baseline'
  for r in (a,h):assert not r.status().get('error') and all(x['healthy'] for x in r.status()['overlay'].values())
  traffic=VPNTraffic(v);traffic.prepare();ordinary=traffic.stream(59410,'sdwan-out-default:wan1',target='198.19.100.2');branch=traffic.stream(59419,'no-mark',target='10.201.1.2')
  assert not traffic.n.call('ip/firewall/nat/print',{'.proplist':'.id','.query':['comment='+tag]},'POST'),'Do not duplicate an existing rebind fixture'
  nat=traffic.n.call('ip/firewall/nat/add',{'chain':'srcnat','src-address':'100.64.10.2','src-port':'51821','dst-address':'198.18.100.1','dst-port':'51821','protocol':'udp','out-interface':'ether2','action':'src-nat','to-addresses':'198.18.100.2','to-ports':'60991','place-before':'0','comment':tag},'POST')['ret'];clear_nat_binding()
  wait(lambda:port()=='60991');wait(lambda:hub_flow(51821,60991));time.sleep(2)
  old=hub_flow(51821,60991);other=hub_flow(51823);assert old and other
  report['old_outer_timeout']=old['timeout'];assert old['timeout'] not in ('0s','1s','2s','3s')
  traffic.assert_sessions(retained=[ordinary,branch]);record('real CGNAT translation is learned by the hub while Internet and branch TCP streams stay established')
  traffic.n.call('ip/firewall/nat/set',{'numbers':nat,'to-ports':'60992'},'POST');start=time.monotonic();clear_nat_binding();wait(lambda:port()=='60992')
  wait(lambda:old['.id'] not in {x['.id'] for x in udp(h)},timeout=10)
  assert hub_flow(51821,60992);assert other['.id'] in {x['.id'] for x in udp(h)}
  report['retirement_seconds']=round(time.monotonic()-start,3);traffic.assert_sessions(retained=[ordinary,branch]);record('authenticated endpoint roaming retires the previous hub UDP tuple in both-direction-aware cleanup, preserving unrelated SiteB UDP and the same TCP streams')
  stable=hub_flow(51821,60992)['.id'];time.sleep(8);assert stable in {x['.id'] for x in udp(h)};traffic.assert_sessions(retained=[ordinary,branch]);record('unchanged transport geometry retains the new UDP conntrack and both established TCP streams')
  # Directly exercise retirement of the real standby socket's saved geometry.
  # This isolates conntrack cleanup; dynamic address changes have separate tests.
  local_ips={x['address'].split('/')[0] for x in a.call('ip/address/print',{'.proplist':'address'},'POST')}
  def owned_outer(x,listen):
   return x.get('protocol')=='udp' and x.get('src-port')==str(listen) and x.get('dst-port')==str(listen) and ((x.get('dst-address')=='198.18.100.1' and x.get('src-address') in local_ips) or (x.get('src-address')=='198.18.100.1' and x.get('dst-address') in local_ips))
  candidates=[x for x in udp(a) if owned_outer(x,51822)]
  assert candidates;previous_ids={x['.id'] for x in candidates};local_sources=[x['src-address'] if x['src-address'] in local_ips else x['dst-address'] for x in candidates];report['standby_original_directions']=['outgoing' if x['src-address'] in local_ips else 'incoming' for x in candidates];report['standby_local_addresses']=local_sources;report['standby_source_differs_from_wan']=any(x!='100.65.10.2' for x in local_sources)
  primary_ids={x['.id'] for x in udp(a) if owned_outer(x,51821)};assert primary_ids
  primary_bytes={x['.id']:int(x['orig-bytes']) for x in udp(a) if x['.id'] in primary_ids}
  # RouterOS may immediately reuse the same conntrack ID for the same UDP
  # tuple. Verify the real helper's removal count rather than requiring a hole
  # long enough for an external API poll to observe a missing identifier.
  # Use the same scheduler environment as the controller. Direct API /run does
  # not share the scheduler's RAM globals, even with identical owner/policies.
  for entry in a.call('system/script/environment/print',{'.proplist':'.id','.query':['name=sdwanOverlayRetireTestCount']},'POST'):a.call('system/script/environment/'+entry['.id'],method='DELETE')
  policy='read,write,policy,test,sensitive'
  assert not a.call('system/scheduler/print',{'.proplist':'.id','.query':['name='+tag]},'POST'),'Do not duplicate a retirement scheduler'
  source='/system/scheduler/disable [/system/scheduler/find where name="'+tag+'"]; :global sdwanOverlayTransport; :global sdwanOverlayRetireTransport; :global sdwanOverlayRetireTestCount; :set sdwanOverlayRetireTestCount [$sdwanOverlayRetireTransport previous=($sdwanOverlayTransport->"hub-wan2")]'
  script=a.call('system/script/add',{'name':tag,'source':source,'policy':policy,'comment':tag},'POST')['ret']
  scheduler=a.call('system/scheduler/add',{'name':tag,'interval':'1s','on-event':'/system/script/run '+tag,'policy':policy,'comment':tag},'POST')['ret']
  result=wait(lambda:a.call('system/script/environment/print',{'.proplist':'value','.query':['name=sdwanOverlayRetireTestCount']},'POST'),timeout=10);assert len(result)==1 and int(result[0]['value'])>=1;report['standby_retired_count']=int(result[0]['value'])
  current={x['.id']:x for x in udp(a)};assert primary_ids<=current.keys();assert all(int(current[id]['orig-bytes'])>=value for id,value in primary_bytes.items());traffic.assert_sessions(retained=[ordinary,branch]);record('explicit standby retirement removes the previous owned outer tuples in either direction while primary UDP counters and established TCP remain')
  report['pass']=True
 finally:
  try:
   if scheduler:a.call('system/scheduler/'+scheduler,method='DELETE')
   if script:a.call('system/script/'+script,method='DELETE')
   for entry in a.call('system/script/environment/print',{'.proplist':'.id','.query':['name=sdwanOverlayRetireTestCount']},'POST'):a.call('system/script/environment/'+entry['.id'],method='DELETE')
   if nat:
    traffic.n.call('ip/firewall/nat/'+nat,method='DELETE');clear_nat_binding()
   if traffic:traffic.close()
  finally:(v.run/'overlay-transport-validation.json').write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()
if __name__=='__main__':main()
