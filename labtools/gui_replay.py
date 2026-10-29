"""Drive real Tk widgets on Xvfb with synthetic API replies, no router connection."""
import argparse,copy,hashlib,importlib.util,json,socket,sys,time,tkinter as tk
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.source=a.source.resolve();a.output.mkdir(parents=True,exist_ok=False)
sys.path.insert(0,str(a.source))
import configurator as gui
from sdwan.discovery import FIELDS
from sdwan.platform_support import CAPABILITY_FIELDS
from sdwan.vpn_egress import MENUS
from vpn_gui import VPNDialog
from policy_gui import PolicyDialog

raw=json.loads((Path(__file__).parent/'fixtures/mixed-router.json').read_text());original=copy.deepcopy(raw)
allowed=set(FIELDS)|set(CAPABILITY_FIELDS)|set(MENUS.values())|{'system/identity','system/resource','interface/wireguard','interface/wireguard/peers','ip/firewall/address-list'}
report={'pass':False,'scope':'real Tk widgets/event loop with replay API; not Windows rendering or real router installation','checks':[],'messages':[],'network_calls':0}

class Replay:
 def __init__(self,data,denied=()):self.data=copy.deepcopy(data);self.denied=set(denied);self.calls=[]
 def close(self):pass
 def call(self,path,data=None,method=None):
  if path in ('system/identity','system/resource'):return copy.deepcopy(self.data[path][0])
  assert path.endswith('/print') and path[:-6] in allowed,('unexpected operation',path)
  menu=path[:-6];attrs=data or {};self.calls.append([path,attrs]);fields=set(attrs.get('.proplist','').split(','))
  assert not fields&{'password','private-key','preshared-key','pin'}
  if menu in self.denied:raise RuntimeError('fixture permission denied')
  rows=self.data.get(menu,[])
  if 'count-only' in attrs:return {'ret':str(len(rows))}
  return [{k:v for k,v in row.items() if k in fields} for row in rows]

def note(name):report['checks'].append({'name':name,'pass':True});print('PASS '+name,flush=True)
def buttons(root):
 for w in root.winfo_children():
  if isinstance(w,ttk.Button):yield w
  yield from buttons(w)
def click(root,text):
 found=[w for w in buttons(root) if w.cget('text')==text];assert len(found)==1,(text,len(found));assert str(found[0].cget('state'))!='disabled',text;found[0].invoke()
def wait(app,fn,seconds=8):
 deadline=time.monotonic()+seconds
 while time.monotonic()<deadline:
  app.update()
  if fn():return
  time.sleep(.01)
 raise AssertionError('GUI wait expired')
def destroy(app):
 for name in app.tk.call('after','info'):
  try:app.tk.call('after','cancel',name)
  except tk.TclError:pass
 app.destroy()
def modal(app,kind,action,trigger):
 errors=[]
 def find(root):
  for w in root.winfo_children():
   if isinstance(w,kind):return w
   found=find(w)
   if found:return found
 def fill():
  dialog=find(app)
  if dialog is None:app.after(20,fill);return
  try:action(dialog)
  except BaseException as e:errors.append(str(e));dialog.destroy()
 def timeout():
  errors.append('modal timeout');dialog=find(app)
  if dialog:dialog.destroy()
 guard=app.after(8000,timeout);app.after(20,fill)
 try:trigger()
 finally:app.after_cancel(guard)
 assert not errors,errors

def connect(app,replay):
 app.make_router=lambda values:replay
 app.connect_button.invoke();wait(app,lambda:not app.busy)
 assert app.connection_matches() and app.inventory is not None
 assert app.setup.tree.winfo_ismapped() and app.setup.tree.get_children()
def select(app,name,priority):
 w=app.setup;key=next(k for k,c in w.selection.items() if c['interface']==name)
 w.tree.selection_set(key);w.tree.event_generate('<<TreeviewSelect>>');app.update()
 click(w.iface_page,'Внешний WAN / убрать');w.priority_box.delete(0,'end');w.priority_box.insert(0,str(priority));click(w.iface_page,'Обновить строку');app.update()
