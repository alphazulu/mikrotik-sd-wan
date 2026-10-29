"""Installing a container must use the selected mounted disk's actual status."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sdwan.platform_support import assess, collect, storage_options
from sdwan import provisioning
from test_platform_support import fixture

ROOT=Path(__file__).resolve().parents[1]


class StorageReadinessTests(unittest.TestCase):
    def disk(self,**changes):
        return dict({'slot':'usb1','mount-point':'data','fs':'ext4','free':str(128*1024**2),
                     'mount-filesystem':'true','mounted':'true','mount-read-only':'false'},**changes)

    def setup_storage(self,**changes):
        resource,caps,config=fixture()
        caps['disk']=[self.disk(**changes)]
        config['container']['storage']='data/custom-controller'
        return resource,caps,config

    def check(self,r,c,cfg):
        return next(row for row in assess(r,c,cfg)['checks'] if row['key']=='container-storage')

    def test_actual_mount_point_is_offered_and_slot_is_not_internal_storage(self):
        r,c,cfg=self.setup_storage()
        self.assertEqual(storage_options(r,c)[0]['path'],'data/sdwan-container')
        self.assertEqual(self.check(r,c,cfg)['state'],'ready')
        cfg['container']['storage']='usb1/sdwan-container'
        self.assertEqual(self.check(r,c,cfg)['state'],'blocked')
        self.assertIn('data',self.check(r,c,cfg)['detail'])

    def test_unusable_disk_never_falls_back_to_internal_free_space(self):
        cases=[{'mount-read-only':'true'},{'disabled':'true'}, {'mounted':'false'},
               {'mount-filesystem':'false'}, {'fs':'fat32'}, {'fs':'tmpfs'},
               {'free':str(16*1024**2-1)}]
        for change in cases:
            with self.subTest(change=change):
                r,c,cfg=self.setup_storage(**change)
                self.assertEqual(self.check(r,c,cfg)['state'],'blocked')
                self.assertFalse(assess(r,c,cfg)['ready'])

    def test_unknown_disk_space_or_mount_is_not_ready(self):
        for change in [{'free':'unknown'},{'free':'-1'},{'mount-point':''},{'mounted':None}]:
            with self.subTest(change=change):
                r,c,cfg=self.setup_storage(**change)
                if change.get('mount-point')=='':cfg['container']['storage']='usb1/controller'
                self.assertNotEqual(self.check(r,c,cfg)['state'],'ready')
                self.assertFalse(any(row['medium']=='external' for row in storage_options(r,c)))

    def test_legacy_slot_and_file_mount_confirmation(self):
        r,c,cfg=self.setup_storage();disk=c['disk'][0];disk.pop('mount-point');disk.pop('mounted')
        cfg['container']['storage']='usb1/controller'
        self.assertEqual(self.check(r,c,cfg)['state'],'unknown')
        # A directory with this name is not proof of a mounted disk.
        c['file']=[{'name':'usb1','type':'directory'}]
        self.assertEqual(self.check(r,c,cfg)['state'],'unknown')
        c['file'][0]['type']='disk'
        self.assertEqual(self.check(r,c,cfg)['state'],'ready')
        disk['mounted']='false'
        self.assertEqual(self.check(r,c,cfg)['state'],'blocked')

    def test_inspection_errors_block_external_and_internal_installation(self):
        for menu in ['disk','file']:
            for selected in ['data/custom-controller','sdwan-container']:
                with self.subTest(menu=menu,selected=selected):
                    r,c,cfg=self.setup_storage();c['errors'][menu]='permission denied'
                    cfg['container']['storage']=selected
                    self.assertEqual(self.check(r,c,cfg)['state'],'unknown')
                    self.assertFalse(any(row['recommended'] for row in storage_options(r,c)))

    def test_file_disk_without_disk_inventory_is_not_internal_storage(self):
        r,c,cfg=self.setup_storage();c['disk']=[];c['file']=[{'name':'data','type':'disk'}]
        self.assertEqual(self.check(r,c,cfg)['state'],'unknown')

    def test_empty_or_unsafe_mount_point_does_not_offer_slot_path(self):
        for name in ['', '../data', '/data', 'data//nested', 'data/./nested', 'data/../nested']:
            with self.subTest(name=name):
                r,c,cfg=self.setup_storage(**{'mount-point':name})
                self.assertFalse(any(row['medium']=='external' for row in storage_options(r,c)))
                cfg['container']['storage']='usb1/controller'
                self.assertEqual(self.check(r,c,cfg)['state'],'blocked')

    def test_mount_matching_uses_complete_path_components(self):
        r,c,cfg=self.setup_storage(**{'mount-point':'data/containers','mount-read-only':'true'})
        cfg['container']['storage']='data/containers/controller'
        self.assertEqual(self.check(r,c,cfg)['state'],'blocked')
        cfg['container']['storage']='data/containers-backup/controller'
        self.assertEqual(self.check(r,c,cfg)['state'],'ready')

    def test_duplicate_mount_is_unknown_and_free_space_boundary_is_explicit(self):
        r,c,cfg=self.setup_storage(free=str(16*1024**2))
        self.assertEqual(self.check(r,c,cfg)['state'],'ready')
        c['disk'].append(dict(c['disk'][0],slot='usb2'))
        self.assertEqual(self.check(r,c,cfg)['state'],'unknown')

    def test_native_mode_does_not_require_storage_for_an_unused_container(self):
        r,c,cfg=self.setup_storage(**{'mount-read-only':'true'});cfg['controller_backend']='routeros'
        self.assertTrue(assess(r,c,cfg)['ready'])

    def test_read_only_collection_requests_actual_mount_metadata(self):
        calls=[]
        class Router:
            def call(self,path,data,method):
                calls.append((path,data,method));return []
        collect(Router())
        fields=next(data['.proplist'].split(',') for path,data,_ in calls if path=='disk/print')
        self.assertIn('mount-point',fields);self.assertIn('mounted',fields)
        self.assertTrue(all(path.endswith('/print') and method=='POST' for path,_,method in calls))

    def test_failed_storage_check_prevents_download_transfer_and_container_prepare(self):
        resource,caps,_=self.setup_storage(**{'mount-read-only':'true'})
        cfg=json.loads((ROOT/'config/examples/container.json').read_text());cfg['container']['storage']='data/controller'
        class Router:
            def __init__(self):self.calls=[]
            def call(self,path,data=None,method=None):
                self.calls.append(path)
                return {'name':'lab'} if path=='system/identity' else resource
        r=Router()
        with patch.object(provisioning,'collect',return_value=caps), \
             patch.object(provisioning,'image_metadata') as image, \
             patch.object(provisioning,'download') as download, \
             patch.object(provisioning,'transfer') as transfer, \
             patch('sdwan.container_runtime.prepare') as prepare:
            with self.assertRaisesRegex(ValueError,'container-storage'):
                provisioning.prepare_container(r,cfg,'lab')
        for operation in [image,download,transfer,prepare]:operation.assert_not_called()
        self.assertEqual(r.calls,['system/identity','system/resource'])
