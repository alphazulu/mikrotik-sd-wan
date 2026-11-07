"""One optional dashboard reader in the owned client namespace; token never logged."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import signal
import threading
import time
import urllib.parse

class TelemetryResponseError(RuntimeError):
    def __init__(self,status):self.status=status;super().__init__('Telemetry returned '+str(status))

def read_endpoint(target,source,token,path):
    connection=http.client.HTTPConnection(target.hostname,target.port or 80,timeout=2,source_address=(source,0))
    try:
        connection.request('GET',path,headers={'Authorization':'Bearer '+token,'Cache-Control':'no-store'});response=connection.getresponse();body=response.read(2*1024*1024)
        if response.status!=200:raise TelemetryResponseError(response.status)
        json.loads(body);return True
    finally:connection.close()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--url',required=True);p.add_argument('--token-file',type=Path,required=True);p.add_argument('--source',default='192.168.50.101');a=p.parse_args();target=urllib.parse.urlsplit(a.url)
    if target.scheme!='http' or target.username or target.password or not target.hostname:raise ValueError('Expected owned HTTP telemetry endpoint')
    token=a.token_file.read_text().strip();stopped=threading.Event();signal.signal(signal.SIGINT,lambda *args:stopped.set());signal.signal(signal.SIGTERM,lambda *args:stopped.set());report={'requests':0,'errors':0,'cycles':0,'period_seconds':5,'errors_by_path':{}}
    with ThreadPoolExecutor(max_workers=3) as workers:
        while not stopped.is_set():
            start=time.monotonic();futures=[(path,workers.submit(read_endpoint,target,a.source,token,path)) for path in ('/api/status','/api/history?max=600','/api/events')]
            for path,future in futures:
                report['requests']+=1
                try:future.result()
                except (OSError,ValueError,RuntimeError) as error:
                    report['errors']+=1;before=report['errors_by_path'].get(path,{})
                    failure={'count':before.get('count',0)+1,'kind':type(error).__name__}
                    if isinstance(error,TelemetryResponseError):failure['status']=error.status
                    if isinstance(error,OSError) and error.errno is not None:failure['errno']=error.errno
                    report['errors_by_path'][path]=failure
            report['cycles']+=1
            if report['cycles']==1:
                if report['errors']:print(json.dumps(report),flush=True);return 1
                print('ready',flush=True)
            stopped.wait(max(0,5-(time.monotonic()-start)))
    print(json.dumps(report),flush=True);return 0 if not report['errors'] else 1

if __name__=='__main__':raise SystemExit(main())
