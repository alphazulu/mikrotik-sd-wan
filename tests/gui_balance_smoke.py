"""Actual Tk policy-dialog round trips; no router connection or configuration."""
import copy
import json
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from configurator import BALANCE_HASHES,POLICY_FIELDS,RecordDialog,Table
from sdwan.config import load,validate

root=tk.Tk();root.withdraw();cfg=load(ROOT/'config/sdwan.json')
original=copy.deepcopy(next(p for p in cfg['policies'] if p['name']=='client101'))
checks=[]
def dialog(value):
 with patch.object(RecordDialog,'wait_window'):
  d=RecordDialog(root,'Fixture',POLICY_FIELDS,value)
 root.update_idletasks();return d
try:
 d=dialog(original);assert not d.balance_enabled.get();d.accept();assert 'balance' not in d.result
 checks.append('legacy policy remains unbalanced after editing')
 p=copy.deepcopy(original);p['wans']=['wan1','wan2','wan3'];p['balance']={'classifier':'both-addresses','weights':{'wan1':3,'wan2':1,'wan3':0}}
 d=dialog(p);assert d.balance_enabled.get();assert BALANCE_HASHES[d.balance_hash.get()]=='both-addresses'
 assert {w:int(v.get()) for w,v in d.balance_values.items()}==p['balance']['weights']
 d.accept();assert d.result['balance']==p['balance'];updated=copy.deepcopy(cfg);updated['policies']=[d.result if x['name']==p['name'] else x for x in updated['policies']];validate(updated)
 checks.append('weights, reserve and affinity survive full JSON configuration validation')
 d=dialog(original);d.vars['wans'].set('wan1,wan2,wan3');d.balance_enabled.set(True)
 for w,n in [('wan1',3),('wan2',1),('wan3',0)]:d.balance_values[w].set(str(n))
 d.accept();assert d.result['balance']['weights']==p['balance']['weights']
 checks.append('balance can be enabled and configured using real Tk controls')
 d=dialog(p);d.vars['wans'].set('wan1,wan3,wan2');errors=[]
 with patch('configurator.messagebox.showerror',side_effect=lambda *a,**k:errors.append(a)):d.accept()
 assert errors and d.result is None and d.winfo_exists();d.destroy()
 checks.append('reserve before a weighted WAN is rejected without losing the dialog')
 d=dialog(p);d.vars['mode'].set('strict');errors=[]
 with patch('configurator.messagebox.showerror',side_effect=lambda *a,**k:errors.append(a)):d.accept()
 assert errors and d.result is None;d.destroy()
 checks.append('strict and weighted distribution cannot be combined')
 d=dialog(p);d.balance_enabled.set(False);d.accept();assert 'balance' not in d.result
 checks.append('disabling balance removes only the optional balance contract')
 table=Table(root,POLICY_FIELDS,[p]);assert 'веса' in str(table.tree.item('0','values')[4]);assert table.rows[0]['mode']=='prefer';table.destroy()
 checks.append('table shows weighted mode without changing the saved policy mode')
 assert original==next(x for x in cfg['policies'] if x['name']=='client101')
 print(json.dumps({'pass':True,'checks':checks,'router_access':False},ensure_ascii=False))
finally:root.destroy()
