"""Host-side verified provisioning. Controllers remain local on RouterOS."""
import hashlib
import http.server
import ipaddress
import json
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
import urllib.parse
import urllib.request
from .container_config import PATH,settings,telemetry,validate_backend
from .platform_support import ARCHITECTURES,VERSION,assess,collect,records

ROOT=Path(__file__).resolve().parents[1]
MAX_IMAGE=8*1024*1024


def sha256_file(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):result.update(chunk)
    return result.hexdigest()


def image_metadata(resource,config,root=ROOT):
    catalog=json.loads((Path(root)/'config/container-images.json').read_text())
    if catalog.get('schema_version')!=1 or catalog.get('routeros_version')!=VERSION:raise ValueError('Invalid image catalog version')
    arch=ARCHITECTURES.get(resource.get('architecture-name'));profile='web' if telemetry(config)['enabled'] else 'base'
    matches=[row for row in catalog['images'] if row['architecture']==arch and row['profile']==profile]
    if len(matches)!=1:raise ValueError('No unique verified image for this architecture/profile')
    item=matches[0]
    for key in ('sha256','image_config_sha256','unit_coverage_source_sha256'):
        if not re.fullmatch('[0-9a-f]{64}',item.get(key,'')):raise ValueError('Invalid pinned image digest')
    if type(item.get('bytes')) is not int or not 0<item['bytes']<=MAX_IMAGE:raise ValueError('Invalid pinned image size')
    _public_url(item['url'])
    return item


def _public_url(url,packages=False):
    parsed=urllib.parse.urlsplit(url)
    prefix='https://download.mikrotik.com/routeros/' if packages else 'https://github.com/alphazulu/mikrotik-sd-wan/releases/download/'
    if not url.startswith(prefix) or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('Refusing untrusted download URL')
    return url


def download(url,cache,*,expected=None,size=None,packages=False):
    _public_url(url,packages)
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    target=cache/(expected or hashlib.sha256(url.encode()).hexdigest())
    if expected and target.exists() and sha256_file(target)==expected and (size is None or target.stat().st_size==size):return target
    temporary=target.with_name(target.name+'.part-'+secrets.token_hex(6))
    try:
        with urllib.request.urlopen(url,timeout=30) as response,temporary.open('wb') as output:
            amount=0
            while True:
                chunk=response.read(65536)
                if not chunk:break
                amount+=len(chunk)
                if amount>MAX_IMAGE:raise ValueError('Downloaded asset exceeds allowed size')
                output.write(chunk)
        if not amount or size is not None and amount!=size:raise ValueError('Downloaded asset is truncated or has wrong size')
        if expected and sha256_file(temporary)!=expected:raise ValueError('Downloaded image SHA256 differs from catalog')
        temporary.replace(target);return target
    finally:
        temporary.unlink(missing_ok=True)


def _callback(router):
    if router.native is None:raise ValueError('Automatic verified transfer requires api:// or apis://')
    if router.native.sock is None:router.call('system/identity')
    bind=router.native.sock.getsockname()[0];peer=router.native.sock.getpeername()[0]
    if ipaddress.ip_address(bind).version!=4:raise ValueError('Use an IPv4 API connection or direct HTTPS download for this upload')
    callback=bind
    if ipaddress.ip_address(bind).is_loopback:
        active=router.call('user/active/print',{'.proplist':'name,address,via'},'POST')
        addresses={row.get('address') for row in active if row.get('name')==router.username and row.get('via','').lower() in ('api','api-ssl','apis')}
        addresses={value for value in addresses if value and not ipaddress.ip_address(value).is_loopback}
        if len(addresses)!=1:raise ValueError('Cannot determine router-reachable callback address through this API tunnel')
        callback=addresses.pop()
    return bind,peer,callback


def _fetch(router,url,target,*,https=False):
    args={'url':url,'dst-path':target,'duration':'45s','idle-timeout':'10s'}
    if https:args['check-certificate']='yes'
    result=records(router.call('tool/fetch',args,'POST'))
    if not result or result[-1].get('status')!='finished':raise RuntimeError('RouterOS did not confirm completed download')


