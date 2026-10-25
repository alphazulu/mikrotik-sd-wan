"""Windows/Tk offline: opt-in wizard and public VPN binding preservation."""
import copy,json,sys,tkinter as tk
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App,RecordDialog,WAN_FIELDS,POLICY_FIELDS
from vpn_gui import VPNDialog
from sdwan.config import load,validate

def main():
 app=App();dialogs=[]
 try:
  cfg=load(ROOT/'config/sdwan.json');before=copy.deepcopy(cfg);link=dict(interface='sstp-existing',vpn_type='sstp',vpn_endpoint='exit.example.test',running=True);inv={'vpn_interfaces':[link],'address_list_names':['dynamic targets']}
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):d=VPNDialog(app,cfg,inv)
  dialogs.append(d);app.update();assert not d.enabled.get() and not d.nat.get() and not d.forward.get();assert cfg==before
  d.enabled.set(True);d.vars['list'].set('dynamic targets');d.vars['underlays'].set('wan2, wan1');d.vars['backups'].set('wan3');d.accept();result=validate(d.result);assert cfg==before
  assert result['policies'][0]['wans']==before['policies'][0]['wans'];assert result['policies'][1]['wans']==['vpn1','wan3'];assert result['wans'][-1]['underlays']==['wan2','wan1'];print('PASS optional VPN wizard preserves physical default and requires explicit opt-in')
  app.render_config(result);assert app.collect()['vpn_egress']['enabled']
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):editor=RecordDialog(app,'VPN probes and drain',WAN_FIELDS,result['wans'][-1],wan=True)
  dialogs.append(editor);editor.vars['admin_state'].set('drain');editor.accept();assert editor.result['vpn_endpoint']==link['vpn_endpoint'];assert editor.result['vpn_type']=='sstp';assert editor.result['underlays']==['wan2','wan1'];assert editor.result['admin_state']=='drain';assert 'address' not in editor.result;print('PASS WAN probe/admin editor retains public VPN binding and saves no session address')
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):policy=RecordDialog(app,'External Address List',POLICY_FIELDS,result['policies'][1])
  dialogs.append(policy);policy.vars['destination_list'].set('future empty list');policy.accept();assert policy.result['destination_list']=='future empty list';print('PASS future or empty external Address List remains configurable')
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):off=VPNDialog(app,result,inv)
  dialogs.append(off);assert off.enabled.get();off.enabled.set(False);off.accept();assert not off.result['vpn_egress']['enabled'];assert all(w.get('kind')!='vpn' for w in off.result['wans']);print('PASS existing opt-in persists in the dialog and optional VPN egress can be disabled without losing physical fallback policy')
 finally:
  for d in dialogs:
   try:d.destroy()
   except tk.TclError:pass
  app.destroy()
if __name__=='__main__':main()
