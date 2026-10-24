"""Offline Windows/Tk LTE configuration using a saved CHR adapter inventory."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App,RecordDialog,WAN_FIELDS
from sdwan.config import validate


def main():
    app=App();app.update();finished=False
    try:
        inv=json.loads((ROOT/'runtime/discovery-lte-adapter.json').read_text(encoding='utf-8-sig'))
        app.inventory=inv;app.bound_connection=app.connection_values();app.setup.load_inventory(inv);app.steps.select(app.setup.iface_page);app.update()
        for key,candidate in app.setup.selection.items():
            if candidate['interface'] not in ('ether2','sdwan-test-pppoe'):continue
            app.setup.tree.selection_set(key);app.setup.on_select();app.setup.toggle()
            app.setup.priority.set('1' if candidate['interface']=='ether2' else '2');app.setup.commit()
            if candidate['kind']=='lte':
                assert app.setup.apn_profile.get()=='sdwan-test-lte-apn'
                assert str(app.setup.apn_box.cget('state'))=='readonly'
                assert str(app.setup.address_box.cget('state'))==str(app.setup.gateway_box.cget('state'))=='readonly'
        app.setup.keep.set(False);app.setup.create();cfg=validate(app.collect());assert len(cfg['wans'])==2
        assert [w.get('kind','static') for w in cfg['wans']]==['static','lte']
        lte=cfg['wans'][1];assert lte['apn_profile']=='sdwan-test-lte-apn' and 'address' not in lte and 'gateway' not in lte
        assert cfg['policies'][0]['wans']==[w['name'] for w in cfg['wans']]
        with patch.object(RecordDialog,'wait_window',return_value=None):dialog=RecordDialog(app,'LTE',WAN_FIELDS,copy.deepcopy(lte),wan=True)
        assert str(dialog.widgets['apn_profile'].cget('state'))=='normal'
        assert str(dialog.widgets['address'].cget('state'))=='disabled'
        dialog.accept();assert dialog.result['apn_profile']==lte['apn_profile'] and 'address' not in dialog.result
        with patch.object(RecordDialog,'wait_window',return_value=None):dialog=RecordDialog(app,'Switch type',WAN_FIELDS,copy.deepcopy(lte),wan=True)
        dialog.vars['kind'].set('static');app.update();assert dialog.vars['apn_profile'].get()=='' and str(dialog.widgets['apn_profile'].cget('state'))=='disabled';dialog.destroy()
        spec=importlib.util.spec_from_file_location('cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        package=cli.bundle(cfg,ROOT/'build/gui-lte');assert {p.name for p in package.iterdir() if p.is_file()}=={'sdwan-config.json',*cli.FILES}
        out={'pass':True,'network_calls':0,'physical_modem_tested':False,'inventory_source':'CHR with LTE device metadata adapter','primary':'ether2','backup':'sdwan-test-pppoe','apn_profile':lte['apn_profile'],'lease_snapshot_saved':False,'readonly_runtime_fields':True,'editor_clears_apn_for_other_modes':True,'package_files':9}
        (ROOT/'runtime/gui-lte-validation.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8');print('GUI_LTE_OK: primary/static + backup/LTE, APN reference, readonly runtime fields, safe editor, 9 files',flush=True);finished=True
    finally:app.destroy()
    assert finished


if __name__=='__main__':main()