def transfer(router,source,target,expected,*,public_url=None):
    """One temporary read-only HTTP file; native API hashes target raw bytes."""
    if not isinstance(target,str) or not PATH.fullmatch(target) or any(part in ('','.','..') for part in target.split('/')):raise ValueError('Invalid destination path')
    if router.native is None:raise ValueError('Verified upload requires api:// or apis://')
    source=Path(source)
    if not 0<source.stat().st_size<=MAX_IMAGE:raise ValueError('Local archive size exceeds transfer limit')
    if sha256_file(source)!=expected:raise ValueError('Local archive SHA256 differs')
    existing=router.file_entry(target)
    if existing:
        if router.file_digest(target,max_bytes=MAX_IMAGE)==expected:return {'uploaded':False,'sha256':expected,'path':target}
        raise ValueError('Destination already contains another file; choose a new image filename: '+target)
    parent=target.rsplit('/',1)[0] if '/' in target else ''
    current=''
    for segment in filter(None,parent.split('/')):
        current=(current+'/' if current else '')+segment
        row=router.file_entry(current)
        if row is None:router.call('file',{'name':current,'type':'directory'},'PUT')
        else:
            info=records(router.call('file/print',{'.proplist':'.id,name,type','.query':['name='+current]},'POST'))
            if len(info)!=1 or info[0].get('type') not in ('directory','disk'):raise ValueError('Container parent is not a directory')
    temporary=target+'.part-'+secrets.token_hex(8)
    server=None;thread=None
    try:
        try:
            bind,peer,callback=_callback(router);token='/'+secrets.token_urlsafe(32)
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    if self.client_address[0]!=peer or self.path!=token:
                        self.send_error(404);return
                    self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Length',str(source.stat().st_size));self.end_headers()
                    with source.open('rb') as stream:shutil.copyfileobj(stream,self.wfile,65536)
            server=http.server.ThreadingHTTPServer((bind,0),Handler);server.daemon_threads=True
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            _fetch(router,'http://'+callback+':'+str(server.server_port)+token,temporary)
        except (OSError,RuntimeError,ValueError):
            if public_url is None:raise
            _public_url(public_url)
            _fetch(router,public_url,temporary,https=True)
        finally:
            if server is not None:server.shutdown();server.server_close();thread.join(timeout=2)
        if router.file_digest(temporary,max_bytes=MAX_IMAGE)!=expected:raise ValueError('Router archive SHA256 mismatch; container will not be imported')
        found=router.file_entry(temporary)
        if not found or router.file_entry(target):raise ValueError('Router destination changed during upload')
        # RouterOS file handles can change on rename; do not GET the old ID
        # through the REST-shaped PATCH helper after a successful rename.
        router.call('file/set',{'numbers':found['.id'],'name':target},'POST')
        if not router.file_entry(target):raise RuntimeError('Renamed archive is not visible')
        return {'uploaded':True,'path':target,'sha256':expected}
    finally:
        leftover=router.file_entry(temporary)
        if leftover:router.call('file/'+leftover['.id'],method='DELETE')


def prepare_container(router,config,expected,*,root=ROOT):
    from .container_runtime import prepare,read_container
    if router.call('system/identity')['name']!=expected:raise ValueError('Router identity changed')
    validate_backend(config)
    resource=router.call('system/resource');capabilities=collect(router)
    readiness=assess(resource,capabilities,config)
    if not readiness['ready']:raise ValueError('Device prerequisites are not ready: '+', '.join(row['key'] for row in readiness['checks'] if row['state']!='ready'))
    item=image_metadata(resource,config,root)
    current=read_container(router)
    if current and current.get('stopped')!='true':
        from .container_runtime import check_ready
        if current.get('image-id','').removeprefix('sha256:')!=item['image_config_sha256']:raise ValueError('Stop and reimport the managed container through the protected upgrade workflow before changing its image')
        check_ready(router,config,expected)
        return {'prepared':True,'already_running':True,'image_verified':True,'image_id':item['image_config_sha256'],'changed':False}
    local=Path(root)/'dist/container'/item['filename']
    if not local.exists() or sha256_file(local)!=item['sha256']:
        local=download(item['url'],Path(root)/'runtime/downloads',expected=item['sha256'],size=item['bytes'])
    uploaded=transfer(router,local,settings(config)['image_file'],item['sha256'],public_url=item['url'])
    prepared=prepare(router,config,expected)
    actual=read_container(router)
    if actual.get('image-id','').removeprefix('sha256:')!=item['image_config_sha256']:raise ValueError('Imported image ID differs from pinned tested image; do not start it')
    return dict(prepared,image_verified=True,image_id=item['image_config_sha256'],upload=uploaded)


