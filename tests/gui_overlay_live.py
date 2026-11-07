"""Windows/Tk: idempotent public key preparation on the EXISTING CHR site."""
import argparse,json,sys,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App,Table,RecordDialog
from overlay_gui import OverlayDialog
from sdwan.overlay_runtime import inventory

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--lab-root',required=True,type=Path);args=p.parse_args();profile=args.lab_root/'runtime/overlay-lab';credential=json.loads((profile/'runtime/credentials.json').read_text())['sitea'];app=App();r=None;d=None
 try:
  app.url.set('api://127.0.0.1:45729');app.username.set(credential['username']);app.password.set(credential['password']);r=app.make_router(app.connection_values());assert r.call('system/identity')['name']=='sdwan-overlay-sitea';before=r.read_file('sdwan-active.json');keys=inventory(r)
  def wait(predicate):
   end=time.monotonic()+60
   while time.monotonic()<end:
    app.update()
    if predicate():return
    time.sleep(.03)
   raise AssertionError('GUI overlay operation timed out')
  app.connect();wait(lambda:not app.busy);assert app.connection_matches();app.render_config(json.loads(before))
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):d=OverlayDialog(app,app.collect(),Table,RecordDialog)
  assert d.enabled.get() and len(d.table.rows)==2;print('PASS GUI reads the existing two-path branch topology through the connected API')
  d.prepare();wait(lambda:not d.preparing);assert d.public and len(d.public['identities'])==2,d.info.get();assert inventory(r)==keys;print('PASS GUI background key preparation reuses the actual on-router public identities without changing active interfaces')
  d.accept();assert d.result;app.render_config(d.result);assert app.collect()['overlay']['tunnels']==json.loads(before)['overlay']['tunnels'];assert r.read_file('sdwan-active.json')==before;print('PASS edited project round trip preserves peer bindings and leaves active router configuration unchanged')
  app.run('diagnostics');wait(lambda:not app.busy and app.diagnostics.report is not None);panel=app.diagnostics;assert len(panel.overlay.get_children())==2 and all(row['ospf_state']=='Full' for row in panel.report['overlay']);assert len(panel.transports.get_children())==2
  panel.received_at-=json.loads(before)['health']['stale_seconds']+1;panel.tick();assert panel.report['telemetry_stale'] and all(panel.overlay.set(i,'ospf_state')=='Устарело' for i in panel.overlay.get_children());assert r.read_file('sdwan-active.json')==before;print('PASS read-only dashboard distinguishes real Full neighbors from inner SLA admission and invalidates aged observations')
 finally:
  if d:
   try:d.destroy()
   except tk.TclError:pass
  if r:r.close()
  app.destroy()

if __name__=='__main__':main()
