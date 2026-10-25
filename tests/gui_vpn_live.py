"""Windows/Tk: read-only live API discovery of four existing CHR VPN clients."""
import argparse,json,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App
from vpn_gui import VPNDialog
from policy_gui import PolicyDialog

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
  d.accept();assert d.result
  app.render_config(d.result);c=app.collect();assert 'vpn_egress' not in c and c['policies']==json.loads(before)['policies'];assert c['wans'][-1]['kind']=='vpn'
  print('PASS live-discovered VPN joins ordinary WANs without creating a routing policy or separate feature switch')
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):d=PolicyDialog(app,c,app.inventory)
  d.modes['source'].set('Address List MikroTik');d.values['source'].set('future-empty-live-users');d.modes['destination'].set('IP / подсеть');d.values['destination'].set('203.0.113.7');d.wans.set_order([c['wans'][-1]['name'],'wan2','wan1']);d.accept();assert d.result
  app.render_config(d.result);policy=next(p for p in app.collect()['policies'] if p['name']==d.vars['name'].get());assert policy['source_list']=='future-empty-live-users' and policy['destination']=='203.0.113.7/32' and policy['wans'][0]==c['wans'][-1]['name']
  print('PASS common live GUI policy combines an existing/future source Address List with a destination IP and VPN/physical priority')
  app.run('diagnostics');wait(lambda:not app.busy and app.diagnostics.report is not None);assert 'address_lists' not in app.diagnostics.report;assert r.read_file('sdwan-active.json')==before
  print('PASS GUI creation and diagnostic refresh leave router configuration unchanged and do not copy Address List membership')
 finally:
  if d:
   try:d.destroy()
   except tk.TclError:pass
  if r:r.close()
  app.destroy()
if __name__=='__main__':main()
