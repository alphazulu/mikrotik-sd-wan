"""Windows/Tk: read-only live API discovery of four existing CHR VPN clients."""
import argparse,json,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App
from vpn_gui import VPNDialog

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();profile=args.lab_root/'runtime/overlay-lab';credential=json.loads((profile/'runtime/credentials.json').read_text())['sitea'];app=App();r=None;d=None
 try:
  app.url.set('api://127.0.0.1:45729');app.username.set(credential['username']);app.password.set(credential['password'])
  r=app.make_router(app.connection_values());assert r.call('system/identity')['name']=='sdwan-overlay-sitea';before=r.read_file('sdwan-active.json')
  def wait(predicate):
   end=time.monotonic()+60
   while time.monotonic()<end:
    app.update()
    if predicate():return
    time.sleep(.03)
   raise AssertionError('GUI operation timed out')
  app.connect();wait(lambda:not app.busy);assert app.connection_matches();assert {v['vpn_type'] for v in app.inventory['vpn_interfaces']}=={'wireguard','l2tp','sstp','openvpn'}
  assert all(v['kind_error'] for v in app.inventory['candidates'] if v['interface'].startswith('vpn-exit-'))
  print('PASS live API discovers four public VPN bindings and keeps them separate from physical WAN selection')
  app.render_config(json.loads(before))
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):d=VPNDialog(app,app.collect(),app.inventory)
  assert not d.enabled.get();d.enabled.set(True);d.vars['list'].set('future-empty-live-list');d.accept();assert d.result
  app.render_config(d.result);c=app.collect();assert c['vpn_egress']['enabled'] and next(p['wans'] for p in c['policies'] if not p['source'])==next(p['wans'] for p in json.loads(before)['policies'] if not p['source']);assert c['wans'][-1]['kind']=='vpn'
  print('PASS live-discovered VPN builds a valid opt-in configuration while preserving physical default')
  app.run('diagnostics');wait(lambda:not app.busy and app.diagnostics.report is not None);assert 'address_lists' not in app.diagnostics.report;assert r.read_file('sdwan-active.json')==before
  print('PASS GUI creation and diagnostic refresh leave router configuration unchanged and do not copy Address List membership')
 finally:
  if d:
   try:d.destroy()
   except tk.TclError:pass
  if r:r.close()
  app.destroy()
if __name__=='__main__':main()
