"""Independent router deployments must never share a mutable local payload."""
import concurrent.futures
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch
from sdwan.config import load

ROOT=Path(__file__).resolve().parents[1]
class StagingTests(unittest.TestCase):
    def test_two_router_transactions_read_their_own_payload_until_upload_finishes(self):
        spec=importlib.util.spec_from_file_location('parallel_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        base=load(ROOT/'config/sdwan.json');barrier=threading.Barrier(2);packages=[]
        def bundle(cfg,output):
            output.mkdir(exist_ok=True);(output/'sdwan-config.json').write_text(json.dumps(cfg));packages.append(output);return output
        def start(router,package,expected,**kwargs):
            barrier.wait(timeout=5);self.assertEqual(json.loads((package/'sdwan-config.json').read_text())['revision'],kwargs['revision']);return 'fixture'
        def apply(number):
            cfg=copy.deepcopy(base);cfg['revision']='router-'+str(number);router=Mock();router.read_file.return_value='{}';router.call.return_value=[];router.status.return_value={};cli.apply(router,cfg,'fixture')
        with tempfile.TemporaryDirectory() as directory,patch.object(cli,'ROOT',Path(directory)),patch.object(cli,'preflight',return_value=[]),patch.object(cli,'bundle',side_effect=bundle),patch('sdwan.deployment.start',side_effect=start),patch('sdwan.deployment.wait',return_value={'phase':'committed'}),contextlib.redirect_stdout(io.StringIO()):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(apply,(1,2)))
            self.assertEqual(len(set(packages)),2);self.assertTrue(all(not p.exists() for p in packages))

if __name__=='__main__':unittest.main()
