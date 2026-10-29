import copy
import unittest
from sdwan.platform_support import assess,collect,fingerprint,recommend,storage_options,workload


def fixture():
    resource={'version':'7.24.5 (stable)','architecture-name':'x86_64','board-name':'x86 QEMU PC','cpu':'test CPU','cpu-count':'1','cpu-frequency':'2500','total-memory':str(1024**3),'free-memory':str(512*1024**2),'free-hdd-space':str(900*1024**2)}
    caps={'system/package':[{'name':'routeros','version':'7.24.5'},{'name':'container','version':'7.24.5'}],
          'system/device-mode':[{'scheduler':'true','fetch':'true','container':'true','flagged':'false'}],
          'disk':[],'file':[],'errors':{}}
    config={'controller_backend':'container','wans':[{'name':'a','probes':[1,2,3]}],'policies':[{}],
            'container':{'storage':'sdwan-container','memory_max_bytes':16777216}}
    return resource,caps,config


class PlatformTests(unittest.TestCase):
    def test_read_only_collection_never_requests_credentials_or_executes_tools(self):
        calls=[]
        class Router:
            def call(self,path,data,method):
                calls.append((path,data,method))
                if path=='disk/print':raise RuntimeError('not allowed')
                return []
        result=collect(Router());self.assertIn('disk',result['errors'])
        self.assertTrue(all(path.endswith('/print') and method=='POST' for path,_,method in calls))
        self.assertFalse(any('password' in str(data) or 'sensitive' in str(data) for _,data,_ in calls))

    def test_ready_requires_version_packages_features_and_storage(self):
        r,c,cfg=fixture();self.assertTrue(assess(r,c,cfg)['ready'])
        c['system/package']=c['system/package'][:1]
        result=assess(r,c,cfg);self.assertFalse(result['ready']);self.assertEqual(result['missing_packages'],['container'])
        c['system/device-mode'][0]['container']='false'
        self.assertEqual(assess(r,c,cfg)['disabled_features'],['container'])

    def test_native_does_not_require_container_or_unrelated_tools(self):
        r,c,cfg=fixture();cfg['controller_backend']='routeros';c['system/package']=c['system/package'][:1];c['system/device-mode'][0].update(container='false',**{'traffic-gen':'false','bandwidth-test':'false'})
        self.assertTrue(assess(r,c,cfg)['ready'])
        self.assertNotIn('traffic-gen',assess(r,c,cfg)['disabled_features'])

    def test_unsupported_architecture_permissions_and_memory_never_silently_pass(self):
        r,c,cfg=fixture();r['architecture-name']='mipsbe';self.assertFalse(assess(r,c,cfg)['ready'])
        r,c,cfg=fixture();r['free-memory']='1000';self.assertFalse(assess(r,c,cfg)['ready'])
        c['system/device-mode']=[];self.assertFalse(assess(r,c,cfg)['ready'])
        c['system/package']=[];c['errors']['system/package']='denied'
        checks=assess(r,c,cfg)['checks'];self.assertEqual(next(x for x in checks if x['key']=='package:routeros')['state'],'unknown')

    def test_package_disabled_scheduled_or_wrong_version_blocks(self):
        for field,value in [('version','7.25'),('disabled','true'),('scheduled','uninstall')]:
            r,c,cfg=fixture();c['system/package'][1][field]=value
            with self.subTest(field=field):self.assertFalse(assess(r,c,cfg)['ready'])

    def test_external_storage_preferred_without_formatting_and_flash_is_persistent_root(self):
        r,c,cfg=fixture();c['file']=[{'name':'flash','type':'directory'}]
        c['disk']=[{'slot':'usb1','fs':'ext4','free':str(128*1024**2),'mount-filesystem':'true','mounted':'true'}]
        options=storage_options(r,c);self.assertEqual(options[0]['path'],'usb1/sdwan-container');self.assertTrue(options[0]['recommended']);self.assertEqual(options[-1]['path'],'flash/sdwan-container')
        cfg['container']['storage']='usb1/custom';self.assertTrue(assess(r,c,cfg)['ready'])
        cfg['container']['storage']='volatile-root';self.assertFalse(assess(r,c,cfg)['ready'])
        c['disk'][0]['mount-read-only']='true';self.assertEqual(len(storage_options(r,c)),1)

    def test_no_benchmark_means_unmeasured_not_invented_performance(self):
        r,_,cfg=fixture();result=recommend(r,cfg,{'schema_version':1,'profiles':[]})
        self.assertEqual(result['confidence'],'unmeasured');self.assertFalse(result['automatic']);self.assertEqual(result['evidence'],[])

    def catalog(self,r,cfg):
        return {'schema_version':1,'controller_source_sha256':'c'*64,'profiles':[{'status':'passed','controller_source_sha256':'c'*64,'report_sha256':'a'*64,'environment':'qemu-wsl','platform':fingerprint(r),'routeros_version':'7.24.5','workload':workload(cfg),'traffic':{'pps':1000},'modes':{'routeros':{'passed':True,'cpu_mean_percent':30,'memory_peak_bytes':20000000},'container':{'passed':True,'cpu_mean_percent':20,'memory_peak_bytes':24000000}}}]}

    def test_measured_choice_uses_matching_hardware_runtime_and_workload(self):
        r,_,cfg=fixture();catalog=self.catalog(r,cfg)
        result=recommend(r,cfg,catalog);self.assertEqual(result['backend'],'container');self.assertEqual(result['confidence'],'measured')
        for change in ('board','load','digest','failed','missing_measurement'):
            other=copy.deepcopy(catalog);rr=dict(r);cc=copy.deepcopy(cfg)
            if change=='board':rr['board-name']='physical ARM'
            if change=='load':cc['wans'].append({'name':'b'})
            if change=='digest':other['controller_source_sha256']='d'*64
            if change=='failed':other['profiles'][0]['status']='failed'
            if change=='missing_measurement':other['profiles'][0]['modes']={}
            with self.subTest(change=change):self.assertEqual(recommend(rr,cc,other)['confidence'],'unmeasured')
