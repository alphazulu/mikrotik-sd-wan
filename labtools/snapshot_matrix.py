"""Headless checks of the GUI discovery/generation path against synthetic API replies."""
import argparse,base64,copy,hashlib,json,sys,unittest
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.source.resolve()))
from sdwan.discovery import discover,generate,FIELDS
from sdwan.platform_support import assess,CAPABILITY_FIELDS
from sdwan.vpn_egress import configure,MENUS

FIXTURE=json.loads((Path(__file__).parent/'fixtures/mixed-router.json').read_text())
ALLOWED=set(FIELDS)|set(CAPABILITY_FIELDS)|{'system/identity','system/resource','interface/wireguard','interface/wireguard/peers','ip/firewall/address-list'}|set(MENUS.values())

class Replay:
 def __init__(self,raw,denied=()):self.raw=copy.deepcopy(raw);self.denied=set(denied);self.calls=[]
 def call(self,path,data=None,method=None):
  assert path.endswith('/print') and path[:-6] in ALLOWED,(path,'unexpected operation')
  assert method=='POST';data=data or {};fields=set(data.get('.proplist','').split(','))
  assert not fields&{'password','private-key','preshared-key','pin','user'},fields
  self.calls.append((path,copy.deepcopy(data)));menu=path[:-6]
  if menu in self.denied:raise RuntimeError('fixture permission denied')
  rows=self.raw.get(menu,[])
  if 'count-only' in data:return {'ret':str(len(rows))}
  return [{k:v for k,v in row.items() if k in fields} for row in rows]

class SnapshotMatrix(unittest.TestCase):
 def setUp(self):self.raw=copy.deepcopy(FIXTURE)
 def build(self,*,denied=(),allow=False,missing=False):
  before=copy.deepcopy(self.raw);r=Replay(self.raw,denied);inv=discover(r)
  choices=[dict(interface=n,priority=i+1,address='192.0.2.2' if i==0 else '',gateway='192.0.2.1' if i==0 else '') for i,n in enumerate(['wan-static','wan-dhcp','wan-pppoe','lte-test'])]
  if missing:choices[-1]['interface']='missing-interface'
  try:return generate(inv,choices,probes=[dict(name='a',type='tcp-conn',host='203.0.113.10',port=443),dict(name='b',type='tcp-conn',host='203.0.113.11',port=443)],icmp_target='203.0.113.10',allow_foreign_mangle=allow),inv,r
  finally:self.assertEqual(self.raw,before)
 def test_mixed_disconnected_dynamic_wans_are_not_frozen(self):
  cfg,_,_=self.build();self.assertEqual([w['kind'] for w in cfg['wans']],['static','dhcp','pppoe','lte'])
  for w in cfg['wans'][1:]:self.assertFalse({'address','gateway'}&set(w))
  self.assertEqual(cfg['wans'][-1]['apn_profile'],'lab-apn');self.assertEqual(cfg['local_networks'],['10.77.0.0/24'])
 def test_apn_read_denied_reports_lte_problem(self):
  with self.assertRaisesRegex(ValueError,'APN'):self.build(denied=['interface/lte/apn'])
 def test_lte_menu_denied_is_not_static_wan(self):
  with self.assertRaisesRegex(ValueError,'LTE'):self.build(denied=['interface/lte'])
 def test_foreign_mangle_blocks_normal_generation(self):
  self.raw['ip/firewall/mangle']=[{'.id':'*99','action':'mark-routing','chain':'prerouting','new-routing-mark':'legacy'}]
  with self.assertRaisesRegex(ValueError,'сторонние'):self.build()
 def test_explicit_draft_preserves_foreign_rules(self):
  self.raw['ip/firewall/mangle']=[{'.id':'*99','action':'mark-routing','chain':'prerouting','new-routing-mark':'legacy'}]
  cfg,inv,_=self.build(allow=True);self.assertEqual(inv['ip/firewall/mangle'],self.raw['ip/firewall/mangle']);self.assertEqual(len(cfg['wans']),4)
 def test_missing_selected_interface_is_named(self):
  with self.assertRaisesRegex(ValueError,'missing-interface'):self.build(missing=True)
 def test_notrack_rejected_even_for_draft(self):
  self.raw['ip/firewall/raw']=[{'action':'notrack'}]
  with self.assertRaisesRegex(ValueError,'notrack'):self.build(allow=True)
 def test_missing_package_and_disabled_tool_are_explicit(self):
  cfg,inv,_=self.build();cfg['controller_backend']='container'
  self.raw['system/device-mode'][0]['fetch']='false';r=Replay(self.raw);inv=discover(r)
  report=assess(inv['resource'],inv['platform_support'],cfg)
  self.assertIn('container',report['missing_packages']);self.assertIn('fetch',report['disabled_features']);self.assertFalse(report['ready']);self.assertEqual(report['recommendation']['confidence'],'unmeasured')
 def test_vpn_destination_list_keeps_default_on_physical_wans(self):
  cfg,inv,_=self.build();before=copy.deepcopy(cfg['policies'][0])
  link=next(v for v in inv['vpn_interfaces'] if v['interface']=='vpn-test')
  changed=configure(cfg,link,name='vpn1',address_list='lab-targets',underlays=['wan1','wan2'],backups=['wan2','wan4'])
  self.assertEqual(changed['policies'][0],before)
  policy=next(p for p in changed['policies'] if p.get('destination_list')=='lab-targets');self.assertEqual(policy['wans'],['vpn1','wan2','wan4'])
 def test_all_supported_vpn_types_from_api_inventory(self):
  for kind,menu in [('wireguard','interface/wireguard'),('l2tp','interface/l2tp-client'),('sstp','interface/sstp-client'),('openvpn','interface/ovpn-client')]:
   with self.subTest(kind=kind):
    self.raw=copy.deepcopy(FIXTURE);self.raw.pop('interface/sstp-client',None)
    self.raw[menu]=[{'name':'vpn-test','running':'false','connect-to':'exit.example.test','mode':'ip','listen-port':'51820'}]
    if kind=='wireguard':self.raw['interface/wireguard/peers']=[{'interface':'vpn-test','allowed-address':'0.0.0.0/0','endpoint-address':'203.0.113.50','public-key':base64.b64encode(bytes([1])*32).decode()}]
    cfg,inv,_=self.build();link=next(v for v in inv['vpn_interfaces'] if v['interface']=='vpn-test')
    self.assertEqual(link['vpn_type'],kind)
    changed=configure(cfg,link,name='vpn1',address_list='lab-targets',underlays=['wan1'],backups=['wan4'])
    self.assertEqual(changed['wans'][-1]['kind'],'vpn');self.assertEqual(changed['wans'][-1]['vpn_type'],kind)
 def test_critical_inventory_denied_stops_discovery(self):
  with self.assertRaisesRegex(RuntimeError,'permission denied'):self.build(denied=['ip/route'])

suite=unittest.defaultTestLoader.loadTestsFromTestCase(SnapshotMatrix)
r=unittest.TextTestRunner(verbosity=2).run(suite)
report={'scope':'headless GUI discovery/generation functions, no Tk rendering or deployment','synthetic_fixture':True,'tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'pass':r.wasSuccessful(),'fixture_sha256':hashlib.sha256((Path(__file__).parent/'fixtures/mixed-router.json').read_bytes()).hexdigest(),'source_files_sha256':{str(p.relative_to(a.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((a.source/'sdwan').glob('*.py'))}}
with a.output.open('x') as stream:json.dump(report,stream,indent=2)
raise SystemExit(0 if r.wasSuccessful() else 1)
