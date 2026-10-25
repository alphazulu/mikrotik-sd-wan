"""Windows GUI backend selection/export and read-only live container status."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App
from sdwan.container_config import settings
from sdwan.policies import signature

def main():
    app=App();r=None
    try:
        creds=json.loads((ROOT/'runtime/container-lab/project/runtime/credentials.json').read_text())['edge']
        app.url.set('api://127.0.0.1:38728');app.username.set(creds['username']);app.password.set(creds['password']);app.connect()
        def wait(predicate):
            end=time.monotonic()+65
            while time.monotonic()<end:
                app.update()
                if predicate():return
                time.sleep(.03)
            raise AssertionError('GUI timed out')
        wait(lambda:not app.busy);assert app.connection_matches()
        r=app.make_router(app.connection_values());before=r.read_file('sdwan-active.json');cfg=json.loads(before)
        app.render_config(cfg);assert app.backend.get()=='Локальный контейнер Rust'
        collected=app.collect()
        assert settings(collected)==settings(cfg) and signature(collected)==signature(cfg) and collected['wans']==cfg['wans']
        assert 'container-prepare' in app.action_buttons
        app.steps.select(app.diagnostics);app.run('diagnostics');wait(lambda:not app.busy and app.diagnostics.report is not None)
        assert app.diagnostics.report['backend']=='container'
        assert app.diagnostics.report['controller_mode'] in ('container','routeros-fallback')
        assert 'Решения:' in app.diagnostics.summary.get()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'diagnostics.json'
            with patch('sdwan.diagnostics_ui.filedialog.asksaveasfilename',return_value=str(path)):app.diagnostics.export()
            assert app.password.get() not in path.read_text(encoding='utf-8')
            spec=importlib.util.spec_from_file_location('gui_container_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
            package=cli.bundle(app.collect(),Path(folder)/'container');assert len(list(package.iterdir()))==10
            assert 'sdwanContainerBridge' in (package/'sdwan-controller.rsc').read_text()
            app.container_vars['subnet'].set('192.168.244.0/30');changed=app.collect()
            assert '192.168.244.0/30' in changed['local_networks']
            app.backend.set('Скрипт RouterOS');native=app.collect();assert 'controller_backend' not in native
            assert all(str(widget['state'])=='disabled' for widget in app.container_entries)
            package=cli.bundle(native,Path(folder)/'native')
            assert all((package/name).read_bytes()==(ROOT/'native'/name).read_bytes() for name in cli.FILES)
        assert r.read_file('sdwan-active.json')==before
        result={'pass':True,'backend_selector':True,'container_fields':True,'management_bypass_added':True,
                'prepare_button':True,'live_controller_mode':True,'separate_backend_bundles':True,
                'diagnostics_without_password':True,'router_configuration_unchanged':True}
        (ROOT/'runtime/gui-container-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print('GUI_CONTAINER_OK',flush=True)
    finally:
        if r:r.close()
        app.destroy()

if __name__=='__main__':main()
