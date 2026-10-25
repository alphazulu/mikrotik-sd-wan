import base64
import unittest
from unittest.mock import patch
from sdwan.overlay_runtime import inventory,prepare_keys,PROPERTIES,PREFIX

KEY=base64.b64encode(bytes([7])*32).decode()
class Router:
    def __init__(self):self.rows=[];self.calls=[];self.fail_second=False
    def read_file(self,name):raise ValueError("Router file not found: "+name)
    def call(self,path,data=None,method=None):
        self.calls.append((path,data,method))
        if path=='system/identity':return {'name':'fixture'}
        if path=='interface/wireguard/print':return list(self.rows)
        if path=='interface/wireguard' and method=='PUT':
            if self.fail_second and self.rows:raise RuntimeError('simulated API failure')
            row=dict(data,**{'.id':'*'+str(len(self.rows)+1),'public-key':KEY});self.rows.append(row);return {'.id':row['.id']}
        if path.endswith('/print'):return []
        if path.startswith('interface/wireguard/') and method=='DELETE':self.rows=[r for r in self.rows if r['.id']!=path.rsplit('/',1)[1]];return
        raise AssertionError((path,data,method))
class OverlayRuntimeTests(unittest.TestCase):
    def test_preparation_is_idempotent_and_never_requests_private_keys(self):
        router=Router();request=[{'name':'hub-wan1','listen_port':51821}]
        first=prepare_keys(router,request,'fixture');self.assertEqual(prepare_keys(router,request,'fixture'),first)
        self.assertEqual(sum(method=='PUT' for _,_,method in router.calls),1)
        self.assertTrue(all(data['.proplist']==PROPERTIES and 'private-key' not in data['.proplist'] for path,data,_ in router.calls if path=='interface/wireguard/print'))
        router.rows[0]['private-key']='unexpected secret';self.assertNotIn('private-key',inventory(router)[0])
    def test_foreign_collision_rejected_before_any_creation(self):
        router=Router();router.rows=[{'name':'sdwan-wg-conflict','listen-port':'51822','mtu':'1380','comment':'foreign'}]
        with self.assertRaisesRegex(ValueError,'Foreign'):prepare_keys(router,[{'name':'first','listen_port':51821},{'name':'conflict','listen_port':51822}],'fixture')
        self.assertFalse(any(method=='PUT' for _,_,method in router.calls))
    def test_partial_failure_removes_only_untouched_interfaces_created_here(self):
        router=Router();router.fail_second=True
        with self.assertRaisesRegex(RuntimeError,'simulated'):prepare_keys(router,[{'name':'first','listen_port':51821},{'name':'second','listen_port':51822}],'fixture')
        self.assertEqual(router.rows,[])
    def test_pending_transaction_defers_key_preparation_without_mutations(self):
        router=Router()
        with patch("sdwan.overlay_runtime.read_state",return_value={"phase":"checking"}),self.assertRaisesRegex(ValueError,"pending protected"):
            prepare_keys(router,[{"name":"first","listen_port":51821}],"fixture")
        self.assertFalse(any(method=="PUT" for _,_,method in router.calls))
    def test_identity_and_secret_fields_are_rejected_before_creation(self):
        router=Router()
        for requests,identity in [([{'name':'first','listen_port':51821}],'changed'),([{'name':'first','listen_port':51821,'private_key':'secret'}],'fixture')]:
            with self.assertRaises(ValueError):prepare_keys(router,requests,identity)
        self.assertFalse(any(method=='PUT' for _,_,method in router.calls))

if __name__=='__main__':unittest.main()
