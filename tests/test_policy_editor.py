import copy,unittest
from pathlib import Path
from sdwan.config import load
from sdwan.policy_editor import create
from sdwan.policies import match_flow,ordered
ROOT=Path(__file__).resolve().parents[1]

class PolicyEditorTests(unittest.TestCase):
 def test_source_destination_modes_are_independent_and_atomic(self):
  cfg=load(ROOT/'config/sdwan.json');before=copy.deepcopy(cfg)
  for src,dst in [('ip','ip'),('list','ip'),('ip','list'),('list','list'),('any','list'),('list','any')]:
   c=create(cfg,name='selected',source_mode=src,source_value='192.168.50.101' if src=='ip' else 'Users',destination_mode=dst,destination_value='203.0.113.7' if dst=='ip' else 'Targets',wans=['wan3','wan1'],profile='default',priority=10)
   self.assertEqual(match_flow(c,'192.168.50.101','203.0.113.7',address_lists={'Users':['192.168.50.101'],'Targets':['203.0.113.7']})['policy'],'selected');self.assertEqual(cfg,before);self.assertEqual(c['policies'][-1]['wans'],['wan3','wan1']);self.assertTrue(all('priority' in p for p in c['policies'] if p['source']))
 def test_long_policy_names_get_unique_bounded_tables(self):
  cfg=load(ROOT/'config/sdwan.json')
  for n in (1,2):cfg=create(cfg,name='a'*29+str(n),source_mode='any',source_value='',destination_mode='list',destination_value='Targets',wans=['wan2'],profile='default',priority=n)
  tables=[p['table'] for p in cfg['policies']];self.assertEqual(len(tables),len(set(tables)));self.assertTrue(all(len(t)<=31 for t in tables))
 def test_empty_list_unknown_wan_and_duplicate_priority_fail_without_changes(self):
  cfg=load(ROOT/'config/sdwan.json');before=copy.deepcopy(cfg);params=dict(name='chosen',source_mode='list',source_value='Users',destination_mode='any',destination_value='',wans=['wan1'],profile='default',priority=10)
  for patch in ({'source_value':''},{'wans':[]},{'wans':['missing']},{'wans':['wan1','wan1']},{'priority':True}):
   with self.subTest(patch=patch),self.assertRaises(ValueError):create(cfg,**dict(params,**patch))
   self.assertEqual(cfg,before)

if __name__=='__main__':unittest.main()
