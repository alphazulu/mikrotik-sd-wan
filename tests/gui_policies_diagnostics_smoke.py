"""Windows/Tk, read-only live CHR API with application policies installed."""
import copy,importlib.util,json,sys,tempfile,time,tkinter as tk
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App,RecordDialog,POLICY_FIELDS
from sdwan.router import Router
from sdwan.policies import signature


def main():
 app=App();r=None
 try:
  app.load_lab();app.connect()
  def wait(predicate):
   end=time.monotonic()+60
   while time.monotonic()<end:
    app.update()
    if predicate():return
    time.sleep(.03)
   raise AssertionError('GUI timed out: '+app.log.get('1.0','end'))
  wait(lambda:not app.busy);assert app.connection_matches()
  r=app.make_router(app.connection_values());before=r.read_file('sdwan-active.json');cfg=json.loads(before)
  app.render_config(cfg);assert app.groups.rows and signature(app.collect())==signature(cfg)
  source=copy.deepcopy(next(p for p in cfg['policies'] if p['name']=='web'))
  with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):
   dialog=RecordDialog(app,'Политика',POLICY_FIELDS,source)
  assert dialog.vars['source_group'].get()=='phones';assert dialog.vars['dst_ports'].get()=='29100-29110'
  dialog.vars['dst_ports'].set('443,8443');dialog.accept();assert dialog.result['dst_ports']=='443,8443'
  index=next(i for i,row in enumerate(app.policies.rows) if row['name']=='web');app.policies.tree.selection_set(str(index));app.policies.move(-1)
  changed=app.collect();assert next(p for p in changed['policies'] if p['name']=='web')['priority']<next(p for p in changed['policies'] if p['name']=='voice-vlan')['priority']
  app.render_config(cfg);app.steps.select(app.diagnostics);app.run('diagnostics')
  wait(lambda:not app.busy and app.diagnostics.report is not None)
  panel=app.diagnostics;assert len(panel.wans.get_children())==3 and len(panel.policies.get_children())==7 and panel.events.get_children()
  assert all(x['sample_age_seconds'] is not None for x in panel.report['wans'])
  for key,value in {'source':'192.168.50.101','destination':'203.0.113.200','protocol':'tcp','src_port':'50000','dst_port':'29100','in_interface':'ether5'}.items():panel.flow[key].set(value)
  panel.explain_flow();assert 'web' in panel.flow_result.get() and 'wan2' in panel.flow_result.get(),panel.flow_result.get()
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'diagnostics.json'
   with patch('sdwan.diagnostics_ui.filedialog.asksaveasfilename',return_value=str(path)):panel.export()
   saved=json.loads(path.read_text(encoding='utf-8'));assert saved['identity']=='sdwan-edge'
   assert app.password.get() not in path.read_text(encoding='utf-8')
   spec=importlib.util.spec_from_file_location('cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
   package=cli.bundle(app.collect(),Path(folder)/'package');assert len(list(package.iterdir()))==len(cli.FILES)+1
  # Local aging and API failures must never leave an apparently fresh snapshot.
  panel.received_at-=cfg['health']['stale_seconds']+1;panel.tick();assert panel.report['telemetry_stale']
  panel.explain_flow();assert 'УСТАРЕЛ' in panel.flow_result.get()
  panel.auto.set(True);panel.last_auto=time.monotonic()-6
  with patch.object(app,'run') as auto_run:panel.tick();auto_run.assert_called_once_with('diagnostics')
  panel.auto.set(False)
  with patch.object(app,'make_router',side_effect=ConnectionError('fixture API unavailable')):
   app.run('diagnostics');wait(lambda:not app.busy);assert panel.report is None and 'fixture API unavailable' in panel.summary.get()
  app.run('diagnostics');wait(lambda:not app.busy and panel.report is not None)
  assert r.read_file('sdwan-active.json')==before
  # A changed connection immediately invalidates the snapshot and explainer.
  app.url.set('api://127.0.0.1:18729');assert panel.report is None and not panel.wans.get_children()
  result={'pass':True,'transport':'native API','wan_rows':3,'policy_rows':7,'group_editor':True,'selector_dialog':True,'priority_move':True,'live_diagnostics':True,'local_age_marks_stale':True,'auto_poll_read_only':True,'api_failure_clears_snapshot':True,'new_flow_explanation':True,'diagnostic_export_without_password':True,'package_files':11,'connection_change_invalidates_snapshot':True,'router_configuration_unchanged':True}
  (ROOT/'runtime/gui-policies-diagnostics-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
  print('GUI_POLICIES_DIAGNOSTICS_OK: groups/selectors/order, live dashboard/flow explain, safe export, router unchanged',flush=True)
 finally:
  if r:r.close()
  app.destroy()

if __name__=='__main__':main()