def prepare_device(router,config,expected,*,root=ROOT,timeout=180,progress=None):
    """Explicit GUI action: install matching package/reboot, then request flags."""
    if router.call('system/identity')['name']!=expected:raise ValueError('Router identity changed')
    resource=router.call('system/resource')
    if resource['version'].split()[0]!=VERSION:raise ValueError('Prepare the validated RouterOS '+VERSION+' version first')
    notify=progress or (lambda message:None)
    capabilities=collect(router);actions=[]
    preliminary=assess(resource,capabilities,config)
    if any(row['key']=='device-flagged' for row in preliminary['checks']):return preliminary
    if 'fetch' in preliminary['disabled_features']:
        return _feature_request(router,preliminary,expected,root,actions,notify)
    if config.get('controller_backend')=='container':
        arch=resource.get('architecture-name')
        if arch not in ARCHITECTURES:raise ValueError('Architecture does not support containers')
        package=next((row for row in capabilities['system/package'] if row.get('name')=='container'),None)
        if package is None and 'system/package' in capabilities['errors']:raise ValueError('Cannot inspect installed packages')
        reboot=False
        if not package or package.get('version')!=VERSION:
            suffix='' if arch in ('x86','x86_64') else '-'+arch
            filename='container-'+VERSION+suffix+'.npk';url='https://download.mikrotik.com/routeros/'+VERSION+'/'+filename
            notify('Загрузка подходящего пакета container с сервера MikroTik и проверка передачи...')
            local=download(url,Path(root)/'runtime/downloads',packages=True)
            transfer(router,local,filename,sha256_file(local))
            actions.append('matching container package uploaded');reboot=True
        if package and package.get('disabled')=='true':
            router.call('system/package/enable',{'numbers':package['.id']},'POST');reboot=True
        if reboot:
            notify('Пакет подготовлен. Выполняется штатная перезагрузка и проверка подключения...')
            try:router.call('system/reboot',{},'POST')
            except OSError:pass
            router.close();deadline=time.monotonic()+timeout
            while time.monotonic()<deadline:
                try:
                    if router.call('system/identity')['name']!=expected:raise ValueError('Router identity changed after reboot')
                    capabilities=collect(router)
                    if any(row.get('name')=='container' and row.get('version')==VERSION and row.get('disabled')!='true' for row in capabilities['system/package']):break
                except (OSError,RuntimeError):router.close()
                time.sleep(2)
            else:raise TimeoutError('Package installation/reconnection not confirmed')
            resource=router.call('system/resource')
            if resource['version'].split()[0]!=VERSION:raise ValueError('RouterOS version changed unexpectedly after package installation')
            actions.append('matching container package active after reboot')
    readiness=assess(resource,capabilities,config)
    return _feature_request(router,readiness,expected,root,actions,notify)


def _feature_request(router,readiness,expected,root,actions,notify):
    pending_path=Path(root)/'runtime'/('device-mode-'+hashlib.sha256((router.base_url+'|'+expected).encode()).hexdigest()[:16]+'.json')
    if readiness['disabled_features']:
        if pending_path.exists():return {'ready':False,'needs_physical_confirmation':True,'features':readiness['disabled_features'],'actions':actions,'request_repeated':False}
        features={name:'yes' for name in readiness['disabled_features']}
        # Save intent before sending: the API can disconnect or wait for the
        # physical confirmation. Never blindly repeat a request that may exist.
        pending_path.parent.mkdir(exist_ok=True,parents=True);pending_path.write_text(json.dumps({'identity':expected,'features':list(features),'request_status':'sending'})+'\n')
        notify('Запрашивается изменение device-mode: '+', '.join(features)+'. Подтвердите кнопкой reset/mode или отключением питания; обычная перезагрузка не подтверждает изменение.')
        try:response=router.call('system/device-mode/update',features,'POST')
        except OSError as error:response={'confirmation_status':'unverified; check flags after physical confirmation','transport_error':type(error).__name__}
        except RuntimeError:
            pending_path.unlink(missing_ok=True)
            raise
        if 'canceled' in json.dumps(response).lower():
            pending_path.unlink(missing_ok=True)
            return {'ready':False,'needs_physical_confirmation':False,'request_started':False,'actions':actions,'instructions':'MikroTik отменил предыдущий запрос device-mode. Новый запрос не запущен; проверьте изменения и повторите действие явно.'}
        return {'ready':False,'needs_physical_confirmation':True,'features':list(features),'actions':actions,'router_reply':response,'instructions':'Подтвердите изменение кнопкой reset/mode или отключением питания согласно инструкции MikroTik. Обычная перезагрузка не подтверждает device-mode. После запуска повторите проверку.'}
    pending_path.unlink(missing_ok=True)
    return dict(readiness,actions=actions)
