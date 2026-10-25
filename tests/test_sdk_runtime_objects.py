"""Regressions for public SDK handling of locally reconciled control-plane state."""
import importlib.util,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from sdwan.config import load
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('sdk_runtime_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class RuntimeObjectsTests(unittest.TestCase):
 def test_repeated_dns_runtime_comments_are_not_configuration_collisions(self):
  class Router:
   def call(self,menu):
    if menu in ('ip/firewall/mangle','ip/firewall/nat','ip/route'):return [{'.id':'*1','comment':'sdwan:v1:dns-bootstrap'},{'.id':'*2','comment':'sdwan:v1:dns-bootstrap'}]
    return []
  actions=cli.inspect(Router(),load(ROOT/'config/sdwan.json'))
  self.assertTrue(actions);self.assertFalse(any(x.get('comment')=='sdwan:v1:dns-bootstrap' for x in actions))
 def test_unrecognized_similar_comment_still_reports_duplicate_ownership(self):
  class Router:
   def call(self,menu):return [{'.id':'*1','comment':'sdwan:v1:dns-bootstrap-foreign'},{'.id':'*2','comment':'sdwan:v1:dns-bootstrap-foreign'}] if menu=='ip/route' else []
  with self.assertRaisesRegex(ValueError,'duplicate managed comment'):cli.inspect(Router(),load(ROOT/'config/sdwan.json'))
 def test_oversized_utf8_payload_is_rejected_before_any_bundle_output(self):
  cfg=load(ROOT/'config/sdwan.json')
  with tempfile.TemporaryDirectory() as folder:
   fake=Path(folder);(fake/'native').mkdir()
   for name in cli.FILES:(fake/'native'/name).write_text(':put "fixture"\n')
   (fake/'native/sdwan-links.rsc').write_text('я'*30001)
   with patch.object(cli,'ROOT',fake),self.assertRaisesRegex(ValueError,'sdwan-links.rsc.*60000-byte'):
    cli.bundle(cfg,fake/'output')
   self.assertFalse((fake/'output').exists())

if __name__=='__main__':unittest.main()
