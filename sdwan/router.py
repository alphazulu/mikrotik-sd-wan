import base64
import ipaddress
import json
from pathlib import Path
import ssl
import urllib.request
import urllib.error
import urllib.parse


class Router:
    def __init__(self,root,url='http://127.0.0.1:18080',credentials=None,ca=None,credentials_data=None):
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme not in ('http','https','api','apis') or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError('Router URL must use api://, apis://, http:// or https:// without credentials/path')
        if parsed.scheme=='http':
            try: local=ipaddress.ip_address(parsed.hostname).is_loopback
            except ValueError: local=parsed.hostname=='localhost'
            if not local: raise ValueError('HTTP is allowed only on loopback; use HTTPS for real routers')
        c=credentials_data if credentials_data is not None else json.loads(Path(credentials or Path(root)/'runtime/credentials.json').read_text(encoding='utf-8-sig'))
        if 'edge' in c: c=c['edge']
        self.root=Path(root);self.base_url=url;self.ca=ca
        self.username=c['username'];self._credentials={'username':c['username'],'password':c['password']};self._prefix=None
        self.native=None
        if parsed.scheme in ('api','apis'):
            from .native_api import NativeAPI
            self.native=NativeAPI(parsed.hostname,parsed.port or (8729 if parsed.scheme=='apis' else 8728),c['username'],c['password'],parsed.scheme=='apis',ca)
            return
        self.url=url.rstrip('/')+'/rest/'
        self.auth='Basic '+base64.b64encode((c['username']+':'+c['password']).encode()).decode()
        ctx=ssl.create_default_context(cafile=ca)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=ctx))

    def close(self):
        if self.native:self.native.close()

    def fresh(self):
        return Router(self.root,self.base_url,ca=self.ca,credentials_data=self._credentials)

    @property
    def storage_prefix(self):
        if self._prefix is None:
            files=self.file_records(['flash'],'name,type')
            self._prefix='flash/' if any(f.get('name')=='flash' for f in files) else ''
        return self._prefix

    def call(self,path,data=None,method=None):
        if self.native:return self.native.call(path,data,method)
        req=urllib.request.Request(self.url+path.lstrip('/'),data=None if data is None else json.dumps(data).encode(),headers={'Authorization':self.auth,'Content-Type':'application/json'},method=method)
        try:
            with self.opener.open(req,timeout=45) as r:
                body=r.read();return json.loads(body) if body else None
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'{path}: {e.code} {e.read().decode()}') from e

    def file_records(self,names,properties='.id,name'):
        names=list(dict.fromkeys(names))
        if not names:return []
        queries=['name='+name for name in names]+['#|']*(len(names)-1)
        return self.call('file/print',{'.proplist':properties,'.query':queries},'POST')

    def file_entry(self,name):
        candidates=[name] if '/' in name else list(dict.fromkeys((self.storage_prefix+name,name)))
        files=self.file_records(candidates)
        if any(sum(f.get('name')==candidate for f in files)>1 for candidate in candidates):
            raise RuntimeError('Ambiguous router filename: '+name)
        found=next((f for candidate in candidates for f in files if f.get('name')==candidate),None)
        return found

    def read_file(self,name):
        found=self.file_entry(name)
        if not found:raise ValueError('Router file not found: '+name)
        result=self.call('file/get',{'number':found['.id'],'value-name':'contents'},'POST')
        if not isinstance(result,dict) or 'ret' not in result:raise RuntimeError('File contents unavailable; check sensitive permission: '+name)
        return result['ret']

    def upload(self,name,text):
        if '/' not in name:name=self.storage_prefix+name
        found=self.file_entry(name)
        if found:
            result=self.call('file/get',{'number':found['.id'],'value-name':'contents'},'POST')
            if isinstance(result,dict) and result.get('ret')==text:return False
        else:
            # RouterOS logs /file add contents verbatim. Create empty, then set:
            # /file set contents does not copy the payload into system logs.
            self.call('file',{'name':name,'type':'file'},'PUT')
            found=self.file_entry(name)
            if not found:raise RuntimeError('Created router file is not visible: '+name)
        self.call('file/'+found['.id'],{'contents':text},'PATCH')
        return True

    def status(self):
        schedulers=self.call('system/scheduler?name=sdwan-controller')
        if not schedulers:return {'controller':'not installed','enabled':False}
        enabled=schedulers[0].get('disabled')!='true'
        rows=self.call('system/script/environment/print',{'.proplist':'name,value','.query':['name=sdwanStatusJSON']},'POST')
        for row in rows:
            if row.get('name')=='sdwanStatusJSON':
                result=json.loads(row['value']);result['enabled']=enabled;return result
        return {'controller':'not initialized','enabled':enabled}
