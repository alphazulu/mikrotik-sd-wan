#!/usr/bin/env python3
"""CHR ONLY: full mixed static/DHCP VLAN/PPPoE deployment and lifecycle."""
import copy
import importlib.util
import json
import subprocess
import threading
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lab
from dynamic_wan_fixture import dynamic_wans
from sdwan.config import load,validate
from sdwan.router import Router
from stream_traffic import StreamTraffic

spec=importlib.util.spec_from_file_location('deploy_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)


def main():
    r=Router(ROOT,'api://127.0.0.1:18728');base=load(ROOT/'config/sdwan.json')
    backup=r.read_file('sdwan-backup.json');report={'checks':[]};traffic=None;remote=None;forward=False
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    stop_observer=threading.Event()
    def observe():
        reader=Router(ROOT)
        try:
            with (ROOT/'runtime/dynamic-wan-status-windows.jsonl').open('w') as stream:
                while not stop_observer.wait(.5):
                    try:stream.write(json.dumps({'time':time.time(),'status':reader.status()})+'\n');stream.flush()
                    except (OSError,RuntimeError,ConnectionError):pass
        finally:reader.close()
    observer=threading.Thread(target=observe,daemon=True);observer.start()
    def wait(predicate,timeout=50):
        end=time.monotonic()+timeout;last={}
        while time.monotonic()<end:
            last=r.status()
            if 'error' in last:raise AssertionError(last)
            if predicate(last):return last
            time.sleep(.3)
        print('Timed-out status:',last,flush=True)
        print('Netwatch diagnostics:',r.call('tool/netwatch/print',{'.proplist':'comment,type,host,src-address,disabled,status,done-tests,sent-count,response-count,rtt-avg'},'POST'),flush=True)
        print('Managed routes:',[x for x in r.call('ip/route') if x.get('comment','').startswith('sdwan:v1:')],flush=True)
        for n in (2,3):
            source=last.get('samples',{}).get('wan'+str(n),{}).get('address')
            if source:
                for target in (f'10.77.{n}.2',f'198.18.{n}.1'):
                    print('Manual source ping:',source,target,r.call('ping',{'address':target,'src-address':source,'count':'2'},'POST'),flush=True)
        raise AssertionError(last)
    def healthy():return wait(lambda s:s.get('states') and all(v['state']=='healthy' for v in s['states'].values()))
    try:
        with dynamic_wans(component_tables=False) as ids:
            try:
                for iface in ('sdwan-test-dhcp-vlan','sdwan-test-pppoe'):ids['add']('edge','interface/list/member',{'list':'WAN','interface':iface,'comment':'dynamic-wan-acceptance-only'})
                if not any(x.get('address')=='192.168.50.103/24' for x in lab.api('client','ip/address')):ids['add']('client','ip/address',{'address':'192.168.50.103/24','interface':'ether2','comment':'dynamic-wan-acceptance-only'})
                for n in (1,2,3):
                    ids['add']('isp'+str(n),'ip/address',{'address':'203.0.113.9/32','interface':'lo','comment':'dynamic-wan-acceptance-only'})
                    ids['add']('isp'+str(n),'ip/firewall/nat',{'chain':'dstnat','dst-address':'203.0.113.200','protocol':'tcp','dst-port':'28910-28919','action':'dst-nat','to-addresses':f'10.77.{n}.2','comment':'dynamic-wan-acceptance-only'})
                lease_hook=':log debug "sdwan dynamic test lease hook"'
                r.call('ip/dhcp-client/'+ids['dhcp'],{'default-route-distance':'250','default-route-tables':'default:240','script':lease_hook},'PATCH')
                r.call('ip/dhcp-client/'+ids['dhcp'],{'add-default-route':'yes'},'PATCH')
                r.call('interface/pppoe-client/'+ids['pppoe'],{'default-route-distance':'250','add-default-route':'true'},'PATCH')
                cfg=copy.deepcopy(base);cfg['revision']='mixed-v1'
                # Isolate session/address lifecycle from host scheduling jitter.
                # PPP reconnect on this CHR/KVM host produces 20-48ms jitter on
                # an otherwise unchanged DHCP link; the normal 15ms voice SLA
                # correctly switches it and invalidates retained-flow assertions.
                # Dedicated native_acceptance keeps the original strict SLA.
                for profile in cfg['sla_profiles'].values():profile['jitter_ms']=100
                for wan,kind,iface in zip(cfg['wans'][1:],('dhcp','pppoe'),('sdwan-test-dhcp-vlan','sdwan-test-pppoe')):
                    wan.update(kind=kind,interface=iface);wan.pop('address');wan.pop('gateway')
                # Enabled clients may have no lease/session during installation.
                lab.api('isp2','ip/dhcp-server/'+ids['dhcp_server'],{'disabled':'true'},'PATCH')
                lab.api('isp3','interface/pppoe-server/server/'+ids['pppoe_server'],{'disabled':'true'},'PATCH')
                for session in lab.api('isp3','ppp/active'):
                    if session.get('name')=='sdwan-test-ppp-user':lab.api('isp3','ppp/active/'+session['.id'],method='DELETE')
                r.call('ip/dhcp-client/release',{'numbers':ids['dhcp']},'POST')
                time.sleep(1)
                validate(cfg);cli.apply(r,cfg,'sdwan-edge')
                wait(lambda s:not s['samples']['wan2']['link_ready'] and not s['samples']['wan3']['link_ready'])
                assert r.status()['selected']['client102']=='wan1'
                assert r.status()['selected']['strict103']=='none'
                record('unbound DHCP and disconnected enabled PPPoE can be installed; unavailable WANs stay closed')
                lab.api('isp2','ip/dhcp-server/'+ids['dhcp_server'],{'disabled':'false'},'PATCH')
                lab.api('isp3','interface/pppoe-server/server/'+ids['pppoe_server'],{'disabled':'false'},'PATCH')
                state=healthy()
                assert [state['samples'][w]['kind'] for w in ('wan1','wan2','wan3')]==['static','dhcp','pppoe']
                assert state['selected']['client102']=='wan2' and state['selected']['strict103']=='wan3'
                active=json.loads(r.read_file('sdwan-active.json'))
                assert all('address' not in w and 'gateway' not in w for w in active['wans'][1:])
                record('protected mixed deployment runs locally with runtime addresses and fresh SLA; no leases saved in JSON')
                from sdwan.discovery import discover
                (ROOT/'runtime/discovery-mixed-wan.json').write_text(json.dumps(discover(r),indent=2)+'\n')
                gui=subprocess.run(['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-Command',
                    r'& "E:\ProgramData\anaconda3\python.exe" "C:\Project\Mikrotik\SD-WAN\tests\gui_dynamic_wan_smoke.py"'],capture_output=True,text=True,timeout=100)
                print(gui.stdout,flush=True)
                assert gui.returncode==0,gui.stderr
                healthy();record('Windows GUI discovers all three WAN kinds via native API and generates a validated nine-file package')
                for source in ('192.168.50.101','192.168.50.102'):
                    rows=lab.api('client','ping',{'address':'198.19.0.1','src-address':source,'count':'3'},'POST')
                    assert int(rows[-1].get('received','0'))==3,(source,rows)
                record('real client traffic succeeds through static WAN1 and DHCP/VLAN WAN2')
                client=r.call('ip/dhcp-client/'+ids['dhcp']);ppp=r.call('interface/pppoe-client/'+ids['pppoe'])
                assert client['default-route-tables'].split(':')[0]=='sdwan-probe-wan2'
                assert ppp['add-default-route'] in ('false','no')
                assert not any(x.get('dst-address')=='0.0.0.0/0' and x.get('routing-table','main')=='main' and x.get('dynamic')=='true' for x in r.call('ip/route'))
                record('provider automatic defaults cannot bypass SLA through main')

                # Remote replies must follow the ingress logical WAN, including
                # DNAT to a client whose outbound policy prefers DHCP WAN2.
                for n,address in ((1,'172.20.1.2'),(2,state['samples']['wan2']['address']),(3,state['samples']['wan3']['address'])):
                    rows=lab.api('isp'+str(n),'ping',{'address':address,'src-address':'203.0.113.9','count':'2'},'POST')
                    assert int(rows[-1].get('received','0'))==2,(address,rows)
                record('remote sources reach router IPs on static, DHCP and logical PPPoE WANs')
                ids['add']('client','ip/firewall/filter',{'chain':'input','src-address':'203.0.113.9','protocol':'tcp','dst-port':'80','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                ids['add']('edge','ip/firewall/filter',{'chain':'forward','connection-nat-state':'dstnat','protocol':'tcp','dst-port':'80','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                ids['add']('edge','ip/firewall/nat',{'chain':'dstnat','in-interface':'sdwan-test-pppoe','dst-address':'172.31.3.2','protocol':'tcp','dst-port':'28909','action':'dst-nat','to-addresses':'192.168.50.102','to-ports':'80','comment':'dynamic-wan-acceptance-only'})
                fetched=lab.api('isp3','tool/fetch',{'url':'http://172.31.3.2:28909/','src-address':'203.0.113.9','output':'user'},'POST')
                if isinstance(fetched,list):fetched=fetched[-1]
                assert fetched.get('status')=='finished'
                record('PPPoE DNAT replies preserve ingress WAN despite client102 preference for DHCP')

                ids['add']('edge','ip/firewall/filter',{'chain':'input','in-interface':'sdwan-test-pppoe','src-address':'10.77.3.0/24','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                api_filter=ids['add']('isp3','ip/firewall/filter',{'chain':'forward','in-interface':'ether1','dst-address':'172.31.3.2','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0','comment':'dynamic-wan-acceptance-only'})
                api_nat=ids['add']('isp3','ip/firewall/nat',{'chain':'dstnat','in-interface':'ether1','protocol':'tcp','dst-port':'29998','action':'dst-nat','to-addresses':'172.31.3.2','to-ports':'8728','comment':'dynamic-wan-acceptance-only'})
                result=lab.qmp('isp3','human-monitor-command',{'command-line':'hostfwd_add mgmt tcp:127.0.0.1:18998-10.77.3.15:29998'});assert not result,result
                forward=True;remote=Router(ROOT,'api://127.0.0.1:18998')
                assert remote.call('system/identity')['name']=='sdwan-edge'
                time.sleep(.3)
                end=time.monotonic()+5;incoming=None
                while time.monotonic()<end:
                    incoming=next((x['.id'] for x in r.call('ip/firewall/connection') if x.get('connection-mark')=='sdwan-in-wan3' and x.get('dst-port')=='8728' and x.get('dst-address')=='172.31.3.2'),None)
                    if incoming:break
                    time.sleep(.2)
                assert incoming,[{k:v for k,v in x.items() if k in ('.id','src-address','dst-address','dst-port','connection-mark')} for x in r.call('ip/firewall/connection') if x.get('dst-port')=='8728']
                traffic=StreamTraffic(r,ids['add'])
                first=traffic.stream('192.168.50.101','wan1',28910)['.id']
                second=traffic.stream('192.168.50.102','wan2',28911)['.id']
                third=traffic.stream('192.168.50.103','wan3',28912)['.id']
                record('concurrent real TCP/NAT streams carry correct marks on all three WAN kinds')
                r.call('ip/dhcp-client/'+ids['dhcp'],{'disabled':'true'},'PATCH')
                wait(lambda s:s['selected']['client102']=='wan1' and not s['samples']['wan2']['link_ready'])
                traffic.assert_sessions(absent=[second],retained=[first,third,incoming]);traffic.stop_stream(second)
                assert remote.call('system/identity')['name']=='sdwan-edge'
                fallback=traffic.stream('192.168.50.102','wan1',28913)['.id']
                r.call('ip/dhcp-client/'+ids['dhcp'],{'disabled':'false'},'PATCH');healthy()
                wait(lambda s:s['selected']['client102']=='wan2')
                traffic.assert_sessions(absent=[fallback],retained=[first,third,incoming]);traffic.stop_stream(fallback)
                second=traffic.stream('192.168.50.102','wan2',28914)['.id']
                record('DHCP lease loss and failback remove only affected client conntrack; PPPoE API and other streams survive')

                # Force a replacement lease without disabling the client: the
                # scheduler must notice address/gateway changes even if it
                # never observes the short unbound interval.
                ids['add']('isp2','ip/address',{'address':'172.31.2.254/24','interface':'sdwan-test-dhcp-vlan','comment':'dynamic-wan-acceptance-only'})
                lab.api('isp2','ip/pool/'+ids['dhcp_pool'],{'ranges':'172.31.2.20-172.31.2.21'},'PATCH')
                lab.api('isp2','ip/dhcp-server/network/'+ids['dhcp_network'],{'gateway':'172.31.2.254'},'PATCH')
                r.call('ip/dhcp-client/release',{'numbers':ids['dhcp']},'POST')
                warm=wait(lambda s:s['samples']['wan2']['address'] in ('172.31.2.20','172.31.2.21') and s['samples']['wan2']['warming'])
                assert warm['states']['voice/wan2']['good_windows']==0 and warm['selected']['client102']!='wan2'
                traffic.assert_sessions(absent=[second],retained=[first,third,incoming]);traffic.stop_stream(second)
                healthy();wait(lambda s:s['selected']['client102']=='wan2')
                current=traffic.stream('192.168.50.102','wan2',28915)
                assert current.get('reply-dst-address') in ('172.31.2.20','172.31.2.21'),current
                second=current['.id']
                assert r.status()['samples']['wan2']['gateway']=='172.31.2.254'
                record('new DHCP address/gateway requires fresh probes and uses the new source NAT without resetting other WANs')

                lab.api('isp2','ip/dhcp-server/network/'+ids['dhcp_network'],{'dhcp-option':'sdwan-test-classless'},'PATCH')
                r.call('ip/dhcp-client/renew',{'numbers':ids['dhcp']},'POST')
                wait(lambda s:s['samples']['wan2']['gateway']=='172.31.2.1' and s['samples']['wan2']['warming'])
                traffic.assert_sessions(absent=[second],retained=[first,third,incoming]);traffic.stop_stream(second)
                healthy();second=traffic.stream('192.168.50.102','wan2',28916)['.id']
                record('option121 gateway change overrides option3 and resets only that WAN generation and conntrack')

                r.call('interface/pppoe-client/'+ids['pppoe'],{'disabled':'true'},'PATCH')
                wait(lambda s:s['selected']['strict103']=='none' and not s['samples']['wan3']['link_ready'])
                traffic.assert_sessions(absent=[third,incoming],retained=[first,second]);traffic.stop_stream(third);remote.close();remote=None
                lab.api('isp3','ppp/profile/'+ids['ppp_profile'],{'remote-address':'172.31.3.22'},'PATCH')
                r.call('interface/pppoe-client/'+ids['pppoe'],{'disabled':'false'},'PATCH')
                warm=wait(lambda s:s['samples']['wan3']['address']=='172.31.3.22' and s['samples']['wan3']['warming'])
                assert warm['selected']['strict103']=='none' and warm['states']['default/wan3']['good_windows']==0
                healthy();third_new=traffic.stream('192.168.50.103','wan3',28917)
                assert third_new.get('reply-dst-address')=='172.31.3.22',third_new
                traffic.assert_sessions(retained=[first,second])
                lab.api('isp3','ip/firewall/filter/'+api_filter,{'dst-address':'172.31.3.22'},'PATCH')
                lab.api('isp3','ip/firewall/nat/'+api_nat,{'to-addresses':'172.31.3.22'},'PATCH')
                remote=Router(ROOT,'api://127.0.0.1:18998');assert remote.call('system/identity')['name']=='sdwan-edge'
                record('PPPoE new-IP reconnect clears old sessions, restores strict routing/NAT/API and preserves DHCP/static streams')
                traffic.close();traffic=None;remote.close();remote=None

                try:r.call('system/reboot',{},'POST')
                except (OSError,ConnectionError):pass
                r.close();time.sleep(3)
                end=time.monotonic()+100
                while time.monotonic()<end:
                    try:
                        state=r.status()
                        if state.get('revision')=='mixed-v1' and state.get('selected',{}).get('strict103')=='wan3' and state.get('selected',{}).get('client102')=='wan2':break
                    except (OSError,ConnectionError):r.close()
                    time.sleep(.5)
                else:raise AssertionError('Mixed WAN controller did not recover after reboot')
                healthy();record('native controller reloads its library and reacquires dynamic WANs after reboot without external runtime')
                cli.rollback(r,'sdwan-edge')
                client=r.call('ip/dhcp-client/'+ids['dhcp']);ppp=r.call('interface/pppoe-client/'+ids['pppoe'])
                assert client['add-default-route']=='yes' and client['default-route-tables']=='default:240',client
                assert client['script']==lease_hook
                assert ppp['add-default-route'] in ('true','yes')
                record('baseline rollback restores original DHCP/PPPoE automatic-route options')
            finally:
                if traffic:traffic.close();traffic=None
                if remote:remote.close();remote=None
                if forward:lab.qmp('isp3','human-monitor-command',{'command-line':'hostfwd_remove mgmt tcp:127.0.0.1:18998'});forward=False
                # Only fixture clients: suppress their defaults before returning
                # to the static lab, then discard their temporary baseline rows.
                r.call('ip/dhcp-client/'+ids['dhcp'],{'add-default-route':'no'},'PATCH')
                r.call('interface/pppoe-client/'+ids['pppoe'],{'add-default-route':'false'},'PATCH')
                cli.apply(r,base,'sdwan-edge');healthy();r.upload('sdwan-backup.json',backup)
    except Exception as error:
        report['checks'].append({'check':'dynamic WAN acceptance interrupted','pass':False,'detail':str(error)});raise
    finally:
        stop_observer.set();observer.join(timeout=3)
        (ROOT/'runtime/dynamic-wan-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');r.close()


if __name__=='__main__':main()
