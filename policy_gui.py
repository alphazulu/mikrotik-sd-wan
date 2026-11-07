"""Common IP/Address List -> ordered WAN policy wizard. No router mutations."""
import tkinter as tk
from tkinter import ttk,messagebox
from sdwan.policy_editor import create

MODES={'Любой адрес':'any','IP / подсеть':'ip','Address List MikroTik':'list'}

class WANOrder(ttk.Frame):
 def __init__(self,parent,wans,initial=()):
  super().__init__(parent);self.names=[w['name'] for w in wans];self.order=[]
  ttk.Label(self,text='Доступные WAN').grid(row=0,column=0);ttk.Label(self,text='Приоритет: сверху вниз').grid(row=0,column=2)
  self.available=tk.Listbox(self,height=6,width=35,selectmode='extended',exportselection=False);self.available.grid(row=1,column=0,sticky='nsew')
  for w in wans:self.available.insert('end',w['name']+' — '+w.get('vpn_type',w.get('kind','static'))+' / '+w['interface'])
  buttons=ttk.Frame(self);buttons.grid(row=1,column=1,padx=8)
  for label,fn in [('Добавить →',self.add),('← Убрать',self.remove),('Выше',lambda:self.move(-1)),('Ниже',lambda:self.move(1))]:ttk.Button(buttons,text=label,command=fn).pack(fill='x',pady=3)
  self.selected=tk.Listbox(self,height=6,width=25,exportselection=False);self.selected.grid(row=1,column=2,sticky='nsew');self.columnconfigure(0,weight=1);self.columnconfigure(2,weight=1);self.set_order(initial)
 def set_order(self,order):
  if len(set(order))!=len(order) or not set(order)<=set(self.names):raise ValueError('Порядок WAN содержит неизвестный или повторный канал')
  self.order=list(order);self.selected.delete(0,'end')
  for name in self.order:self.selected.insert('end',name)
 def add(self):self.set_order(self.order+[self.names[i] for i in self.available.curselection() if self.names[i] not in self.order])
 def remove(self):self.set_order([n for i,n in enumerate(self.order) if i not in self.selected.curselection()])
 def move(self,offset):
  selected=self.selected.curselection()
  if not selected:return
  i=selected[0];j=i+offset
  if not 0<=j<len(self.order):return
  new=list(self.order);new[i],new[j]=new[j],new[i];self.set_order(new);self.selected.selection_set(j)

class PolicyDialog(tk.Toplevel):
 def __init__(self,parent,config,inventory):
  super().__init__(parent);self.title('Правило: IP / Address List → WAN');self.transient(parent);self.result=None;self.cfg=config;self.vars={};self.modes={};self.values={};self.widgets={}
  body=ttk.Frame(self,padding=16);body.pack(fill='both',expand=True)
  names={p['name'] for p in config['policies']};n=1
  while 'policy'+str(n) in names:n+=1
  ranks={p['priority'] for p in config['policies'] if 'priority' in p};priority=10
  while priority in ranks:priority+=10
  profile=next(p['profile'] for p in config['policies'] if not p['source'])
  for row,(key,label,value) in enumerate([('name','Имя правила','policy'+str(n)),('priority','Приоритет правила (меньше = раньше)',str(priority)),('profile','SLA-профиль',profile)]):
   self.vars[key]=tk.StringVar(value=value);ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',pady=5)
   widget=ttk.Combobox(body,textvariable=self.vars[key],values=list(config['sla_profiles']),state='readonly') if key=='profile' else ttk.Entry(body,textvariable=self.vars[key],width=42);widget.grid(row=row,column=1,columnspan=2,sticky='ew',padx=8,pady=5)
  for row,(side,label) in enumerate([('source','Источник'),('destination','Назначение')],3):
   self.modes[side]=tk.StringVar(value='Любой адрес');self.values[side]=tk.StringVar();ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',pady=5);mode=ttk.Combobox(body,textvariable=self.modes[side],values=list(MODES),state='readonly',width=23);mode.grid(row=row,column=1,padx=8)
   value=ttk.Combobox(body,textvariable=self.values[side],values=inventory.get('address_list_names',[]),width=32);value.grid(row=row,column=2,sticky='ew');self.widgets[side]=value;self.modes[side].trace_add('write',lambda *args,s=side:self.changed(s));self.changed(side)
  default=next(p['wans'] for p in config['policies'] if not p['source']);self.wans=WANOrder(body,config['wans'],default);self.wans.grid(row=5,columnspan=3,sticky='nsew',pady=14)
  ttk.Label(body,text='Источник и назначение соединяются условием И. Одиночный IP допустим без /32. Address List используется непосредственно на MikroTik, включая DNS и временные записи. Пустой список не совпадает ни с одним адресом.\n\nПервый WAN с подходящим SLA имеет приоритет; следующие — резерв. Физические и VPN WAN используют один механизм переключения и возврата. Strict, порты и VLAN доступны в общем редакторе правила.',wraplength=720).grid(row=6,columnspan=3,sticky='w',pady=8)
  bar=ttk.Frame(body);bar.grid(row=7,columnspan=3,sticky='e');ttk.Button(bar,text='Отмена',command=self.destroy).pack(side='left',padx=5);ttk.Button(bar,text='Добавить правило',command=self.accept).pack(side='left');self.grab_set();self.wait_window()
 def changed(self,side):self.widgets[side].configure(state='disabled' if MODES[self.modes[side].get()]=='any' else 'normal')
 def accept(self):
  try:self.result=create(self.cfg,name=self.vars['name'].get().strip(),priority=int(self.vars['priority'].get()),profile=self.vars['profile'].get(),source_mode=MODES[self.modes['source'].get()],source_value=self.values['source'].get().strip(),destination_mode=MODES[self.modes['destination'].get()],destination_value=self.values['destination'].get().strip(),wans=self.wans.order);self.destroy()
  except (ValueError,KeyError) as e:messagebox.showerror('Правило WAN',str(e),parent=self)
