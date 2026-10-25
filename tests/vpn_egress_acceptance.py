#!/usr/bin/env python3
"""Existing isolated CHRs only: optional VPN uses common SLA/priority engine."""
import argparse,contextlib,copy,fcntl,importlib.util,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from vpn_lab import VPNLab
from sdwan.config import validate

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);p.add_argument('--only-reapply',action='store_true');p.add_argument('--reapply',action='store_true');p.add_argument('--traffic',action='store_true');p.add_argument('--protocol',choices=['wireguard','l2tp','sstp','openvpn'],default='wireguard');args=p.parse_args();v=VPNLab(args.lab_root);lock=(v.run/'lab.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);a=v.routers['sitea'];h=v.routers['hub'];report={'checks':[],'pass':False};created=[];disabled=None;applied=False;traffic=None
 spec=importlib.util.spec_from_file_location('vpn_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
 before=json.loads(a.read_file('sdwan-active.json'));(v.run/'vpn-before.json').write_text(json.dumps(before,indent=2)+'\n')
 def record(s):report['checks'].append({'check':s,'pass':True});print('PASS '+s,flush=True)
 def wait(fn,timeout=65):
  end=time.monotonic()+timeout;last={}
  while time.monotonic()<end:
   last=a.status()
   if last.get('error'):raise AssertionError(last['error'])
   if fn(last):return last
   time.sleep(.3)
  raise AssertionError(last)
 def apply(c):
  with (v.run/'vpn-protected-apply.log').open('a') as log,contextlib.redirect_stdout(log):cli.apply(a,validate(c),'sdwan-overlay-sitea')
 try:
  cfg=copy.deepcopy(before);cfg['revision']='vpn-'+args.protocol+'-egress-fixture';cfg['vpn_egress']={'enabled':True,'masquerade':True,'allow_selected_forward':True}
  wan=copy.deepcopy(cfg['wans'][0]);wan.pop('address');wan.pop('gateway');wan.update(v.state['links'][args.protocol]);wan.update(name='vpn1',kind='vpn',probe_table='sdwan-probe-vpn1');cfg['wans'].append(wan)
  cfg['policies'].append(dict(name='vpn-targets',source='0.0.0.0/0',table='sdwan-vpn-targets',profile='default',mode='prefer',wans=['vpn1','wan1','wan2'],allow_degraded=False,priority=10,destination_list='vpn-fixture-targets'))
  row=a.call('ip/firewall/address-list',{'list':'vpn-fixture-targets','address':'198.19.100.1','comment':'vpn-egress-acceptance-only'},'PUT');created.append((a,'ip/firewall/address-list',row['.id']))
  applied=True;apply(cfg)
  s=wait(lambda s:s['selected'].get('vpn-targets')=='vpn1' and s['selected'].get('default')=='wan1' and all(x['healthy'] for x in s['overlay'].values()))
  record('existing VPN exit is healthy through pinned physical WAN; Address List policy prefers VPN while default and branch OSPF remain independent')
  if args.traffic:
   from vpn_traffic import VPNTraffic
   traffic=VPNTraffic(v);traffic.prepare()
   matched=traffic.stream(59410,'sdwan-out-vpn-targets:vpn1')
   ordinary=traffic.stream(59411,'sdwan-out-default:wan1',target='198.19.100.2')
   branch=traffic.stream(59419,'no-mark',target='10.201.1.2')
   record('real forwarded TCP uses VPN only for Address List members; unrelated Internet and branch streams use their own paths')
   if args.reapply:
    cfg['revision']+='-reapply';apply(cfg)
    wait(lambda s:s['selected'].get('vpn-targets')=='vpn1')
    try:traffic.assert_sessions(retained=[matched,ordinary,branch])
    except AssertionError:
     debug={'status':a.status(),'connections':traffic.connections(),'routes':a.call('ip/route/print',{'.proplist':'dst-address,gateway,routing-table,active,disabled,comment'},'POST')}
     (v.run/'vpn-reapply-debug.json').write_text(json.dumps(debug,indent=2)+'\n');raise
    record('protected idempotent reapply preserves VPN, ordinary Internet and branch TCP connection identities')
    if args.only_reapply:report['pass']=True;return
  row=h.call('ip/firewall/filter',{'chain':'forward','in-interface':('vpn-server-wg' if args.protocol=='wireguard' else '<'+('ovpn' if args.protocol=='openvpn' else args.protocol)+'-vpn-lab-'+args.protocol+'>'),'dst-address':'198.19.100.1','protocol':'tcp','dst-port':'58081-58083','action':'drop','place-before':'0','comment':'vpn-egress-acceptance-only'},'PUT');created.append((h,'ip/firewall/filter',row['.id']))
  wait(lambda s:s['states']['default/vpn1']['state']=='down' and s['selected']['vpn-targets']=='wan1' and s['selected']['default']=='wan1')
  assert a.call('interface/print',{'.proplist':'running','.query':['name='+v.state['links'][args.protocol]['interface']]},'POST')[0]['running']=='true'
  record('target-resource outage beyond a running VPN triggers the common SLA failover to declared physical backup')
  if traffic:
   traffic.assert_sessions(absent=[matched],retained=[ordinary,branch])
   backup=traffic.stream(59412,'sdwan-out-vpn-targets:wan1')
   record('VPN SLA failure retires only affected conntrack; new real TCP uses the declared backup while unrelated streams continue')
  h.call('ip/firewall/filter/'+row['.id'],method='DELETE');created.pop()
  wait(lambda s:s['selected']['vpn-targets']=='vpn1');record('fresh successful probes and existing hold-down return the policy to preferred VPN')
  if traffic:
   traffic.assert_sessions(absent=[backup],retained=[ordinary,branch])
   traffic.stream(59413,'sdwan-out-vpn-targets:vpn1')
   record('preferred VPN failback retires only the old policy path and preserves unrelated Internet and branch TCP streams')
   traffic.close();traffic=None
  iface=a.call('interface/print',{'.proplist':'.id,disabled','.query':['name=ether2']},'POST')[0];assert iface['disabled']=='false';disabled=iface['.id'];a.call('interface/'+disabled,{'disabled':'true'},'PATCH')
  wait(lambda s:s['selected']['vpn-targets']=='vpn1' and s['selected']['default']=='wan2' and s['states']['default/vpn1']['state']=='healthy' and s['overlay']['hub-wan2']['healthy'])
  record('physical WAN1 loss reconnects the same VPN exit through WAN2 and preserves independent branch backup')
  a.call('interface/'+disabled,{'disabled':'false'},'PATCH');disabled=None
  wait(lambda s:s['selected']['vpn-targets']=='vpn1' and s['selected']['default']=='wan1' and all(x['healthy'] for x in s['overlay'].values()))
  record('physical preferred path and VPN recover without an external controller')
  report['pass']=True
 finally:
  if traffic:traffic.close()
  if disabled:a.call('interface/'+disabled,{'disabled':'false'},'PATCH')
  for r,menu,id in reversed(created):
   try:r.call(menu+'/'+id,method='DELETE')
   except RuntimeError:pass
  try:
   if applied:apply(before)
  finally:
   (v.run/('vpn-'+args.protocol+('-reapply' if args.reapply else '')+'-egress-validation.json')).write_text(json.dumps(report,indent=2)+'\n');v.close();lock.close()

if __name__=='__main__':main()
