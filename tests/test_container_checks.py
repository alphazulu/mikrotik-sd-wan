import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('container_checks',ROOT/'tools/container_checks.py');checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
class ContainerCoverageGateTests(unittest.TestCase):
 def fixture(self,folder):
  root=Path(folder);(root/'container-controller/src').mkdir(parents=True);(root/'container-controller/web').mkdir();(root/'container-controller/src/lib.rs').write_text('pub mod logic;\n');(root/'container-controller/src/logic.rs').write_text('pub fn decide()->bool{true}\n');(root/'container-controller/web/app.js').write_text('(()=>{})();\n');return root
 def report(self,root,covered=1):return {'data':[{'files':[{'filename':str(root/'container-controller/src/logic.rs'),'summary':{'lines':{'count':1,'covered':covered},'functions':{'count':1,'covered':covered},'regions':{},'branches':{}}}]}]}
 def test_every_rust_file_requires_full_lines_and_functions(self):
  with tempfile.TemporaryDirectory() as folder:
   root=self.fixture(folder);checks.rust_summary(self.report(root),'base',root)
   with self.assertRaises(ValueError):checks.rust_summary(self.report(root,0),'base',root)
   (root/'container-controller/src/unmeasured.rs').write_text('pub fn missing(){}')
   with self.assertRaisesRegex(ValueError,'Unmeasured'):checks.rust_summary(self.report(root),'web',root)
 def test_module_only_exception_cannot_hide_executable_code(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'lib.rs';p.write_text('#[cfg(feature="web")]\npub mod web;\n');self.assertTrue(checks.module_only(p));p.write_text('pub mod web;\npub fn uncovered(){}');self.assertFalse(checks.module_only(p))
 def test_browser_gate_uses_exact_counts_and_rejects_missing_files(self):
  with tempfile.TemporaryDirectory() as folder:
   root=self.fixture(folder);row={'path':str(root/'container-controller/web/app.js'),'totalLineCount':1000000,'coveredLineCount':1000000,'totalFunctionCount':1,'coveredFunctionCount':1};events=[{'coverage':{'files':[row]}}];checks.js_summary(events,root);row['coveredLineCount']-=1
   with self.assertRaises(ValueError):checks.js_summary(events,root)
   with self.assertRaises(ValueError):checks.js_summary([{'coverage':{'files':[]}}],root)
 def test_aliased_root_resolves_before_relative_coverage_paths(self):
  with tempfile.TemporaryDirectory() as folder:
   root=self.fixture(Path(folder)/'real');alias=Path(folder)/'alias'
   try:alias.symlink_to(root,target_is_directory=True)
   except OSError:self.skipTest('Creating a directory alias requires host privileges')
   result=checks.rust_summary(self.report(root),'base',alias);self.assertIn('container-controller/src/logic.rs',result)
   row={'path':str(root/'container-controller/web/app.js'),'totalLineCount':1,'coveredLineCount':1,'totalFunctionCount':1,'coveredFunctionCount':1}
   self.assertIn('container-controller/web/app.js',checks.js_summary([{'coverage':{'files':[row]}}],alias))
 def test_stale_or_partial_receipt_requires_a_fresh_run(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(checks,'source_digest',return_value='current'),patch.object(checks,'run',return_value={'pass':True}) as run:
   output=Path(folder);receipt=output/'result.json';receipt.write_text(json.dumps({'pass':True,'source_sha256':'old','coverage':{'base':{},'web':{},'javascript':{}}}));checks.ensure_coverage(output);self.assertEqual(run.call_count,1);receipt.write_text(json.dumps({'pass':True,'source_sha256':'current','coverage':{'base':{}}}));checks.ensure_coverage(output);self.assertEqual(run.call_count,2)
 def test_exact_source_receipt_is_reused_without_repeating_identical_tests(self):
  with tempfile.TemporaryDirectory() as folder,patch.object(checks,'source_digest',return_value='current'),patch.object(checks,'run') as run:
   output=Path(folder);result={'pass':True,'source_sha256':'current','coverage':{'base':{},'web':{},'javascript':{}}};(output/'result.json').write_text(json.dumps(result));self.assertEqual(checks.ensure_coverage(output),result);run.assert_not_called()