def targets(app):
 w=app.setup;click(w.iface_page,'Далее: контроль каналов →');assert app.steps.select()==str(w.target_page)
 w.icmp.set('203.0.113.10')
 for i in range(3):
  w.probes.tree.selection_set(str(i))
  def fill(d,i=i):d.widgets['host'].insert(0,'203.0.113.'+str(10+i));click(d,'Сохранить')
  modal(app,gui.RecordDialog,fill,lambda:click(w.probes,'Изменить'))
 click(w.target_page,'Создать конфигурацию из выбранных интерфейсов →');app.update();assert app.data is not None

def blocked_network(*args,**kwargs):report['network_calls']+=1;raise AssertionError('Live network is forbidden in GUI replay')
def message(kind):
 def handler(title,body,*args,**kwargs):report['messages'].append({'kind':kind,'title':str(title),'text':str(body)});return 'ok'
 return handler

try:
 with patch.object(socket,'create_connection',blocked_network),patch.object(socket.socket,'connect',blocked_network),patch.object(gui.messagebox,'showerror',message('error')),patch.object(gui.messagebox,'showwarning',message('warning')),patch.object(gui.messagebox,'showinfo',message('info')):
  app=gui.App();callback_errors=[];app.report_callback_exception=lambda *e:callback_errors.append(str(e[1]));app.update()
  try:
   replay=Replay(raw);connect(app,replay);note('connect button drives async discovery and fills visible interface tree')
   select(app,'wan-static',1);select(app,'lte-test',2)
   assert str(app.setup.apn_box.cget('state'))=='readonly' and app.setup.apn_profile.get()=='lab-apn'
   assert str(app.setup.address_box.cget('state'))=='readonly';note('LTE selection shows APN and read-only runtime address')
   targets(app);cfg=app.collect();assert [w['kind'] for w in cfg['wans']]==['static','lte'];assert 'gateway' not in cfg['wans'][1];note('next/create buttons and modal probe editor generate static plus LTE config')
   app.tabs.select(app.wans)
   def vpn(d):d.vars['underlays'].set('wan1, wan2');click(d,'Сохранить WAN в проекте')
   modal(app,VPNDialog,vpn,lambda:click(app.wans,'Добавить / настроить VPN WAN'))
   assert app.collect()['wans'][-1]['kind']=='vpn';note('actual VPN dialog adds existing SSTP as ordinary WAN')
   app.tabs.select(app.policies)
   def policy(d):
    d.modes['source'].set('IP / подсеть');d.widgets['source'].insert(0,'10.77.0.9')
    d.modes['destination'].set('Address List MikroTik');d.widgets['destination'].insert(0,'lab-targets')
    d.wans.available.selection_set(2);click(d.wans,'Добавить →');d.wans.selected.selection_set(2);click(d.wans,'Выше');click(d.wans,'Выше');click(d,'Добавить правило')
   modal(app,PolicyDialog,policy,lambda:click(app.policies,'Правило по IP / Address List → WAN'))
   policy=next(p for p in app.collect()['policies'] if p.get('destination_list')=='lab-targets')
   assert policy['source']=='10.77.0.9/32' and policy['wans']==['vpn1','wan1','wan2'];note('policy dialog combines source IP and destination list with VPN-first fallback order')
   dest=a.output/'project.json'
   with patch.object(gui.filedialog,'asksaveasfilename',return_value=str(dest)):click(app,'Сохранить JSON')
   assert dest.exists() and Path(str(dest)+'.migration.json').exists()
   package=a.output/'bundle'
   with patch.object(gui.filedialog,'askdirectory',return_value=str(package)):click(app,'Файлы RouterOS')
   spec=importlib.util.spec_from_file_location('bundle_check',a.source/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
   assert {'sdwan-config.json',*cli.FILES,'MIGRATION-REVIEW.txt','MIGRATION-REVIEW.json'}=={p.name for p in package.iterdir()}
   assert json.loads((package/'sdwan-config.json').read_text())==json.loads(dest.read_text());note('save and export buttons write matching JSON and complete RouterOS package')
   with patch.object(gui.filedialog,'askopenfilename',return_value=str(dest)):click(app,'Открыть JSON')
   assert app.collect()['policies']==json.loads(dest.read_text())['policies'];note('open button restores exported policy conditions and WAN order')
   assert not callback_errors,callback_errors
  finally:destroy(app)
  for case in ('missing-apn','missing-gateway','foreign-mangle'):
   app=gui.App();app.update();start=len(report['messages']);data=copy.deepcopy(raw)
   if case=='foreign-mangle':data['ip/firewall/mangle']=[{'.id':'*99','chain':'prerouting','action':'mark-routing','new-routing-mark':'legacy','comment':'synthetic-old-policy'}]
   try:
    connect(app,Replay(data,['interface/lte/apn'] if case=='missing-apn' else []));select(app,'wan-static',1)
    if case=='missing-apn':
     select(app,'lte-test',2);click(app.setup.iface_page,'Далее: контроль каналов →');assert any('APN' in m['text'] for m in report['messages'][start:]);assert app.steps.select()==str(app.setup.iface_page);note('missing LTE/APN permission shows error and keeps interface selection step')
    elif case=='missing-gateway':
     app.setup.gateway_box.delete(0,'end');click(app.setup.iface_page,'Далее: контроль каналов →');assert any('wan-static' in m['text'] and 'шлюз' in m['text'] for m in report['messages'][start:]);assert app.data is None;note('missing gateway is attributed to selected WAN before generation')
    else:
     select(app,'lte-test',2);targets(app);assert app.migration_report['blocking_rules'] and str(app.action_buttons['apply'].cget('state'))=='disabled'
     package=a.output/'migration-bundle'
     with patch.object(gui.filedialog,'askdirectory',return_value=str(package)):click(app,'Файлы RouterOS')
     review=json.loads((package/'MIGRATION-REVIEW.json').read_text());assert review['blocking_rules'][0]['.id']=='*99';note('foreign mangle allows draft/export with exact conflict report and disabled install button')
   finally:destroy(app)
  app=gui.App();app.update();data=copy.deepcopy(raw)
  data['system/package'].append({'name':'container','version':'7.24.5','disabled':'false'})
  data['system/device-mode'][0]['container']='true'
  data['disk']=[{'slot':slot,'mount-point':mount,'fs':'ext4','free':str(64*1024**2),
                 'mount-filesystem':'true','mounted':mounted,'mount-read-only':readonly}
                for slot,mount,mounted,readonly in [('usb1','data','true','false'),('usb2','readonly','true','true'),('usb3','offline','false','false')]]
  try:
   connect(app,Replay(data));select(app,'wan-static',1);select(app,'lte-test',2);targets(app)
   app.backend.set('Локальный контейнер Rust');app.update()
   storage=next(w for w in app.container_entries if isinstance(w,ttk.Combobox))
   choices=storage.cget('values')
   assert 'data/sdwan-container' in choices and not any(name in choices for name in ['usb1/sdwan-container','readonly/sdwan-container','offline/sdwan-container'])
   note('storage selector offers actual mount point and excludes read-only or unmounted disks')
   app.container_vars['storage'].set('readonly/controller');click(app,'Проверить готовность');wait(app,lambda:not app.busy)
   assert 'container-storage' in app.platform_info.get() and 'только для чтения' in app.log.get('1.0','end')
   note('readiness button explains read-only disk before any installation')
   app.container_vars['storage'].set('data/controller');click(app,'Проверить готовность');wait(app,lambda:not app.busy)
   assert 'Пакеты, функции и ресурсы доступны' in app.platform_info.get()
   note('readiness button accepts verified mounted writable storage')
  finally:destroy(app)
  assert raw==original and report['network_calls']==0
  assert not [m for m in report['messages'] if m['kind']=='error' and not ('APN' in m['text'] or 'шлюз' in m['text'])],report['messages']
  report['pass']=True
except BaseException as error:report['error']=type(error).__name__+': '+str(error);raise
finally:
 report['source_sha256']={str(p.relative_to(a.source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [a.source/name for name in ['configurator.py','vpn_gui.py','policy_gui.py','sdwan/wizard_ui.py','sdwan/platform_support.py','sdwan/provisioning.py','labtools/gui_replay.py']]}
 (a.output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
