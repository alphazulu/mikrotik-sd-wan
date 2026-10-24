"""Discovery-first setup steps; no network calls on Tk's UI thread."""
import copy
import tkinter as tk
from tkinter import ttk,messagebox
from .discovery import generate,validate_wan_choices,WANSelectionError


class SetupWizard:
    def __init__(self,app,notebook,table_class,probe_fields):
        self.app=app;self.notebook=notebook;self.inventory=None;self.selection={};self.current=None;self.loading=False
        self.iface_page=ttk.Frame(notebook,padding=10);notebook.add(self.iface_page,text='1. Выбрать внешние интерфейсы')
        self.target_page=ttk.Frame(notebook,padding=10);notebook.add(self.target_page,text='2. Контроль каналов')
        self.instructions=tk.StringVar(value='Подключитесь к MikroTik. Мастер прочитает его настройки и покажет интерфейсы.')
        ttk.Label(self.iface_page,textvariable=self.instructions,wraplength=1120).pack(anchor='w',pady=(0,8))
        columns=('wan','priority','interface','type','running','addresses','gateways','hint')
        self.tree=ttk.Treeview(self.iface_page,columns=columns,show='headings',height=9,selectmode='browse')
        labels=('Внешний WAN','Приоритет','Интерфейс','Тип','Состояние','IPv4','Шлюзы','Обнаружено')
        widths=(90,65,110,80,75,150,150,270)
        for key,label,width in zip(columns,labels,widths):self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=45)
        self.tree.tag_configure('suggested',foreground='#175c97');self.tree.tag_configure('limited',foreground='#9b5b16')
        scroll=ttk.Scrollbar(self.iface_page,orient='horizontal',command=self.tree.xview);self.tree.configure(xscrollcommand=scroll.set)
        self.tree.pack(fill='both',expand=True);scroll.pack(fill='x')
        self.tree.bind('<<TreeviewSelect>>',self.on_select);self.tree.bind('<Button-1>',self.click_checkbox);self.tree.bind('<Double-1>',lambda e:self.toggle() if self.tree.identify_column(e.x)!='#1' else None);self.tree.bind('<space>',lambda e:self.toggle())
        bar=ttk.Frame(self.iface_page);bar.pack(fill='x',pady=6)
        ttk.Button(bar,text='Внешний WAN / убрать',command=self.toggle).pack(side='left',padx=3)
        ttk.Button(bar,text='Отметить рекомендованные',command=self.suggest).pack(side='left',padx=3)
        ttk.Button(bar,text='Далее: контроль каналов →',command=self.next_step).pack(side='right')
        details=ttk.LabelFrame(self.iface_page,text='Параметры выбранного интерфейса',padding=8);details.pack(fill='x')
        self.iface=tk.StringVar(value='—');self.address=tk.StringVar();self.gateway=tk.StringVar();self.priority=tk.StringVar(value='1');self.apn_profile=tk.StringVar()
        ttk.Label(details,textvariable=self.iface,width=18).grid(row=0,column=0,padx=5)
        ttk.Label(details,text='IPv4 на MikroTik').grid(row=0,column=1);self.address_box=ttk.Combobox(details,textvariable=self.address,width=18);self.address_box.grid(row=0,column=2,padx=5)
        ttk.Label(details,text='Шлюз').grid(row=0,column=3);self.gateway_box=ttk.Combobox(details,textvariable=self.gateway,width=18);self.gateway_box.grid(row=0,column=4,padx=5)
        ttk.Label(details,text='Приоритет').grid(row=0,column=5);self.priority_box=ttk.Spinbox(details,from_=1,to=16,textvariable=self.priority,width=5);self.priority_box.grid(row=0,column=6,padx=5)
        ttk.Button(details,text='Обновить строку',command=self.commit).grid(row=0,column=7,padx=5)
        ttk.Label(details,text='APN профиль LTE').grid(row=1,column=1,sticky='w')
        self.apn_box=ttk.Entry(details,textvariable=self.apn_profile,state='readonly',width=32);self.apn_box.grid(row=1,column=2,columnspan=3,sticky='w',padx=5)
        ttk.Label(details,text='Приоритет 1 — основной. Для static выберите IP и шлюз. Для DHCP/PPPoE/LTE показаны текущие параметры; они обновляются самим MikroTik и не сохраняются как постоянные. PPPoE WAN — логический интерфейс.',wraplength=1100).grid(row=2,columnspan=8,sticky='w',pady=(8,0))
        self.keep=tk.BooleanVar(value=True);self.existing=tk.BooleanVar(value=True)
        self.keep_box=ttk.Checkbutton(self.target_page,text='Сохранить существующие правила клиентов этого MikroTik',variable=self.keep);self.keep_box.pack(anchor='w',pady=4)
        self.existing_box=ttk.Checkbutton(self.target_page,text='Использовать контрольные цели из действующего SD-WAN на этом MikroTik',variable=self.existing);self.existing_box.pack(anchor='w',pady=4)
        self.target_note=tk.StringVar(value='Для нового устройства задайте контрольные цели. Для настроенного SD-WAN они будут прочитаны с MikroTik.')
        ttk.Label(self.target_page,textvariable=self.target_note,wraplength=1100).pack(anchor='w',pady=8)
        f=ttk.Frame(self.target_page);f.pack(fill='x',pady=4);ttk.Label(f,text='Общая ICMP-цель (IPv4 за провайдером)').pack(side='left');self.icmp=tk.StringVar();ttk.Entry(f,textvariable=self.icmp,width=24).pack(side='left',padx=8)
        self.probes=table_class(self.target_page,probe_fields,[{'name':n,'type':'tcp-conn','host':'','port':443} for n in ('a','b','c')]);self.probes.pack(fill='both',expand=True,pady=5)
        ttk.Label(self.target_page,text='Эти цели применятся ко всем выбранным WAN, если снята галочка использования действующих целей.\nДля реального устройства укажите согласованные независимые ресурсы; лабораторные адреса не подставляются в новый роутер.',wraplength=1100).pack(anchor='w',pady=5)
        ttk.Button(self.target_page,text='Создать конфигурацию из выбранных интерфейсов →',command=self.create).pack(anchor='e',pady=8)

    def load_inventory(self,inventory):
        self.inventory=inventory;self.current=None;self.selection={};self.tree.delete(*self.tree.get_children())
        for i,c in enumerate(inventory['candidates']):
            self.selection[str(i)]=dict(copy.deepcopy(c),enabled=False)
            self.refresh(str(i))
        active=inventory.get('active_config')
        self.keep.set(bool(active));self.existing.set(bool(active))
        self.keep_box.configure(state='normal' if active else 'disabled');self.existing_box.configure(state='normal' if active else 'disabled')
        self.instructions.set(f"{inventory['identity']['name']} · RouterOS {inventory['resource']['version']} · {len(self.selection)} интерфейсов. Отметьте только внешние WAN. Подсказки не заменяют ваш выбор.")
        self.target_note.set('Действующий SD-WAN найден: цели, SLA и политики можно сохранить.' if active else 'SD-WAN на устройстве не найден. Добавьте контрольные цели и ICMP-адрес; остальные параметры будут получены из выбранных WAN.')
        if active and active.get('wans'):
            first=active['wans'][0];self.icmp.set(first['icmp_target']);self.probes.rows=copy.deepcopy(first['probes']);self.probes.refresh()
        else:
            self.icmp.set('');self.probes.rows=[{'name':n,'type':'tcp-conn','host':'','port':443} for n in ('a','b','c')];self.probes.refresh()
        self.iface.set('—');self.address.set('');self.gateway.set('');self.apn_profile.set('')

    def refresh(self,key):
        c=self.selection[key]
        values=('☑' if c['enabled'] else '☐',c['priority'] if c['priority']!=255 else '',c['interface'],c.get('kind','static')+' / '+c['type'],'up' if c['running'] else 'down',', '.join(c['addresses']) or '—',', '.join(c['gateways']) or '—',c['reason'])
        tags=('limited',) if c['bridge'] or c.get('kind_error') or (c['dynamic'] and c.get('kind','static')=='static') else (('suggested',) if c['suggested'] else ())
        if self.tree.exists(key):self.tree.item(key,values=values,tags=tags)
        else:self.tree.insert('',tk.END,iid=key,values=values,tags=tags)

    def commit(self):
        if self.current is None or self.loading:return
        c=self.selection[self.current]
        if c.get('kind','static')=='static':c['address']=self.address.get().strip();c['gateway']=self.gateway.get().strip()
        try:c['priority']=int(self.priority.get())
        except ValueError:c['priority']=0
        self.refresh(self.current)

    def on_select(self,event=None):
        selected=self.tree.selection()
        if not selected:return
        key=selected[0]
        if key==self.current:return
        self.commit();self.current=key;c=self.selection[key];self.loading=True
        self.apn_profile.set(c.get('apn_profile',''))
        self.iface.set(c['interface']);self.address.set(c['address']);self.gateway.set(c['gateway']);self.priority.set(str(c['priority'] if c['priority']!=255 else 1))
        dynamic=c.get('kind','static')!='static'
        self.address_box.configure(values=[] if dynamic else c['addresses'],state='readonly' if dynamic else 'normal')
        self.gateway_box.configure(values=[] if dynamic else c['gateways'],state='readonly' if dynamic else 'normal');self.loading=False

    def click_checkbox(self,event):
        row=self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x)=='#1':
            self.tree.selection_set(row);self.on_select();self.toggle();return 'break'

    def toggle(self):
        selected=self.tree.selection()
        if not selected:return
        self.commit();key=selected[0];c=self.selection[key];c['enabled']=not c['enabled']
        if c['enabled']:
            used={x['priority'] for k,x in self.selection.items() if k!=key and x['enabled']}
            if c['priority']==255 or c['priority'] in used or c['priority']<1:c['priority']=max(used,default=0)+1
            self.priority.set(str(c['priority']))
        self.refresh(key)

    def suggest(self):
        self.commit();eligible=[(k,c) for k,c in self.selection.items() if c['suggested'] and not c['disabled'] and not c['bridge'] and not c.get('kind_error') and (c.get('kind','static') in ('dhcp','pppoe','lte') or (not c['dynamic'] and c['addresses']))]
        for c in self.selection.values():c['enabled']=False
        for priority,(key,c) in enumerate(sorted(eligible,key=lambda p:(p[1]['priority'],p[1]['interface'])),1):c['enabled']=True;c['priority']=priority
        for key in self.selection:self.refresh(key)
        if self.current is not None:self.priority.set(str(self.selection[self.current]['priority']))

    def checked_choices(self):
        if not self.inventory or not self.app.connection_matches():raise ValueError('Сначала подключитесь и получите настройки MikroTik.')
        self.commit()
        choices=[{k:c[k] for k in ('interface','address','gateway','priority')} for c in self.selection.values() if c['enabled']]
        return validate_wan_choices(self.inventory,choices)

    def show_selection_error(self,error):
        self.notebook.select(self.iface_page)
        key=next((key for key,c in self.selection.items() if c['interface']==error.interface),None)
        if key is not None:
            self.tree.selection_set(key);self.tree.see(key);self.on_select()
        messagebox.showerror('Параметры внешнего интерфейса',str(error),parent=self.app)
        widget={'address':self.address_box,'gateway':self.gateway_box,'priority':self.priority_box}.get(error.field,self.tree)
        widget.focus_set()

    def next_step(self):
        try:
            self.checked_choices();self.notebook.select(self.target_page)
        except WANSelectionError as e:self.show_selection_error(e)
        except ValueError as e:messagebox.showerror('Выбор WAN',str(e),parent=self.app)

    def create(self):
        try:
            choices=self.checked_choices()
            config=generate(self.inventory,choices,keep_policies=self.keep.get(),probes=None if self.existing.get() else self.probes.rows,icmp_target=None if self.existing.get() else self.icmp.get().strip())
            self.app.accept_generated(config,self.inventory)
        except WANSelectionError as e:self.show_selection_error(e)
        except (ValueError,KeyError,TypeError) as e:messagebox.showerror('Создание конфигурации',str(e),parent=self.app)
