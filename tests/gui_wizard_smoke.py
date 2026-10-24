# Run using Windows Python while the CHR lab is running.
import sys,json,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from configurator import App
from sdwan.router import Router
from sdwan.config import validate
ROOT=Path(__file__).resolve().parents[1]
app=App();finished=False;attempts=0;phase=0
creds=json.loads((ROOT/'runtime/credentials.json').read_text())['edge']
r=Router(ROOT,'api://127.0.0.1:18728',credentials_data=creds)
active=next(f for f in r.call('file/print',{'.proplist':'.id,name'},'POST') if f['name']=='sdwan-active.json')
before=r.read_file('sdwan-active.json');r.close()
def failure(*args):
    traceback.print_exception(*args);app.destroy()
app.report_callback_exception=failure
app.load_lab();assert app.data is None;app.connect()
def step():
    global attempts,phase,finished
    attempts+=1
    if attempts>200:raise AssertionError('Wizard timed out')
    if app.busy:app.after(200,step);return
    if phase==0:
        assert app.connection_matches(),app.connection_info.get()
        assert app.inventory['identity']['name']=='sdwan-edge'
        assert len(app.setup.tree.get_children())==6
        assert not any(c['enabled'] for c in app.setup.selection.values())
        # Exercise actual checkbox events, not only programmatic selection.
        from types import SimpleNamespace
        for key,entry in app.setup.selection.items():
            if entry['interface'] not in ('ether2','ether3','ether4'):continue
            box=app.setup.tree.bbox(key,column='wan');assert box
            app.setup.click_checkbox(SimpleNamespace(x=box[0]+10,y=box[1]+box[3]//2))
            app.update()
        app.setup.create();c=validate(app.collect())
        assert [w['interface'] for w in c['wans']]==['ether2','ether3','ether4']
        assert len(c['policies'])==4
        assert creds['password'] not in json.dumps(c)
        (ROOT/'runtime/wizard-gui-generated.json').write_text(json.dumps(c,indent=2),encoding='utf-8')
        (ROOT/'config/discovered-sdwan-edge.json').write_text(json.dumps(c,indent=2)+'\n',encoding='utf-8')
        import importlib.util
        spec=importlib.util.spec_from_file_location('bundle_cli',ROOT/'sdwan.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        m.bundle(c,ROOT/'build/wizard-sdwan-edge')
        package=sorted(p.name for p in (ROOT/'build/wizard-sdwan-edge').iterdir() if p.is_file())
        assert set(package)=={'sdwan-config.json',*m.FILES},package
        assert 'sdwan-dataplane.rsc' in package
        app.run('plan');phase=1;app.after(200,step);return
    text=app.log.get('1.0','end');assert 'Код завершения: 0' in text,text
    assert 'sdwan:v1:classify:' in text and 'sdwan:v1:reply:' in text
    remote=Router(ROOT,'api://127.0.0.1:18728',credentials_data=creds)
    after=remote.read_file('sdwan-active.json');remote.close();assert before==after
    app.steps.select(app.setup.iface_page);app.update();app.lift();app.focus_force();app.update()
    try:
        from PIL import ImageGrab
    except ImportError:ImageGrab=None
    if ImageGrab:
        folder=ROOT/'runtime/screenshots';folder.mkdir(exist_ok=True)
        try:
            ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save(folder/'wizard-interfaces.png')
            app.steps.select(app.review);app.update()
            ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save(folder/'wizard-generated.png')
        except OSError as error:print('Optional screenshot unavailable: '+str(error),flush=True)
    result={'pass':True,'transport':'RouterOS native API','interfaces_read':len(app.inventory['candidates']),'wans':[w['interface'] for w in app.collect()['wans']],'config_valid':True,'existing_policies_preserved':True,'router_active_config_unchanged':True,'password_saved_in_config':False,'plan_api_ok':True,'package_files':sorted(p.name for p in (ROOT/'build/wizard-sdwan-edge').iterdir() if p.is_file()),'connection_mark_plan_ok':True}
    (ROOT/'runtime/gui-wizard-validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('GUI_WIZARD_NATIVE_API_OK: connected, read 6 interfaces, selected 3 WANs, generated JSON/RSC, plan succeeded, router unchanged',flush=True)
    finished=True;app.destroy()
app.after(200,step);app.mainloop()
assert finished,'GUI wizard failed'
