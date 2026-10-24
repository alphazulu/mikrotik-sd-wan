#!/usr/bin/env python3
"""Import and execute the scratch archive on isolated RouterOS 7.24.5 CHR."""
from pathlib import Path
import functools
import http.server
import json
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import container_lab
lab=container_lab.load()

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def main():
    assert json.loads((ROOT/'runtime/container-package-validation.json').read_text())['pass']
    identity=lab.api('edge','system/identity')
    if isinstance(identity,list):identity=identity[0]
    assert identity['name']=='sdwan-container-edge'
    existing=lab.api('edge','container')
    assert len(existing)<=1 and all(row['name']=='sdwan-container-controller' and row['file']=='sdwan-controller-amd64.tar' and row['cmd']=='--version' for row in existing), 'Unexpected existing container; inspect before retry'
    # Separate interface subnet, no forwarding or NAT required for --version.
    for path,data in [
        ('interface/bridge',{'name':'sdwan-container-mgmt'}),
        ('ip/address',{'address':'172.31.255.1/30','interface':'sdwan-container-mgmt'}),
        ('interface/veth',{'name':'sdwan-container-veth','address':'172.31.255.2/30','gateway':'172.31.255.1'}),
        ('interface/bridge/port',{'bridge':'sdwan-container-mgmt','interface':'sdwan-container-veth'})]:
        rows=lab.api('edge',path)
        if any(all(row.get(k)==v for k,v in data.items()) for row in rows):continue
        lab.api('edge',path,data,'PUT')
    if not existing:
        handler=functools.partial(Quiet,directory=str(ROOT/'dist/container'))
        server=http.server.ThreadingHTTPServer(('127.0.0.1',48090),handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            lab.api('edge','tool/fetch',{'url':'http://10.77.0.2:48090/sdwan-controller-amd64.tar',
                    'dst-path':'sdwan-controller-amd64.tar','keep-result':'yes'},'POST')
        finally:server.shutdown();server.server_close();worker.join()
        lab.api('edge','container',{'file':'sdwan-controller-amd64.tar','interface':'sdwan-container-veth',
                'root-dir':'sdwan-container-root','name':'sdwan-container-controller',
                'cmd':'--version','logging':'yes','start-on-boot':'no'},'PUT')
    end=time.monotonic()+60
    while time.monotonic()<end:
        rows=lab.api('edge','container')
        assert len(rows)==1
        if rows[0].get('stopped')=='true' or rows[0].get('status')=='stopped':break
        if rows[0].get('status')=='error' or rows[0].get('error')=='true':raise RuntimeError('Container import failed; inspect isolated CHR logs')
        time.sleep(1)
    else:raise RuntimeError('Container extraction did not finish')
    ident=rows[0]['.id']
    lab.api('edge','container/start',{'numbers':ident},'POST')
    end=time.monotonic()+20
    expected='sdwan-router-controller 0.1.0'
    while time.monotonic()<end:
        logs=lab.api('edge','log')
        if any(expected in row.get('message','') for row in logs):break
        time.sleep(.5)
    else:raise RuntimeError('Scratch binary did not print version in RouterOS; inspect isolated CHR logs')
    rows=lab.api('edge','container')
    assert rows[0].get('stopped')=='true' or rows[0].get('status')=='stopped'
    result={'pass':True,'routeros':'7.24.5','identity':identity['name'],
            'base':'scratch','architecture':'amd64','import':'Docker-save single layer tar',
            'binary_version_output':expected,'nonroot_image_user':'65532:65532',
            'production_modified':False,'sdwan_active_acceptance':False}
    (ROOT/'runtime/container-image-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))

if __name__=='__main__':main()
