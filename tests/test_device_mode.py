"""Router-local launch, ownership, ambiguous transport and pending-request states."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sdwan import device_mode,provisioning

class WorkerRouter:
    base_url='api://unit';username='admin'
    def __init__(self,resource=None):self.calls=[];self.item=None;self.value='running';self.resource=resource;self.job_visible=True;self.scripts={};self.serial=0
    def call(self,path,data=None,method=None):
        self.calls.append((path,data,method))
        if path=='system/identity':return {'name':'lab'}
        if path=='system/resource':return self.resource
        if path=='system/script' and method=='PUT':
            self.serial+=1;self.item=dict(data,**{'.id':'*'+str(self.serial)});self.scripts[data['name']]=self.item;return self.item
        if path=='system/script/run':return []
        if path=='system/script/print':return [r for r in self.scripts.values() if all(r.get(q.split('=',1)[0])==q.split('=',1)[1] for q in data['.query'])]
        if path=='system/script/remove':
            self.scripts={k:v for k,v in self.scripts.items() if v['.id']!=data['numbers']};self.item=None;return []
        if path=='system/script/environment/print':
            marker=data['.query'][0].split('=',1)[1]
            return [{'name':marker,'value':self.value},{'name':marker+'Job','value':'*B'}] if self.value is not None else []
        if path=='system/script/job/print':return [{'.id':'*B','owner':'admin','script':data['.query'][0].split('=',1)[1]}] if self.job_visible else []
        raise AssertionError((path,data,method))

class DeviceModeTests(unittest.TestCase):
    def test_local_launcher_uses_delta_only_and_is_removed_after_background_start(self):
        router=WorkerRouter();saved=[]
        intent=device_mode.request(router,{'container':'yes','fetch':'yes'},lambda x:saved.append(dict(x)))
        self.assertEqual([x['request_status'] for x in saved],['sending','launched'])
        source='\n'.join(data['source'] for path,data,method in router.calls if method=='PUT')
        self.assertIn(':execute script=',source);self.assertIn('container=yes fetch=yes activation-timeout=5m as-value',source)
        self.assertNotIn(' mode=',source);self.assertNotIn('traffic-gen',source)
        self.assertNotIn('system/device-mode/update',[path for path,_,_ in router.calls]);self.assertEqual(list(router.scripts),[intent['worker']])
        self.assertEqual(device_mode.observe(router,intent),'running')

    def test_invalid_flags_fail_before_intent_or_router_mutation(self):
        for flags in ({},{'mode':'advanced'},{'traffic-gen':'yes'},{'fetch':'no'},{'fetch;bad':'yes'}):
            router=WorkerRouter();saved=[]
            with self.assertRaises(ValueError):device_mode.request(router,flags,saved.append)
            self.assertFalse(saved);self.assertFalse(router.calls)

    def test_cleanup_checks_unique_name_and_comment_instead_of_reusing_id(self):
        class Replaced(WorkerRouter):
            def call(self,path,data=None,method=None):
                result=super().call(path,data,method)
                if path=='system/script/print':return [{'.id':'*A','name':'someone-else','comment':'other'}]
                return result
        router=Replaced();device_mode.request(router,{'scheduler':'yes'},lambda x:None)
        self.assertFalse(any(path=='system/script/remove' for path,_,_ in router.calls))

    def test_ambiguous_run_loss_preserves_intent_and_does_not_repeat_update(self):
        class Lost(WorkerRouter):
            def call(self,path,data=None,method=None):
                if path=='system/script/run':raise ConnectionError('lost')
                return super().call(path,data,method)
        router=Lost();saved=[]
        with self.assertRaises(ConnectionError):device_mode.request(router,{'container':'yes'},lambda x:saved.append(dict(x)))
        self.assertEqual(len(saved),1);self.assertEqual(saved[0]['request_status'],'sending')
        self.assertFalse(any(path=='system/device-mode/update' for path,_,_ in router.calls))

    def test_marker_validation_and_unknown_ended_states(self):
        router=WorkerRouter();self.assertEqual(device_mode.observe(router,{'marker':'bad;script'}),'unknown');self.assertFalse(router.calls)
        marker={'marker':'sdwanDeviceMode'+'a'*16,'worker':'sdwan-device-mode-'+'a'*16}
        for value,expected in [(None,'unknown'),('running','running'),('failed','ended'),('{"update":"canceled previous update"}','ended')]:
            router.value=value;self.assertEqual(device_mode.observe(router,marker),expected)

    def test_expired_or_failed_request_requires_another_explicit_action(self):
        for value,expired in [('failed',False),(None,True)]:
            with self.subTest(value=value,expired=expired),tempfile.TemporaryDirectory() as folder:
                router=WorkerRouter();router.value=value
                intent={'marker':'sdwanDeviceMode'+'b'*16,'expires':0 if expired else 10**15};runtime=Path(folder)/'runtime';runtime.mkdir()
                import hashlib
                file=runtime/('device-mode-'+hashlib.sha256((router.base_url+'|lab').encode()).hexdigest()[:16]+'.json');file.write_text(json.dumps(intent))
                result=provisioning._feature_request(router,{'disabled_features':['fetch']},'lab',folder,[],lambda x:None)
                self.assertFalse(result['needs_physical_confirmation']);self.assertFalse(result['request_repeated']);self.assertFalse(file.exists())
                self.assertFalse(any(path=='system/script' for path,_,_ in router.calls))

    def test_unknown_legacy_intent_is_not_blindly_reissued(self):
        with tempfile.TemporaryDirectory() as folder:
            router=WorkerRouter();runtime=Path(folder)/'runtime';runtime.mkdir()
            import hashlib
            file=runtime/('device-mode-'+hashlib.sha256((router.base_url+'|lab').encode()).hexdigest()[:16]+'.json');file.write_text('{"request_status":"sending"}')
            result=provisioning._feature_request(router,{'disabled_features':['fetch']},'lab',folder,[],lambda x:None)
            self.assertEqual(result['request_status'],'unknown');self.assertFalse(result['needs_physical_confirmation']);self.assertTrue(file.exists());self.assertFalse(router.calls)

    def test_live_worker_is_not_reissued_even_if_host_expiry_has_passed(self):
        with tempfile.TemporaryDirectory() as folder:
            router=WorkerRouter();runtime=Path(folder)/'runtime';runtime.mkdir()
            import hashlib
            file=runtime/('device-mode-'+hashlib.sha256((router.base_url+'|lab').encode()).hexdigest()[:16]+'.json')
            file.write_text(json.dumps({'marker':'sdwanDeviceMode'+'c'*16,'worker':'sdwan-device-mode-'+'c'*16,'expires':0}))
            result=provisioning._feature_request(router,{'disabled_features':['fetch']},'lab',folder,[],lambda x:None)
            self.assertTrue(result['needs_physical_confirmation']);self.assertFalse(result['request_repeated']);self.assertTrue(file.exists())
            self.assertFalse(any(path=='system/script' for path,_,_ in router.calls))

    def test_stale_running_marker_after_job_cancellation_is_ended(self):
        router=WorkerRouter();router.job_visible=False
        self.assertEqual(device_mode.observe(router,{'marker':'sdwanDeviceMode'+'d'*16,'worker':'sdwan-device-mode-'+'d'*16}),'ended')

    def test_named_worker_is_retained_while_active_and_removed_only_after_exit(self):
        router=WorkerRouter();intent=device_mode.request(router,{'fetch':'yes'},lambda x:None)
        device_mode.cleanup(router,intent);self.assertIn(intent['worker'],router.scripts)
        router.job_visible=False;device_mode.cleanup(router,intent);self.assertFalse(router.scripts)
