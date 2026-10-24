"""Real slow TCP downloads for CHR tests; never makes routing decisions."""
import http.server
import threading
import time
import lab


class StreamTraffic:
    def __init__(self,router,add):
        self.router=router;self.add=add;self.stop=threading.Event();self.servers={};self.tasks={}

    def connections(self):return self.router.call('ip/firewall/connection')

    def stream(self,source,wan,port,policy=None):
        stop=self.stop
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Length','100000000');self.end_headers()
                try:
                    while not stop.wait(.2):self.wfile.write(b'x'*256);self.wfile.flush()
                except (OSError,ConnectionError):pass
        if port not in self.servers:
            server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
            self.servers[port]=server;threading.Thread(target=server.serve_forever,daemon=True).start()
        name=f'dynamic-stream-{port}-{time.monotonic_ns()}'
        row=self.add('client','system/script',{'name':name,'source':f':execute {{ /tool/fetch url="http://203.0.113.200:{port}/" src-address={source} keep-result=no }}','policy':'read,write,policy,test'})
        lab.api('client','system/script/run',{'number':row},'POST')
        policy=policy or ('strict103' if source=='192.168.50.103' else 'client'+source.rsplit('.',1)[1])
        end=time.monotonic()+25
        while time.monotonic()<end:
            for j in lab.api('client','system/script/job'):
                if '/script:'+name+'/:execute:' in j.get('trace',''):self.tasks[name]=j['.id']
            for c in self.connections():
                if c.get('src-address')==source and c.get('dst-address')=='203.0.113.200' and c.get('dst-port')==str(port) and c.get('connection-mark')==f'sdwan-out-{policy}:{wan}' and c.get('seen-reply')=='true':
                    self.tasks[c['.id']]=self.tasks.get(name);return c
            time.sleep(.2)
        raise AssertionError({'source':source,'wan':wan,'port':port,'flows':[c for c in self.connections() if c.get('dst-address')=='203.0.113.200']})

    def assert_sessions(self,absent=(),retained=()):
        end=time.monotonic()+3
        while time.monotonic()<end:
            ids={c['.id'] for c in self.connections()}
            if not (set(absent)&ids) and set(retained)<=ids:return
            time.sleep(.1)
        raise AssertionError({'unexpectedly_present':list(set(absent)&ids),'unexpectedly_missing':list(set(retained)-ids),'status':self.router.status()})

    def stop_stream(self,connection):
        task=self.tasks.get(connection)
        if task and any(j['.id']==task for j in lab.api('client','system/script/job')):
            try:lab.api('client','system/script/job/'+task,method='DELETE')
            except RuntimeError as error:
                if '404' not in str(error):raise

    def close(self):
        self.stop.set()
        for task in list(self.tasks):self.stop_stream(task)
        for server in self.servers.values():server.shutdown();server.server_close()
