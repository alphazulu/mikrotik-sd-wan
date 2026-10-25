#!/usr/bin/env python3
"""CHR ONLY: strict response validation, bounded workers, heartbeat and cleanup."""
import argparse
import copy
import contextlib
import ssl
import subprocess
import tempfile
import http.server
import json
from pathlib import Path
import threading
import time
from network_lab import NetworkLab


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',type=Path,required=True);p.add_argument('--only-hang',action='store_true');p.add_argument('--only-dns',action='store_true');args=p.parse_args()
    report={'checks':[],'pass':False};servers=[];modes={59080:'good',59081:'good',59082:'503'};stop=threading.Event();requests=[];tls_directory=tempfile.TemporaryDirectory(prefix='strict-probe-tls-',dir=args.lab_root/'runtime')
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_GET(self):
            mode=modes[self.server.server_port];requests.append((self.server.server_port,self.path,mode))
            code=503 if mode=='503' else 302 if mode=='redirect' else 204 if mode=='204' else 200
            body=b'healthy\n' if mode=='good' and self.path=='/expected?x=1' else b'CAPTIVE PORTAL' if mode=='wrong' else b'x'*2048 if mode=='oversize' else b''
            self.send_response(code)
            if mode=='redirect':self.send_header('Location','http://127.0.0.1:1/never-follow')
            if mode=='hang':self.send_header('Content-Length','1000000')
            else:self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            try:
                if mode=='hang':
                    for i in range(200):
                        if stop.wait(.1):break
                        self.wfile.write(b'x');self.wfile.flush()
                elif body:self.wfile.write(body);self.wfile.flush()
            except (OSError,ConnectionError):pass
    def record(name,**data):report['checks'].append({'check':name,'pass':True,**data});print('PASS '+name,flush=True)
    try:
        for port in modes:
            server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True;servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
        tls_path=Path(tls_directory.name)
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=sdwan-invalid-test','-keyout',str(tls_path/'key.pem'),'-out',str(tls_path/'cert.pem')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(tls_path/'cert.pem',tls_path/'key.pem')
        for port in (59083,59084):
            modes[port]='good';server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.socket=tls.wrap_socket(server.socket,server_side=True);server.daemon_threads=True;servers.append(server);threading.Thread(target=server.serve_forever,daemon=True).start()
        with NetworkLab(args.lab_root) as env,contextlib.ExitStack() as cleanup:
            cfg=copy.deepcopy(env.before);cfg['revision']='strict-response-fixture';cfg['health'].update(strict_probe_interval_seconds=5,strict_probe_timeout_ms=2000)
            for profile in cfg['sla_profiles'].values():profile['jitter_ms']=100
            for probe,port in zip(cfg['wans'][0]['probes'][:2],(59080,59081)):probe.update(type='http-get',port=port,http_path='/expected?x=1',http_expected_body='healthy\n',http_codes=[200])
            cfg['wans'][0]['probes'][2].update(port=59082,http_codes=[503]);env.apply(cfg);env.healthy()
            env.wait(lambda s:all(s['probe_details']['wan1/'+n]['up'] for n in ('a','b','c')))
            assert all(path=='/expected?x=1' for port,path,_ in requests if port!=59082)
            record('exact HTTP origin path/body and custom native Netwatch status whitelist are verified on the pinned WAN')
            good=copy.deepcopy(cfg)
            if not args.only_dns:
                for mode,reason in ([] if args.only_hang else [('wrong','http-body'),('204','http-code'),('oversize','http-oversize'),('redirect','http-error')]):
                    modes[59080]=modes[59081]=mode
                    env.wait(lambda s:all(s['probe_details']['wan1/'+n].get('reason')==reason for n in ('a','b')))
                    env.wait(lambda s:s['selected']['client101']=='wan2')
                    record(mode+' response fails closed and causes SLA failover')
                    modes[59080]=modes[59081]='good';env.healthy();env.wait(lambda s:s['selected']['client101']=='wan1')
                if not args.only_hang:
                    saved=copy.deepcopy(cfg);cfg['revision']='strict-empty-204-default-timeout';cfg['health'].pop('strict_probe_timeout_ms',None)
                    for probe in cfg['wans'][0]['probes'][:2]:probe.update(http_expected_body='',http_codes=[204])
                    modes[59080]=modes[59081]='204';env.apply(cfg);env.healthy()
                    env.wait(lambda s:all(s['probe_details']['wan1/'+n]['up'] for n in ('a','b')))
                    record('explicit empty 204 response works with the default strict deadline')
                    cfg=saved;modes[59080]=modes[59081]='good';env.apply(cfg);env.healthy()
                modes[59080]=modes[59081]='hang'
                env.wait(lambda s:all(s['probe_details']['wan1/'+n].get('reason')=='strict-timeout' for n in ('a','b')))
                env.wait(lambda s:s['selected']['client101']=='wan2')
                start=env.router.status()['uptime_seconds'];latencies=[];max_workers=0;max_guards=0
                for i in range(30):
                    before=time.monotonic();state=env.router.status();latencies.append(time.monotonic()-before)
                    jobs=env.router.call('system/script/job/print',{'.proplist':'trace'},'POST')
                    workers=sum('/script:sdwan-strict-worker-' in j.get('trace','') for j in jobs);guards=sum('/script:sdwan-strict-timeout-' in j.get('trace','') for j in jobs)
                    max_workers=max(max_workers,workers);max_guards=max(max_guards,guards)
                    assert workers<=4 and guards<=4,{'workers':workers,'guards':guards}
                    assert state['selected']['client101']=='wan2';time.sleep(.25)
                assert state['uptime_seconds']>=start+6;assert max(latencies)<1
                record('hung/dribbling endpoints are cancelled; two-worker cap, API responsiveness and controller heartbeat survive',max_worker_jobs=max_workers,max_guard_jobs=max_guards,max_api_latency_ms=round(max(latencies)*1000))
                modes[59080]=modes[59081]='good';env.healthy()
                if not args.only_hang:
                    good=copy.deepcopy(cfg)
                    cfg['revision']='strict-generation-change'
                    for probe in cfg['wans'][0]['probes'][:2]:probe['http_expected_body']='different proof'
                    env.apply(cfg);env.wait(lambda s:all(s['probe_details']['wan1/'+n].get('reason')=='http-body' for n in ('a','b')))
                    env.wait(lambda s:s['selected']['client101']=='wan2')
                    record('configuration generation change invalidates formerly good HTTP evidence')
                    cfg=copy.deepcopy(good);cfg['revision']='strict-generation-restored';env.apply(cfg);env.healthy()
                    def generation():return int(env.router.call('system/script/environment/print',{'.proplist':'value','.query':['name=sdwanStrictGeneration']},'POST')[0]['value'])
                    previous=generation();cfg['revision']='strict-admin-only';cfg['wans'][1]['admin_state']='drain';env.apply(cfg);env.wait(lambda s:s['maintenance']['wan2']['effective']=='drain')
                    assert generation()==previous
                    record('administrative-only configuration preserves the strict evidence generation')
                    cfg=copy.deepcopy(good);cfg['revision']='strict-invalid-tls'
                    for probe,port in zip(cfg['wans'][0]['probes'][:2],(59083,59084)):probe.update(type='https-get',port=port)
                    env.apply(cfg);env.wait(lambda s:all(s['probe_details']['wan1/'+n].get('reason')=='http-error' for n in ('a','b')));env.wait(lambda s:s['selected']['client101']=='wan2')
                    record('untrusted HTTPS certificate fails strict verification despite an available TCP port')
            if not args.only_hang:
                dns=env.lab.api('isp1','ip/dns');env.lab.api('isp1','ip/dns/set',{'allow-remote-requests':'true'},'POST');cleanup.callback(env.lab.api,'isp1','ip/dns/set',{'allow-remote-requests':dns['allow-remote-requests']},'POST')
                env.add('isp1','ip/firewall/filter',{'chain':'input','protocol':'udp','src-address':'172.20.1.2','dst-port':'53','action':'accept','place-before':'0'})
                entries=[env.add('isp1','ip/dns/static',{'name':'strict-'+name+'.invalid','address':'192.0.2.11','ttl':'1s'}) for name in ('a','b')]
                cfg=copy.deepcopy(good);cfg['revision']='strict-dns-answers'
                for probe in cfg['wans'][0]['probes'][:2]:
                    name=probe['name'];probe.clear();probe.update(name=name,type='dns',host='strict-'+name+'.invalid',dns_server='172.20.1.1',dns_expected_ips=['192.0.2.11'])
                env.apply(cfg);env.healthy()
                for entry in entries:env.lab.api('isp1','ip/dns/static/'+entry,{'address':'192.0.2.12'},'PATCH')
                env.wait(lambda s:all(s['probe_details']['wan1/'+n].get('reason')=='dns-mismatch' for n in ('a','b')));env.wait(lambda s:s['selected']['client101']=='wan2')
                record('syntactically successful DNS response with an unexpected A address fails quorum')
                cfg['revision']='strict-dns-allowlist'
                for probe in cfg['wans'][0]['probes'][:2]:probe['dns_expected_ips']=['192.0.2.11','192.0.2.12']
                env.apply(cfg);env.healthy();env.wait(lambda s:s['selected']['client101']=='wan1')
                record('DNS allowlist accepts a declared alternative A address')
                cfg=copy.deepcopy(good)
            for probe in cfg['wans'][0]['probes']:
                for key in ('http_path','http_expected_body','http_codes'):probe.pop(key,None)
            for probe,port in zip(cfg['wans'][0]['probes'],(28081,28082,28083)):probe['port']=port
            cfg['revision']='strict-disabled';env.apply(cfg);env.healthy()
            assert not env.router.call('system/scheduler/print',{'.proplist':'name','.query':['name=sdwan-strict-dispatch']},'POST')
            assert not any(x.get('name','').startswith('sdwan-strict-') for x in env.router.call('system/script/print',{'.proplist':'name'},'POST'))
            record('turning strict HTTP off removes its owned workers/scheduler and restores ordinary Netwatch mode')
            report['pass']=True
    finally:
        stop.set()
        for server in servers:server.shutdown();server.server_close()
        tls_directory.cleanup()
        (args.lab_root/'runtime/strict-probe-validation.json').write_text(json.dumps(report,indent=2)+'\n')

if __name__=='__main__':main()
