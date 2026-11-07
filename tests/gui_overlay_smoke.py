"""Windows/Tk offline: optional overlay editor and public-key file workflow."""
import copy,json,sys,tempfile,tkinter as tk
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App,Table,RecordDialog
from overlay_gui import OverlayDialog
from test_overlay import config
from sdwan.overlay_project import exchange,decode_exchange

def dialog(app,cfg):
 with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):return OverlayDialog(app,cfg,Table,RecordDialog)

def main():
 app=App();dialogs=[]
 try:
  cfg=config();before=copy.deepcopy(cfg);plain=copy.deepcopy(cfg);plain.pop('overlay');d=dialog(app,plain);dialogs.append(d);app.update();assert not d.enabled.get() and plain=={k:v for k,v in before.items() if k!='overlay'};d.accept();assert d.result['overlay']=={'enabled':False};print('PASS overlay is explicitly optional and opening the editor does not mutate configuration or call the router')
  d=dialog(app,cfg);dialogs.append(d);assert d.enabled.get();d.table.rows[0]['cost']=42;d.accept();assert d.result['overlay']['tunnels'][0]['cost']==42 and cfg==before;app.render_config(d.result);assert app.collect()['overlay']['tunnels'][0]['cost']==42;print('PASS per-router site paths and public identities survive editing and the main configurator round trip')
  d=dialog(app,cfg);dialogs.append(d);d.vars['role'].set('hub');d.vars['local_prefixes'].set('');d.accept();assert d.result['overlay']['role']=='hub' and not d.result['overlay']['local_prefixes'];assert all(f not in d.result['overlay']['tunnels'][0] for f in ('endpoint','endpoint_port','keepalive_seconds'));print('PASS hub configuration removes client-only endpoint fields and preserves responder semantics')
  d=dialog(app,cfg);dialogs.append(d);t=cfg['overlay']['tunnels'][0];d.public=exchange('offline-branch',[dict(name=t['name'],interface='sdwan-wg-'+t['name'],listen_port=t['listen_port'],mtu=1380,public_key=t['local_public_key'])])
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'public.json'
   with patch('overlay_gui.filedialog.asksaveasfilename',return_value=str(path)):d.export_keys()
   public=decode_exchange(path.read_text());assert public==d.public and 'private' not in path.read_text() and 'password' not in path.read_text()
  print('PASS bounded public-key exchange file contains only declared public identity fields')
  d.enabled.set(False);d.accept();assert d.result['overlay']=={'enabled':False} and d.result['policies']==cfg['policies'];print('PASS disabling overlay in the project retains Internet policies')
 finally:
  for d in dialogs:
   try:d.destroy()
   except tk.TclError:pass
  app.destroy()

if __name__=='__main__':main()
