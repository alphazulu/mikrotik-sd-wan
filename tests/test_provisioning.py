"""Host transfer integrity, destination ownership, URL/architecture and flags."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
from sdwan import provisioning as provision

ROOT=Path(__file__).resolve().parents[1]

class FakeRouter:
    def __init__(self):self.native=object();self.files={};self.calls=[];self.username='admin';self.base_url='api://unit';self.counter=0
    def file_entry(self,name):
        return {'.id':str(value['id']),'name':name} if (value:=self.files.get(name)) else None
    def file_digest(self,name,**kwargs):return hashlib.sha256(self.files[name]['data']).hexdigest()
    def call(self,path,data=None,method=None):
        self.calls.append((path,data,method))
        if path=='file' and method=='PUT':
            self.counter+=1;self.files[data['name']]={'id':self.counter,'type':data['type'],'data':b''};return self.file_entry(data['name'])
        if path=='file/print':
            return [dict(self.file_entry(name),type=value['type']) for name,value in self.files.items() if '.query' not in data or 'name='+name in data['.query']]
        if path=='tool/fetch':
            body=urllib.request.urlopen(data['url'],timeout=2).read();self.counter+=1
            self.files[data['dst-path']]={'id':self.counter,'type':'file','data':body};return [{'status':'finished'}]
        if path=='file/set':
            name=next(name for name,v in self.files.items() if str(v['id'])==data['numbers']);self.files[data['name']]=self.files.pop(name);return {}
        if path.startswith('file/'):
            name=next(name for name,v in self.files.items() if str(v['id'])==path.split('/')[1])
            if method=='DELETE':del self.files[name];return None
            if method=='PATCH':self.files[data['name']]=self.files.pop(name);return self.file_entry(data['name'])
        raise AssertionError((path,data,method))

class ProvisionTests(unittest.TestCase):
    def test_real_http_transfer_roundtrip_and_idempotent_no_rewrite(self):
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'image.bin';body=bytes(range(256))*300;src.write_bytes(body);sha=hashlib.sha256(body).hexdigest();router=FakeRouter()
            with patch.object(provision,'_callback',return_value=('127.0.0.1','127.0.0.1','127.0.0.1')):
                result=provision.transfer(router,src,'sdwan-container/image.tar.gz',sha)
            self.assertTrue(result['uploaded']);self.assertEqual(router.files[result['path']]['data'],body)
            self.assertFalse(any('.part-' in name for name in router.files))
            calls=len(router.calls);self.assertFalse(provision.transfer(router,src,result['path'],sha)['uploaded']);self.assertEqual(len(router.calls),calls)

    def test_wrong_remote_hash_cleans_only_owned_partial_and_never_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'image.bin';src.write_bytes(b'abc');sha=hashlib.sha256(b'abc').hexdigest();router=FakeRouter()
            router.files['keep.txt']={'id':99,'type':'file','data':b'private'}
            router.file_digest=lambda *a,**k:'0'*64
            with patch.object(provision,'_callback',return_value=('127.0.0.1','127.0.0.1','127.0.0.1')),self.assertRaisesRegex(ValueError,'mismatch'):
                provision.transfer(router,src,'image.tar.gz',sha)
            self.assertEqual(set(router.files),{'keep.txt'});self.assertFalse(any(path.startswith('container') for path,_,_ in router.calls))

    def test_wrong_existing_destination_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'x';src.write_bytes(b'abc');router=FakeRouter();router.files['image.tar.gz']={'id':1,'type':'file','data':b'unrelated'}
            with self.assertRaisesRegex(ValueError,'another file'):provision.transfer(router,src,'image.tar.gz',hashlib.sha256(b'abc').hexdigest())
            self.assertEqual(router.files['image.tar.gz']['data'],b'unrelated');self.assertEqual(router.calls,[])

    def test_invalid_paths_and_urls_fail_before_network_or_mutation(self):
        for target in ('../x','/root','a//b','a/./b'):
            with self.subTest(target=target),self.assertRaises(ValueError):provision.transfer(FakeRouter(),Path('absent'),target,'0'*64)
        for url in ('http://github.com/x','https://evil.example/image','https://github.com/alphazulu/mikrotik-sd-wan/releases/download/x?token=secret'):
            with self.subTest(url=url),self.assertRaises(ValueError):provision._public_url(url)

    def test_catalog_has_exact_architecture_and_optional_web_profiles(self):
        for arch in ('x86','x86_64','arm','arm64'):
            for enabled in (False,True):
                item=provision.image_metadata({'architecture-name':arch},{'container':{'telemetry':{'enabled':enabled}}})
                self.assertEqual(item['profile'],'web' if enabled else 'base')
                self.assertEqual(len(item['sha256']),64)
        with self.assertRaisesRegex(ValueError,'unique'):provision.image_metadata({'architecture-name':'mipsbe'},{})

    def test_downloader_rejects_truncation_and_hash_mismatch_and_reuses_verified_cache(self):
        body=b'public image';sha=hashlib.sha256(body).hexdigest();url='https://github.com/alphazulu/mikrotik-sd-wan/releases/download/v0.3.0/test.tar.gz'
        with tempfile.TemporaryDirectory() as folder,patch.object(provision.urllib.request,'urlopen',return_value=io.BytesIO(body)):
            path=provision.download(url,folder,expected=sha,size=len(body));self.assertEqual(path.read_bytes(),body)
        with tempfile.TemporaryDirectory() as folder:
            for expected,size in [('0'*64,len(body)),(sha,len(body)+1)]:
                with patch.object(provision.urllib.request,'urlopen',return_value=io.BytesIO(body)),self.assertRaises(ValueError):provision.download(url,folder,expected=expected,size=size)
            self.assertEqual(list(Path(folder).iterdir()),[])
            target=Path(folder)/sha;target.write_bytes(body)
            with patch.object(provision.urllib.request,'urlopen') as network:self.assertEqual(provision.download(url,folder,expected=sha,size=len(body)),target)
            network.assert_not_called()

    def test_feature_request_is_delta_only_and_is_not_reissued_while_pending(self):
        from test_platform_support import fixture
        resource,caps,config=fixture();config['controller_backend']='routeros';caps['system/device-mode'][0]['scheduler']='false'
        class Router:
            base_url='api://test'
            def __init__(self):self.calls=[]
            def call(self,path,data=None,method=None):
                self.calls.append((path,data,method))
                return {'name':'lab'} if path=='system/identity' else resource if path=='system/resource' else []
        router=Router()
        with tempfile.TemporaryDirectory() as folder,patch.object(provision,'collect',return_value=caps):
            one=provision.prepare_device(router,config,'lab',root=Path(folder));two=provision.prepare_device(router,config,'lab',root=Path(folder))
        changes=[call for call in router.calls if call[0]=='system/device-mode/update']
        self.assertEqual(changes,[('system/device-mode/update',{'scheduler':'yes'},'POST')]);self.assertTrue(one['needs_physical_confirmation']);self.assertFalse(two['request_repeated'])

    def test_identity_mismatch_never_provisions(self):
        class Router:
            def call(self,*args):return {'name':'other'}
        with self.assertRaisesRegex(ValueError,'identity'):provision.prepare_device(Router(),{},'expected')
        with self.assertRaisesRegex(ValueError,'identity'):provision.prepare_container(Router(),{},'expected')

class DevicePreparationOrderTests(unittest.TestCase):
    def test_fetch_restriction_requests_physical_confirmation_before_download(self):
        from test_platform_support import fixture
        resource,caps,config=fixture();caps['system/device-mode'][0]['fetch']='false';caps['system/package']=caps['system/package'][:1]
        class Router:
            base_url='api://test'
            def __init__(self):self.calls=[]
            def call(self,path,data=None,method=None):
                self.calls.append((path,data,method))
                return {'name':'lab'} if path=='system/identity' else resource if path=='system/resource' else []
        router=Router()
        with tempfile.TemporaryDirectory() as folder,patch.object(provision,'collect',return_value=caps),patch.object(provision,'download') as download:
            result=provision.prepare_device(router,config,'lab',root=Path(folder))
        download.assert_not_called();self.assertTrue(result['needs_physical_confirmation'])
        self.assertEqual([c for c in router.calls if c[0]=='system/device-mode/update'],[('system/device-mode/update',{'fetch':'yes'},'POST')])

    def test_transport_loss_keeps_pending_request_and_never_claims_enabled(self):
        from test_platform_support import fixture
        resource,caps,config=fixture();config['controller_backend']='routeros';caps['system/device-mode'][0]['scheduler']='false'
        class Router:
            base_url='api://unit'
            def call(self,path,data=None,method=None):
                if path=='system/device-mode/update':raise OSError('connection closed')
                return {'name':'lab'} if path=='system/identity' else resource
        with tempfile.TemporaryDirectory() as folder,patch.object(provision,'collect',return_value=caps):
            one=provision.prepare_device(Router(),config,'lab',root=Path(folder));two=provision.prepare_device(Router(),config,'lab',root=Path(folder))
            self.assertTrue(list((Path(folder)/'runtime').glob('device-mode-*.json')))
        self.assertFalse(one['ready']);self.assertFalse(two['request_repeated'])

class ContainerPreparationTests(unittest.TestCase):
    def test_successful_import_is_verified_against_pinned_image_id(self):
        from test_platform_support import fixture
        resource,caps,_=fixture();cfg=json.loads((ROOT/'config/examples/container.json').read_text())
        class Router:
            def call(self,path,data=None,method=None):return {'name':'lab'} if path=='system/identity' else resource
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'dist/container').mkdir(parents=True);body=b'unit image';(root/'dist/container/image.tar.gz').write_bytes(body)
            item={'filename':'image.tar.gz','sha256':hashlib.sha256(body).hexdigest(),'image_config_sha256':'b'*64,'url':'https://github.com/alphazulu/mikrotik-sd-wan/releases/download/v0.3.0/image.tar.gz'}
            with patch.object(provision,'collect',return_value=caps),patch.object(provision,'image_metadata',return_value=item),patch.object(provision,'transfer',return_value={'uploaded':True}),patch('sdwan.container_runtime.prepare',return_value={'prepared':True}) as prepare,patch('sdwan.container_runtime.read_container',side_effect=[None,{'image-id':'sha256:'+'b'*64}]):
                result=provision.prepare_container(Router(),cfg,'lab',root=root)
                self.assertTrue(result['image_verified']);prepare.assert_called_once()
            with patch.object(provision,'collect',return_value=caps),patch.object(provision,'image_metadata',return_value=item),patch.object(provision,'transfer',return_value={'uploaded':True}),patch('sdwan.container_runtime.prepare',return_value={'prepared':True}),patch('sdwan.container_runtime.read_container',side_effect=[None,{'image-id':'sha256:'+'d'*64}]),self.assertRaisesRegex(ValueError,'do not start'):
                provision.prepare_container(Router(),cfg,'lab',root=root)

    def test_already_running_verified_image_is_not_rewritten(self):
        from test_platform_support import fixture
        resource,caps,_=fixture();cfg=json.loads((ROOT/'config/examples/container.json').read_text())
        class Router:
            def call(self,path,data=None,method=None):return {'name':'lab'} if path=='system/identity' else resource
        with patch.object(provision,'collect',return_value=caps),patch.object(provision,'image_metadata',return_value={'image_config_sha256':'b'*64}),patch.object(provision,'transfer') as upload,patch('sdwan.container_runtime.read_container',return_value={'stopped':'false','image-id':'sha256:'+'b'*64}),patch('sdwan.container_runtime.check_ready') as check:
            result=provision.prepare_container(Router(),cfg,'lab');self.assertTrue(result['already_running']);self.assertFalse(result['changed']);upload.assert_not_called();check.assert_called_once()
