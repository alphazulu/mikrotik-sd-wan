import copy
from pathlib import Path
import unittest
from sdwan.config import load,validate

ROOT=Path(__file__).resolve().parents[1]
class WANMaintenanceTests(unittest.TestCase):
    def test_maintenance_modes_and_bounded_deadline(self):
        base=load(ROOT/'config/sdwan.json')
        for mode,timeout in [('enabled',300),('drain',0),('drain',86400),('down',1)]:
            cfg=copy.deepcopy(base);cfg['wans'][0].update(admin_state=mode,drain_timeout_seconds=timeout);validate(cfg)
        for patch in [{'admin_state':'disabled'},{'admin_state':None},{'drain_timeout_seconds':True},{'drain_timeout_seconds':-1},{'drain_timeout_seconds':86401}]:
            cfg=copy.deepcopy(base);cfg['wans'][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):validate(cfg)

if __name__=='__main__':unittest.main()
