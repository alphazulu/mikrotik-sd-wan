"""Offline Windows/Tk regression for the Create configuration error.

Uses synthetic inventories only; never connects to a router.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from configurator import App
from sdwan.discovery import candidates
from test_discovery import fixture


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    args=parser.parse_args()
    app=App();app.update()
    checks=[];errors=[]

    def load(inventory):
        app.data=None;app.inventory=inventory
        app.bound_connection=app.connection_values()
        app.setup.load_inventory(inventory)
        app.steps.select(app.setup.iface_page);app.update()

    def select(name):
        key=next(k for k,c in app.setup.selection.items() if c['interface']==name)
        app.setup.tree.selection_set(key);app.setup.on_select();app.setup.toggle();app.update()

    def expect_error(name,field,part,action):
        errors.clear();app.steps.select(app.setup.target_page)
        action();app.update()
        assert errors and part in errors[-1],errors
        assert 'Address cannot be empty' not in errors[-1]
        assert app.steps.select()==str(app.setup.iface_page)
        assert app.setup.selection[app.setup.current]['interface']==name
        assert app.data is None
        checks.append({'check':field+' validation returns to the WAN interface','pass':True})

    def save_screenshot(name):
        try:from PIL import ImageGrab
        except ImportError:return
        folder=ROOT/'runtime/screenshots';folder.mkdir(parents=True,exist_ok=True)
        app.lift();app.update()
        try:ImageGrab.grab(bbox=(app.winfo_rootx(),app.winfo_rooty(),app.winfo_rootx()+app.winfo_width(),app.winfo_rooty()+app.winfo_height())).save(folder/name)
        except OSError as error:print('Optional screenshot unavailable: '+str(error),flush=True)

    try:
        with patch('sdwan.wizard_ui.messagebox.showerror',side_effect=lambda title,message,**kw:errors.append(message)):
            inv=fixture();inv['candidates'][0]['gateway']='';inv['candidates'][0]['gateways']=['192.0.2.1','192.0.2.3']
            load(inv);select('WAN ISP A')
            expect_error('WAN ISP A','gateway','несколько вариантов',app.setup.create)
            # The same form can be corrected and used without reconnecting.
            app.setup.gateway.set('192.0.2.1');app.setup.commit();app.setup.next_step()
            assert app.steps.select()==str(app.setup.target_page)
            checks.append({'check':'correcting the gateway permits the next step','pass':True})

            inv=fixture();inv['candidates'][0]['address']='';inv['candidates'][0]['addresses']=[]
            load(inv);select('WAN ISP A')
            expect_error('WAN ISP A','address','не указан IPv4-адрес',app.setup.next_step)

            inv=fixture()
            inv['ip/route'][0].update(gateway='203.0.113.100',**{'immediate-gw':'192.0.2.1%WAN ISP A'})
            inv['ip/route'].append({'.id':'*3','dst-address':'0.0.0.0/0','gateway':'192.0.2.1','routing-table':'provider-a'})
            inv['candidates']=candidates(inv);load(inv)
            select('WAN ISP A');select('ether2')
            app.setup.icmp.set('203.0.113.10')
            app.setup.probes.rows=[{'name':host,'type':'tcp-conn','host':host,'port':443} for host in ('example.com','example.net','example.org')]
            app.setup.probes.refresh();errors.clear();app.setup.create();app.update()
            assert not errors,errors
            cfg=app.collect();assert cfg['wans'][0]['gateway']=='192.0.2.1'
            assert cfg['wans'][0]['probes'][0]['name']=='example.com'
            assert app.steps.select()==str(app.review)
            checks.append({'check':'Create succeeds with recursive gateway discovery and domain-like probe names','pass':True})
            save_screenshot('wizard-create-regression.png')

        run=ROOT/'runtime';run.mkdir(exist_ok=True)
        (run/'gui-create-regression.json').write_text(json.dumps({'pass':True,'network_calls':0,'checks':checks},indent=2)+'\n',encoding='utf-8')
        print(f'GUI_CREATE_REGRESSION_OK: {len(checks)} checks; no network calls',flush=True)
    finally:app.destroy()


if __name__=='__main__':main()
