import copy,json,unittest
from test_overlay import config,key
from sdwan.overlay_project import exchange,decode_exchange,with_local_keys,configure

def identities():return [dict(name='hub-wan1',interface='sdwan-wg-hub-wan1',listen_port=51821,mtu=1380,public_key=key(1))]

class ProjectTests(unittest.TestCase):
 def test_public_exchange_round_trip_and_no_secret_fields(self):
  public=exchange('branch-lab',identities());self.assertEqual(decode_exchange(json.dumps(public)),public)
  for patch in ({'private_key':key(9)},{'password':'placeholder'},{'listen_port':True},{'interface':'wrong'}):
   rows=identities();rows[0].update(patch)
   with self.subTest(patch=patch),self.assertRaises(ValueError):exchange('branch-lab',rows)
  with self.assertRaises(ValueError):decode_exchange(json.dumps(dict(public,credentials={})))
 def test_exchange_limits_identity_uniqueness_and_strict_schema(self):
  for value in ('x'*32769,'[]',json.dumps({'schema_version':True,'router':'branch','identities':identities()})):
   with self.subTest(value=value[:40]),self.assertRaises(ValueError):decode_exchange(value)
  for rows in ([],identities()*2):
   with self.assertRaises(ValueError):exchange('branch',rows)
  with self.assertRaises(ValueError):exchange('branch\n',identities())
 def test_readback_preserves_edited_fields_but_rejects_stale_geometry(self):
  tunnels=config()['overlay']['tunnels'];before=copy.deepcopy(tunnels);tunnels[0]['cost']=42;result=with_local_keys(tunnels,identities(),1380);self.assertEqual(result[0]['cost'],42);self.assertEqual(tunnels[0]['local_public_key'],before[0]['local_public_key']);self.assertIsNot(result,tunnels)
  for field,value in [('name','changed'),('listen_port',51822)]:
   changed=copy.deepcopy(tunnels);changed[0][field]=value
   with self.assertRaises(ValueError):with_local_keys(changed,identities(),1380)
  with self.assertRaises(ValueError):with_local_keys(tunnels,identities(),1390)
 def test_editor_is_atomic_and_disabling_keeps_other_scopes(self):
  cfg=config();before=copy.deepcopy(cfg);o=copy.deepcopy(cfg['overlay']);o['mtu']=1390;result=configure(cfg,o);self.assertEqual(result['overlay']['mtu'],1390);self.assertEqual(cfg,before)
  o['remote_prefixes']=['0.0.0.0/0']
  with self.assertRaises(ValueError):configure(cfg,o)
  self.assertEqual(cfg,before);off=configure(cfg,{'enabled':False});self.assertEqual(off['overlay'],{'enabled':False});self.assertEqual(off['wans'],cfg['wans']);self.assertEqual(off['policies'],cfg['policies'])

if __name__=='__main__':unittest.main()
