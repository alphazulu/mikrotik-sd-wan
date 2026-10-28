import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from sdwan_lab.runtime import Lease,Run

class TapOwnershipTests(unittest.TestCase):
 def test_foreign_tap_is_not_deleted(self):
  with tempfile.TemporaryDirectory() as name:
   with Lease(Path(name)/'workspace',Path(name)/'host.lock') as lease:
    run=Run(lease,'foreign-tap',{});run.data['resources']=[{'kind':'tap','name':'synthetic','ifindex':'1','alias':'ours','deleted':False}]
    with patch('sdwan_lab.runtime.Path.exists',return_value=True),patch('sdwan_lab.runtime.Path.read_text',side_effect=['1','other']),patch('sdwan_lab.runtime.checked') as call:
     self.assertFalse(run.cleanup());call.assert_not_called()
 def test_owned_tap_is_deleted_and_recorded(self):
  with tempfile.TemporaryDirectory() as name:
   with Lease(Path(name)/'workspace',Path(name)/'host.lock') as lease:
    run=Run(lease,'owned-tap',{});run.data['resources']=[{'kind':'tap','name':'synthetic','ifindex':'1','alias':'ours','deleted':False}]
    with patch('sdwan_lab.runtime.Path.exists',return_value=True),patch('sdwan_lab.runtime.Path.read_text',side_effect=['1','ours']),patch('sdwan_lab.runtime.checked') as call:
     self.assertTrue(run.cleanup());call.assert_called_once_with(['ip','link','delete','dev','synthetic'])
    self.assertTrue(run.data['resources'][0]['deleted'])
