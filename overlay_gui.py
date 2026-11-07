"""Per-router branch overlay wizard. Keys are generated locally on RouterOS."""
import copy,json,queue,threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from sdwan.overlay import health,HEALTH_DEFAULTS
from sdwan.overlay_project import configure,exchange,decode_exchange,with_local_keys

TUNNEL_FIELDS=[('name','Имя пути','text'),('wan','Физический WAN','text'),('listen_port','Локальный UDP-порт','int'),('address','Адрес туннеля /30 или /31','text'),('peer_address','Внутренний IP peer','text'),('local_public_key','Локальный публичный ключ','text'),('peer_public_key','Публичный ключ peer','text'),('peer_prefixes','Сети за peer, через запятую','csv'),('cost','Стоимость OSPF','int'),('endpoint','Публичный IP / DNS головного узла (site)','text'),('endpoint_port','UDP-порт головного узла (site)','int'),('keepalive_seconds','Keepalive (site), с','int')]

class OverlayDialog(tk.Toplevel):
 def __init__(self,parent,config,table_class,record_class):
  super().__init__(parent);self.app=parent;self.cfg=copy.deepcopy(config);self.result=None;self.record_class=record_class;self.messages=queue.Queue();self.preparing=False;self.public=None
  self.title('Филиалы: WireGuard + OSPF');self.transient(parent);self.geometry('1170x820');self.minsize(900,700);self.protocol('WM_DELETE_WINDOW',self.cancel)
  o=config.get('overlay',{});self.enabled=tk.BooleanVar(value=o.get('enabled',False));self.mss=tk.BooleanVar(value=o.get('mss_clamp',False));self.vars={};self.health=health(config)
  body=ttk.Frame(self,padding=12);body.pack(fill='both',expand=True);ttk.Checkbutton(body,text='Включить опциональный филиальный overlay на этом роутере',variable=self.enabled).pack(anchor='w')
  form=ttk.Frame(body);form.pack(fill='x',pady=6)
  for row,(key,label,default) in enumerate([('role','Роль: site — филиал за CGNAT, hub — доступный головной узел','site'),('router_id','Уникальный OSPF Router ID',''),('local_prefixes','Публикуемые локальные сети, через запятую',''),('remote_prefixes','Все удалённые сети, через запятую',''),('mtu','MTU туннелей (1280–1420)',1380)]):
   value=o.get(key,default);value=', '.join(value) if isinstance(value,list) else str(value);var=tk.StringVar(value=value);self.vars[key]=var;ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',pady=4)
   widget=ttk.Combobox(form,textvariable=var,values=['site','hub'],state='readonly',width=16) if key=='role' else ttk.Entry(form,textvariable=var,width=65);widget.grid(row=row,column=1,sticky='ew',padx=8,pady=4)
  form.columnconfigure(1,weight=1);ttk.Checkbutton(body,text='Ограничить TCP MSS только на управляемых туннелях',variable=self.mss).pack(anchor='w')
  self.table=table_class(body,TUNNEL_FIELDS,o.get('tunnels',[]));self.table.pack(fill='both',expand=True,pady=8);self.table.choices=lambda:{'wan':[w['name'] for w in self.cfg['wans'] if w.get('kind')!='vpn']}
  bar=ttk.Frame(body);bar.pack(fill='x');self.prepare_button=ttk.Button(bar,text='Подготовить локальные ключи на MikroTik',command=self.prepare);self.prepare_button.pack(side='left',padx=3)
  ttk.Button(bar,text='Экспорт публичных ключей',command=self.export_keys).pack(side='left',padx=3);ttk.Button(bar,text='Ключ peer из файла',command=self.import_peer).pack(side='left',padx=3);ttk.Button(bar,text='SLA туннелей',command=self.edit_health).pack(side='left',padx=3)
  self.info=tk.StringVar(value='Добавьте пути, укажите имена/порты и подготовьте ключи. Существующие ключи сохраняются.');ttk.Label(body,textvariable=self.info,wraplength=1110).pack(fill='x',pady=6)
  ttk.Label(body,text='За CGNAT оба филиала исходящими туннелями подключаются к доступному публичному hub. На hub каждому пути филиала соответствует отдельный интерфейс. Согласуйте адреса, порты и публичные ключи на обоих узлах; прямой проход через два CGNAT не предполагается.\n\nПодготовка создаёт только выключенные WireGuard-интерфейсы без адресов, peer, маршрутов и firewall. Закрытый ключ остаётся на MikroTik. Выберите строку для импорта публичного ключа peer. На hub поля endpoint/keepalive не используются. Конфигурация каждого узла сохраняется отдельно; сетевые изменения применяются через общий план и защищённую установку.',wraplength=1110).pack(fill='x',pady=8)
  buttons=ttk.Frame(body);buttons.pack(fill='x');ttk.Button(buttons,text='Отмена',command=self.cancel).pack(side='right',padx=4);ttk.Button(buttons,text='Создать конфигурацию',command=self.accept).pack(side='right',padx=4)
  self.poll_id=self.after(100,self.poll);self.grab_set();self.wait_window()
 def destroy(self):
  if getattr(self,'poll_id',None):
   try:self.after_cancel(self.poll_id)
   except tk.TclError:pass
  super().destroy()
 def cancel(self):
  if self.preparing:self.info.set('Дождитесь завершения подготовки ключей.');return
  self.destroy()
 def draft(self):
  if not self.enabled.get():return {'enabled':False}
  csv=lambda key:[s.strip() for s in self.vars[key].get().split(',') if s.strip()];role=self.vars['role'].get();tunnels=copy.deepcopy(self.table.rows)
  for t in tunnels:
   if role=='hub':
    for f in ('endpoint','endpoint_port','keepalive_seconds'):t.pop(f,None)
  return dict(enabled=True,role=role,router_id=self.vars['router_id'].get().strip(),local_prefixes=csv('local_prefixes'),remote_prefixes=csv('remote_prefixes'),mtu=int(self.vars['mtu'].get()),mss_clamp=self.mss.get(),health=copy.deepcopy(self.health),tunnels=tunnels)
 def accept(self):
  if self.preparing:return
  try:self.result=configure(self.cfg,self.draft());self.destroy()
  except (ValueError,KeyError) as e:messagebox.showerror('Филиальный overlay',str(e),parent=self)
 def edit_health(self):
  editor=self.record_class(self,'SLA внутренних туннелей',[(k,k,'int') for k in HEALTH_DEFAULTS],self.health)
  if editor.result:self.health=editor.result
 def prepare(self):
  if self.preparing:return
  try:
   if not self.app.connection_matches() or not self.app.inventory:raise ValueError('Сначала подключитесь к нужному MikroTik.')
   mtu=int(self.vars['mtu'].get());tunnels=copy.deepcopy(self.table.rows);requests=[{'name':t['name'],'listen_port':t['listen_port'],'mtu':mtu} for t in tunnels];values=self.app.connection_values();expected=self.app.inventory['identity']['name']
   self.preparing=True;self.app.busy=True;self.app.refresh_buttons();self.prepare_button.configure(state='disabled');self.info.set('Подготовка выключенных интерфейсов; закрытые ключи не запрашиваются…')
   def work():
    router=None
    try:
     from sdwan.overlay_runtime import prepare_keys
     router=self.app.make_router(values);identities=prepare_keys(router,requests,expected);self.messages.put(('ok',(values,exchange(expected,identities))))
    except Exception as e:self.messages.put(('error',str(e)))
    finally:
     if router:router.close()
   threading.Thread(target=work,daemon=False).start()
  except (ValueError,KeyError) as e:messagebox.showerror('Подготовка ключей',str(e),parent=self)
 def poll(self):
  try:
   kind,payload=self.messages.get_nowait();self.preparing=False;self.app.busy=False;self.app.refresh_buttons();self.prepare_button.configure(state='normal')
   if kind=='error':self.info.set('Подготовка не завершена: '+payload)
   else:
    values,public=payload
    if values!=self.app.connection_values() or not self.app.connection_matches():self.info.set('Подключение изменилось. Перечитайте устройство.');self.public=None
    else:
     try:
      # The table can still be edited while the API worker runs. Never replace
      # its newer contents with an older snapshot or attach stale port identities.
      self.table.rows=with_local_keys(self.table.rows,public['identities'],int(self.vars['mtu'].get()));self.table.refresh();self.public=public;self.info.set('Публичные ключи получены. Обменяйте файлы с другим узлом и укажите ключи peer; сетевые изменения ещё не применены.')
     except (ValueError,KeyError) as e:self.public=None;self.info.set(str(e))
  except queue.Empty:pass
  self.poll_id=self.after(100,self.poll)
 def export_keys(self):
  try:
   if not self.public:raise ValueError('Сначала подготовьте или перечитайте локальные ключи кнопкой подготовки.')
   with_local_keys(self.table.rows,self.public['identities'],int(self.vars['mtu'].get()))
   path=filedialog.asksaveasfilename(parent=self,defaultextension='.json',initialfile='overlay-public-keys.json',filetypes=[('JSON','*.json')])
   if path:Path(path).write_text(json.dumps(self.public,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
  except (ValueError,KeyError,OSError) as e:messagebox.showerror('Публичные ключи',str(e),parent=self)
 def import_peer(self):
  try:
   selected=self.table.tree.selection()
   if len(selected)!=1:raise ValueError('Выберите один путь, которому принадлежит ключ удалённого peer.')
   path=filedialog.askopenfilename(parent=self,filetypes=[('Публичные ключи JSON','*.json')])
   if not path:return
   with Path(path).open(encoding='utf-8-sig') as f:public=decode_exchange(f.read(32769))
   picker=tk.Toplevel(self);picker.title('Выберите peer на '+public['router']);picker.transient(self);choice=tk.StringVar(value=public['identities'][0]['name']);ttk.Combobox(picker,textvariable=choice,values=[r['name'] for r in public['identities']],state='readonly',width=35).pack(padx=20,pady=12);chosen=[]
   def accept():chosen.append(next(r['public_key'] for r in public['identities'] if r['name']==choice.get()));picker.destroy()
   ttk.Button(picker,text='Использовать этот публичный ключ',command=accept).pack(padx=20,pady=12);picker.grab_set();self.wait_window(picker);self.grab_set()
   if chosen:self.table.rows[int(selected[0])]['peer_public_key']=chosen[0];self.table.refresh()
  except (ValueError,KeyError,OSError) as e:messagebox.showerror('Ключ peer',str(e),parent=self)
