"""Windows/Tk offline: ordinary VPN WAN and common IP/list policy wizard."""
import copy,sys,tkinter as tk
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from configurator import App,RecordDialog,WAN_FIELDS
from vpn_gui import VPNDialog
from policy_gui import PolicyDialog
from sdwan.config import load,validate
from sdwan.policies import ordered

def dialog(cls,*args):
 with patch.object(tk.Toplevel,'wait_window',return_value=None),patch.object(tk.Toplevel,'grab_set',return_value=None):return cls(*args)

def main():
 app=App();dialogs=[]
 try:
  cfg=load(ROOT/'config/sdwan.json');before=copy.deepcopy(cfg);link=dict(interface='sstp-existing',vpn_type='sstp',vpn_endpoint='exit.example.test',running=True);inv={'vpn_interfaces':[link],'address_list_names':['Users','Targets']};d=dialog(VPNDialog,app,cfg,inv);dialogs.append(d);assert not d.nat.get() and not d.forward.get();d.vars['underlays'].set('wan2, wan1');d.accept();result=validate(d.result);assert cfg==before and result['policies']==before['policies'] and 'vpn_egress' not in result;print('PASS adding an optional VPN WAN creates no implicit policy or separate feature switch')
  app.render_config(result);assert app.collect()['wans'][-1]['kind']=='vpn';editor=dialog(RecordDialog,app,'VPN WAN',WAN_FIELDS,result['wans'][-1],True);dialogs.append(editor);editor.vars['admin_state'].set('drain');editor.vars['masquerade'].set(True);editor.accept();assert editor.result['underlays']==['wan2','wan1'] and editor.result['vpn_type']=='sstp' and editor.result['masquerade'];print('PASS ordinary WAN editor retains VPN transport metadata and exposes common NAT/drain settings')
  for src,dst in [('Address List MikroTik','Address List MikroTik'),('IP / подсеть','Address List MikroTik'),('Address List MikroTik','IP / подсеть')]:
   p=dialog(PolicyDialog,app,result,inv);dialogs.append(p);p.modes['source'].set(src);p.values['source'].set('Users' if src=='Address List MikroTik' else '192.168.50.101');p.modes['destination'].set(dst);p.values['destination'].set('Targets' if dst=='Address List MikroTik' else '203.0.113.7');p.wans.set_order(['wan1','vpn1','wan3']);p.wans.selected.selection_set(1);p.wans.move(-1);assert p.wans.order==['vpn1','wan1','wan3'];p.accept();assert p.result;presult=p.result['policies'][-1];assert presult['wans']==['vpn1','wan1','wan3'];assert ('source_list' in presult)==(src=='Address List MikroTik') and ('destination_list' in presult)==(dst=='Address List MikroTik');app.render_config(p.result);assert app.collect()['policies']==ordered(p.result);print('PASS common policy wizard combines '+src+' source with '+dst+' destination and ordered physical/VPN WANs')
 finally:
  for d in dialogs:
   try:d.destroy()
   except tk.TclError:pass
  app.destroy()
if __name__=='__main__':main()
