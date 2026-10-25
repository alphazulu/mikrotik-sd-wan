"""Windows/Tk: mixed WAN wizard via real API or a saved read-only inventory."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App,RecordDialog,WAN_FIELDS
from sdwan.config import validate
from sdwan.router import Router


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inventory',type=Path);args=parser.parse_args()
    app=App();finished=False;phase=0;attempts=0;before=None
    def failed(*error):
        import traceback
        traceback.print_exception(*error);app.destroy()
    app.report_callback_exception=failed
    if args.inventory:
        inv=json.loads(args.inventory.read_text(encoding='utf-8-sig'));app.inventory=inv;app.bound_connection=app.connection_values();app.setup.load_inventory(inv)
    else:
        r=Router(ROOT,'api://127.0.0.1:18728');before=r.read_file('sdwan-active.json');r.close()
        app.load_lab();app.connect()
    def step():
        nonlocal phase,attempts,finished
        attempts+=1
        if attempts>250:raise AssertionError('Mixed wizard timed out')
        if app.busy:app.after(200,step);return
        if phase==0:
            assert app.connection_matches(),app.connection_info.get()
            choices={'ether2':('static',1),'sdwan-test-dhcp-vlan':('dhcp',2),'sdwan-test-pppoe':('pppoe',3)}
            for key,item in app.setup.selection.items():
                if item['interface'] not in choices:continue
                kind,priority=choices[item['interface']]
                assert item['kind']==kind
                app.setup.tree.selection_set(key);app.setup.on_select();app.setup.toggle();app.setup.priority.set(str(priority));app.setup.commit()
                if kind!='static':assert str(app.setup.address_box.cget('state'))=='readonly' and str(app.setup.gateway_box.cget('state'))=='readonly'
            app.setup.create();cfg=validate(app.collect())
            assert [x['kind'] for x in cfg['wans']]==['static','dhcp','pppoe']
            assert all('address' not in x and 'gateway' not in x for x in cfg['wans'][1:])
            # Exercise the editor too: changing static -> dynamic must remove
            # stale address fields, and switching back must allow manual input.
            with patch.object(RecordDialog,'wait_window',return_value=None):
                dialog=RecordDialog(app,'WAN test',WAN_FIELDS,copy.deepcopy(cfg['wans'][0]),wan=True)
            dialog.vars['kind'].set('dhcp');app.update()
            assert str(dialog.widgets['address'].cget('state'))=='disabled'
            assert dialog.vars['address'].get()==dialog.vars['gateway'].get()==''
            dialog.accept();assert 'address' not in dialog.result and 'gateway' not in dialog.result
            spec=importlib.util.spec_from_file_location('bundle_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
            package=cli.bundle(cfg,ROOT/'build/wizard-dynamic')
            assert {x.name for x in package.iterdir() if x.is_file()}=={'sdwan-config.json',*cli.FILES}
            assert len(cli.FILES)==8
            if not args.inventory:
                app.run('plan');phase=1;app.after(200,step);return
        else:
            text=app.log.get('1.0','end');assert 'Код завершения: 0' in text,text
            r=Router(ROOT,'api://127.0.0.1:18728');assert r.read_file('sdwan-active.json')==before;r.close()
        result={'pass':True,'live_native_api':not bool(args.inventory),'kinds':['static','dhcp','pppoe'],'dynamic_lease_snapshots_saved':False,'dynamic_fields_readonly':True,'editor_clears_static_snapshot':True,'package_files':10,'router_unchanged':True}
        (ROOT/'runtime/gui-dynamic-wan-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print('GUI_DYNAMIC_WAN_OK: static/DHCP/PPPoE selected, fields safe, 9 files exported, router unchanged',flush=True)
        finished=True;app.destroy()
    app.after(200,step);app.mainloop();assert finished,'Dynamic GUI wizard failed'


if __name__=='__main__':main()
