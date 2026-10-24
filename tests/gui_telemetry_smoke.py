"""Offline Windows/Tk checks for optional web configuration. No router writes."""
from pathlib import Path
import json
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App
from sdwan.config import load
from sdwan.container_config import telemetry

def main():
    app=App();checks=[];token='b'*64
    try:
        cfg=load(ROOT/'config/examples/container.json');app.render_config(cfg);app.update()
        assert not app.telemetry_enabled.get();assert 'telemetry' not in app.collect()['container'];checks.append('default off preserves existing JSON')
        app.telemetry_enabled.set(True);app.telemetry_changed()
        assert app.container_vars['image_file'].get()=='sdwan-controller-web-amd64.tar.gz'
        app.telemetry_vars['allowed_sources'].set('192.168.50.0/24');app.telemetry_vars['allowed_interfaces'].set('ether5')
        enabled=app.collect();assert telemetry(enabled)['enabled'];checks.append('explicit LAN scopes and web image selected')
        app.render_config(enabled);app.update();assert app.collect()==enabled;checks.append('re-render and JSON round trip')
        app.telemetry_enabled.set(False);app.telemetry_changed();assert app.container_vars['image_file'].get()=='sdwan-controller-amd64.tar.gz'
        app.backend.set('Скрипт RouterOS');native=app.collect();assert 'container' not in native
        assert all(str(w['state'])=='disabled' for w in app.telemetry_entries);checks.append('RouterOS backend disables optional web')
        app.render_config(enabled);app.inventory={'identity':{'name':'edge'}};app.bound_connection=app.connection_values()
        class ReadOnly:
            def call(self,*args,**kwargs):assert args==('system/identity',);return {'name':'edge'}
            def read_file(self,*args):assert args[0].endswith('/secrets/web-token');return token
            def close(self):pass
        before=app.log.get('1.0','end')
        with patch.object(app,'make_router',return_value=ReadOnly()),patch('sdwan.container_runtime.check_ready',return_value={}):
            app.run('web-token');end=time.monotonic()+10
            while app.busy and time.monotonic()<end:app.update();time.sleep(.02)
        assert not app.busy;assert app.clipboard_get()==token
        assert token not in app.log.get('1.0','end');assert token not in json.dumps(app.collect());checks.append('token uses clipboard without JSON or log exposure')
        with patch('configurator.webbrowser.open') as browser:
            app.open_web();browser.assert_called_once_with('http://172.31.255.2:8080/')
        checks.append('browser URL contains no token')
        run=ROOT/'runtime';run.mkdir(exist_ok=True)
        (run/'gui-telemetry-validation.json').write_text(json.dumps({'pass':True,'checks':checks},indent=2)+'\n')
        print('GUI_TELEMETRY_OK '+str(len(checks)),flush=True)
    finally:
        try:
            if app.clipboard_get()==token:app.clipboard_clear()
        except Exception:pass
        app.destroy()
if __name__=='__main__':main()
