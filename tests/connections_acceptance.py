#!/usr/bin/env python3
"""LAB ONLY: real ingress/DNAT/TCP flows and scoped native conntrack cleanup."""
import http.server
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import lab
from sdwan.router import Router


def main():
    router=Router(ROOT);remote=None;resources=[];servers=[];stop=threading.Event();forward=False;jobs={}
    report={'checks':[]}
    def record(name):report['checks'].append({'check':name,'pass':True});print('PASS '+name,flush=True)
    def add(node,menu,data):
        data=dict(data,comment='connections-acceptance-only')
        item=lab.api(node,menu,data,'PUT');resources.append((node,menu,item['.id']))
        # RouterOS may publish a rule before interface/route validation completes.
        if menu.startswith('ip/firewall/'):
            until=time.monotonic()+5
            while lab.api(node,menu+'/'+item['.id']).get('invalid')=='true':
                if time.monotonic()>until:raise AssertionError('Rule stayed invalid: '+menu)
                time.sleep(.1)
        return item['.id']
    def status():
        value=router.status()
        if 'error' in value:raise AssertionError(value)
        return value
    def wait(predicate,timeout=45):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if predicate():return
            time.sleep(.3)
        raise AssertionError('Condition timed out; status='+json.dumps(status()))
    def connections():return router.call('ip/firewall/connection')
    def present(identifier):return any(c['.id']==identifier for c in connections())
    def assert_sessions(absent=(),retained=()):
        end=time.monotonic()+3
        while True:
            entries=connections();ids={c['.id'] for c in entries}
            detail={'unexpectedly_present':[x for x in absent if x in ids],'unexpectedly_missing':[x for x in retained if x not in ids]}
            if not detail['unexpectedly_present'] and not detail['unexpectedly_missing']:return
            if time.monotonic()>end:
                detail['entries']=[c for c in entries if c['.id'] in detail['unexpectedly_present']]
                detail['status']=status()
                raise AssertionError(json.dumps(detail))
            time.sleep(.1)
    def healthy():wait(lambda:all(x['state']=='healthy' for x in status()['states'].values()))

    class Stream(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Length','1000000');self.end_headers()
            try:
                while not stop.wait(.2):self.wfile.write(b'x'*256);self.wfile.flush()
            except (OSError,ConnectionError):pass

    def stream(source,wan,port):
        if not any(server.server_port==port for server in servers):
            server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Stream);server.daemon_threads=True
            servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
        name=f'connections-test-{port}-{time.monotonic_ns()}'
        job=add('client','system/script',{'name':name,'source':f':execute {{ /tool/fetch url="http://203.0.113.200:{port}/" src-address={source} keep-result=no }}','policy':'read,write,policy,test'})
        lab.api('client','system/script/run',{'number':job},'POST')
        running=[]
        def find_job():
            running[:]=[j['.id'] for j in lab.api('client','system/script/job') if '/script:'+name+'/:execute:' in j.get('trace','')]
            return bool(running)
        wait(find_job,timeout=5);task=running[0];jobs[name]=task
        matches=[]
        def connected():
            matches[:]=[c for c in connections() if c.get('src-address')==source and c.get('dst-address')=='203.0.113.200' and c.get('dst-port')==str(port) and c.get('connection-mark')==f'sdwan-out-client{source.rsplit(".",1)[1]}:{wan}' and c.get('seen-reply')=='true']
            return bool(matches)
        try:wait(connected)
        except Exception:
            print('Stream connection diagnostics',source,port,[c for c in connections() if c.get('dst-address')=='203.0.113.200'],flush=True)
            print('Client flow diagnostics',[c for c in lab.api('client','ip/firewall/connection') if c.get('dst-address')=='203.0.113.200'],flush=True)
            print('TCP diagnostics',[x.get('message') for x in router.call('log') if x.get('message','').startswith('SDWAN-TCPTEST')][-10:],flush=True)
            raise
        jobs[matches[0]['.id']]=task
        return matches[0]['.id']

    def stop_stream(connection):
        task=jobs.get(connection)
        if task and any(j['.id']==task for j in lab.api('client','system/script/job')):
            try:lab.api('client','system/script/job/'+task,method='DELETE')
            except RuntimeError as error:
                if '404' not in str(error):raise

    try:
        lab.proxy_request({'reset':True});healthy()
        for n in (1,2,3):
            add('isp'+str(n),'ip/address',{'address':'203.0.113.9/32','interface':'lo'})
            add('edge','ip/address',{'address':f'172.21.{n}.2/30','interface':f'ether{n+1}'})
            add('isp'+str(n),'ip/address',{'address':f'172.21.{n}.1/30','interface':'ether2'})
            for address in (f'172.20.{n}.2',f'172.21.{n}.2'):
                rows=lab.api('isp'+str(n),'ping',{'address':address,'src-address':'203.0.113.9','count':'2'},'POST')
                assert int(rows[-1].get('received','0'))==2,(n,address,rows)
            add('isp'+str(n),'ip/firewall/nat',{'chain':'dstnat','dst-address':'203.0.113.200','protocol':'tcp','dst-port':'28901-28906','action':'dst-nat','to-addresses':f'10.77.{n}.2'})
        record('remote source reaches primary and additional router IPs on all three WANs')

        add('edge','ip/firewall/filter',{'chain':'input','in-interface':'ether4','src-address':'10.77.3.0/24','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0'})
        add('isp3','ip/firewall/filter',{'chain':'forward','in-interface':'ether1','dst-address':'172.20.3.2','protocol':'tcp','dst-port':'8728','action':'accept','place-before':'0'})
        add('isp3','ip/firewall/nat',{'chain':'dstnat','in-interface':'ether1','protocol':'tcp','dst-port':'29999','action':'dst-nat','to-addresses':'172.20.3.2','to-ports':'8728'})
        result=lab.qmp('isp3','human-monitor-command',{'command-line':'hostfwd_add mgmt tcp:127.0.0.1:18999-10.77.3.15:29999'})
        assert not result,result
        forward=True;time.sleep(.5);remote=Router(ROOT,'api://127.0.0.1:18999')
        assert remote.call('system/identity')['name']=='sdwan-edge'
        incoming_matches=[]
        def find_incoming():
            incoming_matches[:]=[c['.id'] for c in connections() if c.get('connection-mark')=='sdwan-in-wan3' and c.get('dst-address')=='172.20.3.2' and c.get('dst-port')=='8728']
            return bool(incoming_matches)
        wait(find_incoming);incoming=incoming_matches[0]
        record('persistent API session enters backup WAN3 and replies through WAN3')

        add('client','ip/firewall/filter',{'chain':'input','src-address':'203.0.113.9','protocol':'tcp','dst-port':'80','action':'accept','place-before':'0'})
        add('edge','ip/firewall/filter',{'chain':'forward','connection-nat-state':'dstnat','protocol':'tcp','dst-port':'80','action':'accept','place-before':'0'})
        add('edge','ip/firewall/nat',{'chain':'dstnat','in-interface':'ether4','dst-address':'172.20.3.2','protocol':'tcp','dst-port':'28903','action':'dst-nat','to-addresses':'192.168.50.102','to-ports':'80'})
        fetched=lab.api('isp3','tool/fetch',{'url':'http://172.20.3.2:28903/','src-address':'203.0.113.9','output':'user'},'POST')
        if isinstance(fetched,list):fetched=fetched[-1]
        assert fetched.get('status')=='finished',fetched.get('status')
        record('DNAT reply from client102 exits ingress WAN3 despite its outbound WAN2 policy')

        first=stream('192.168.50.101','wan1',28901)
        second=stream('192.168.50.102','wan2',28902)
        record('established NAT TCP streams carry distinct client-policy/WAN connection marks')
        lab.proxy_request({'wan':'wan2','set':{'delay':55.0}})
        wait(lambda:status()['selected']['client102']=='wan1')
        assert_sessions(absent=[second],retained=[first,incoming])
        stop_stream(second)
        assert remote.call('system/identity')['name']=='sdwan-edge'
        second_fallback=stream('192.168.50.102','wan1',28904)
        record('voice SLA transition removes only client102 old-WAN conntrack; client101 and incoming API survive')
        lab.proxy_request({'reset':True});healthy();wait(lambda:status()['selected']['client102']=='wan2')
        assert_sessions(absent=[second_fallback],retained=[first,incoming])
        stop_stream(second_fallback)
        second_current=stream('192.168.50.102','wan2',28905)
        record('failback also removes the changed policy connection without resetting other sessions')

        lab.proxy_request({'wan':'wan1','set':{'blackhole':True}})
        wait(lambda:status()['selected']['client101']=='wan2')
        assert_sessions(absent=[first],retained=[second_current,incoming])
        stop_stream(first)
        assert remote.call('system/identity')['name']=='sdwan-edge'
        old_count=status()['last_cleanup']['client101']['removed'];assert old_count>=1,old_count
        replacement=stream('192.168.50.101','wan2',28906)
        record('silent upstream failure purges affected NAT state and replacement flow uses WAN2')
        lab.proxy_request({'reset':True});healthy();wait(lambda:status()['selected']['client101']=='wan1')
        assert_sessions(absent=[replacement],retained=[second_current,incoming])
        stop_stream(replacement)
        assert remote.call('system/identity')['name']=='sdwan-edge'
        record('client101 failback from WAN2 preserves client102 streams on that same WAN2')
    except Exception as e:
        report['checks'].append({'check':'connections acceptance interrupted','pass':False,'detail':str(e)});raise
    finally:
        stop.set()
        lab.proxy_request({'reset':True})
        for connection in list(jobs):stop_stream(connection)
        if remote:remote.close()
        if forward:lab.qmp('isp3','human-monitor-command',{'command-line':'hostfwd_remove mgmt tcp:127.0.0.1:18999'})
        for node,menu,identifier in reversed(resources):
            try:lab.api(node,menu+'/'+identifier,method='DELETE')
            except Exception as e:print('Cleanup failed:',node,menu,identifier,str(e),file=sys.stderr)
        for server in servers:server.shutdown();server.server_close()
        try:healthy()
        finally:
            (ROOT/'runtime/connections-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');router.close()


if __name__=='__main__':main()
