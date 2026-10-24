#!/usr/bin/env python3
"""Desktop configuration editor. Routing decisions run only on the MikroTik."""
import copy
import contextlib
import io
import importlib.util
import re
from datetime import datetime, timezone
import json
import ipaddress
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from sdwan.config import validate
from sdwan.router import Router
from sdwan.discovery import discover
from sdwan.wizard_ui import SetupWizard
from sdwan.diagnostics_ui import DiagnosticsPanel
from sdwan.policies import ordered,conflicts
from sdwan.container_config import settings as container_settings

BACKENDS={'Скрипт RouterOS':'routeros','Локальный контейнер Rust':'container'}

ROOT=Path(__file__).resolve().parent
PROBE_FIELDS=[('name','Имя','text'),('type','Тип',['http-get','https-get','tcp-conn','dns']),('host','IP / DNS-имя','text'),('port','Порт (кроме DNS)','int'),('dns_server','DNS-сервер (для DNS)','text')]
WAN_FIELDS=[('name','Имя WAN','text'),('interface','Интерфейс RouterOS','text'),('kind','Подключение',['static','dhcp','pppoe','lte']),('apn_profile','APN профиль (LTE)','text'),('address','IP роутера (static)','text'),('gateway','Шлюз (static)','text'),('probe_table','Таблица проб sdwan-…','text'),('icmp_target','ICMP-цель за шлюзом','text')]
POLICY_FIELDS=[('name','Имя политики','text'),('source','Источник (0.0.0.0/0 = все; пусто = общая)','text'),('table','Таблица маршрутизации','text'),('profile','SLA-профиль','text'),('mode','Режим',['prefer','strict']),('wans','WAN по порядку, через запятую','csv'),('allow_degraded','Разрешить degraded, если нет healthy','bool')]
GROUP_FIELDS=[('name','Имя группы','text'),('members','IP/подсети через запятую','csv')]
POLICY_FIELDS += [('priority','Приоритет (меньше = раньше)','int'),('source_group','Группа источников','text'),('destination','Подсеть назначения','text'),('destination_group','Группа назначений','text'),('in_interface','Входной интерфейс / VLAN','text'),('protocol','Протокол',['any','tcp','udp','icmp']),('src_ports','Порты источника / диапазоны','text'),('dst_ports','Порты назначения / диапазоны','text')]
SLA_FIELDS=[('name','Имя профиля','text'),('rtt_ms','Средний RTT, мс','float'),('jitter_ms','Jitter max-min, мс','float'),('loss_percent','Потери, %','float')]
HEALTH_LABELS={'interval_seconds':'Интервал проб, с','timeout_ms':'Timeout пробы, мс','packet_count':'ICMP пакетов в окне','packet_interval_ms':'Интервал ICMP пакетов, мс','quorum':'Кворум доступных целей','fail_windows':'Плохих окон для исключения','recover_windows':'Хороших окон для возврата','hold_down_seconds':'Задержка возврата после плохого окна, с','stale_seconds':'Устаревание телеметрии, с'}


class RecordDialog(tk.Toplevel):
    def __init__(self,parent,title,fields,value=None,wan=False):
        super().__init__(parent);self.title(title);self.transient(parent);self.result=None;self.fields=fields;self.vars={};self.widgets={};self.wan=wan
        value=copy.deepcopy(value or {})
        if wan:value.setdefault('kind','static')
        self.body=ttk.Frame(self,padding=12);self.body.pack(fill='both',expand=True)
        policy=any(key=='source_group' for key,_,_ in fields)
        if policy:
            pages=ttk.Notebook(self.body);pages.grid(row=0,columnspan=2,sticky='nsew')
            basic=ttk.Frame(pages,padding=8);selectors=ttk.Frame(pages,padding=8);pages.add(basic,text='Маршрут и приоритет');pages.add(selectors,text='Группа и приложение')
            counts={True:0,False:0}
        for row,(key,label,kind) in enumerate(fields):
            container=self.body
            if policy:
                extra=key in ('source_group','destination','destination_group','in_interface','protocol','src_ports','dst_ports')
                container=selectors if extra else basic;row=counts[extra];counts[extra]+=1
            ttk.Label(container,text=label).grid(row=row,column=0,sticky='w',padx=4,pady=5)
            v=value.get(key,False if kind=='bool' else 'any' if key=='protocol' else '')
            if kind=='csv':v=', '.join(v) if isinstance(v,list) else v
            var=tk.BooleanVar(value=v) if kind=='bool' else tk.StringVar(value=str(v))
            self.vars[key]=var
            if isinstance(kind,list):widget=ttk.Combobox(container,textvariable=var,values=kind,state='readonly',width=35)
            elif kind=='bool':widget=ttk.Checkbutton(container,variable=var)
            else:widget=ttk.Entry(container,textvariable=var,width=42)
            widget.grid(row=row,column=1,sticky='ew',padx=4,pady=5)
            self.widgets[key]=widget
        if policy:ttk.Label(self.body,text='Все условия внутри правила соединяются И. Группы содержат IP/подсети. Порты: 80,443,10000-20000.\nПри пересечении правил задайте каждому явный приоритет. Пустой источник оставьте только общей политике.',wraplength=650).grid(row=1,columnspan=2,sticky='w',pady=8)
        self.probes=copy.deepcopy(value.get('probes',[]))
        if wan:
            ttk.Label(self.body,text='DHCP/PPPoE/LTE: IP и шлюз определяются на MikroTik. Для LTE укажите имя APN профиля, назначенного этому интерфейсу.\nВыберите уже настроенный клиент на MikroTik; для PPPoE укажите логический интерфейс.',wraplength=580).grid(row=len(fields),columnspan=2,sticky='w',pady=5)
            self.vars['kind'].trace_add('write',self.addressing_changed);self.addressing_changed()
            f=ttk.LabelFrame(self.body,text='Контрольные цели доступности',padding=6);f.grid(row=len(fields)+1,columnspan=2,sticky='ew',pady=8)
            self.probe_table=Table(f,PROBE_FIELDS,self.probes);self.probe_table.pack(fill='both',expand=True)
        buttons=ttk.Frame(self.body);buttons.grid(row=len(fields)+(2 if wan else 1),columnspan=2,sticky='e',pady=10)
        ttk.Button(buttons,text='Отмена',command=self.destroy).pack(side='left',padx=4)
        ttk.Button(buttons,text='Сохранить',command=self.accept).pack(side='left',padx=4)
        self.grab_set();self.wait_window()
    def addressing_changed(self,*args):
        dynamic=self.vars['kind'].get()!='static'
        lte=self.vars['kind'].get()=='lte'
        self.widgets['apn_profile'].configure(state='normal' if lte else 'disabled')
        if not lte:self.vars['apn_profile'].set('')
        for key in ('address','gateway'):
            if dynamic:self.vars[key].set('')
            self.widgets[key].configure(state='disabled' if dynamic else 'normal')
    def accept(self):
        try:
            d={}
            for key,_,kind in self.fields:
                val=self.vars[key].get()
                if kind in ('int','float'):
                    if val=='':continue
                    val=int(val) if kind=='int' else float(val)
                elif kind=='csv':val=[v.strip() for v in val.split(',') if v.strip()]
                elif kind!='bool':val=val.strip()
                d[key]=val
            if self.wan:
                d['probes']=self.probe_table.rows
                if d['kind']!='static':d.pop('address',None);d.pop('gateway',None)
                if d['kind']!='lte':d.pop('apn_profile',None)
            if d.get('type')=='dns':d.pop('port',None)
            elif 'type' in d:d.pop('dns_server',None)
            self.result=d;self.destroy()
        except ValueError as e:messagebox.showerror('Значение',str(e),parent=self)


class Table(ttk.Frame):
    def __init__(self,parent,fields,rows,wan=False):
        super().__init__(parent);self.fields=fields;self.rows=copy.deepcopy(rows);self.wan=wan;self.choices=None;self.is_policy=any(k=='priority' for k,_,_ in fields)
        keys=[x[0] for x in fields]
        self.tree=ttk.Treeview(self,columns=keys,show='headings',height=7)
        for k,label,_ in fields:self.tree.heading(k,text=label);self.tree.column(k,width=140,minwidth=60)
        scroll=ttk.Scrollbar(self,orient='horizontal',command=self.tree.xview);self.tree.configure(xscrollcommand=scroll.set)
        self.tree.pack(fill='both',expand=True);scroll.pack(fill='x')
        bar=ttk.Frame(self);bar.pack(fill='x',pady=5)
        for label,command in [('Добавить',self.add),('Изменить',self.edit),('Удалить',self.delete)]:ttk.Button(bar,text=label,command=command).pack(side='left',padx=4)
        if self.is_policy:
            ttk.Button(bar,text='Выше',command=lambda:self.move(-1)).pack(side='left',padx=4)
            ttk.Button(bar,text='Ниже',command=lambda:self.move(1)).pack(side='left',padx=4)
        self.tree.bind('<Double-1>',lambda e:self.edit());self.refresh()
    def refresh(self):
        if self.is_policy:self.rows=ordered({'policies':self.rows})
        self.tree.delete(*self.tree.get_children())
        for i,row in enumerate(self.rows):self.tree.insert('',tk.END,iid=str(i),values=[', '.join(row.get(k,[])) if isinstance(row.get(k),list) else row.get(k,'') for k,_,_ in self.fields])
    def add(self):
        d=RecordDialog(self,'Добавить',self.dialog_fields(),wan=self.wan)
        if d.result:self.rows.append(d.result);self.refresh()
    def edit(self):
        ids=self.tree.selection()
        if not ids:return
        i=int(ids[0]);d=RecordDialog(self,'Изменить',self.dialog_fields(),self.rows[i],self.wan)
        if d.result:self.rows[i]=d.result;self.refresh()
    def dialog_fields(self):
        choices=self.choices() if self.choices else {}
        return [(key,label,choices.get(key,kind)) for key,label,kind in self.fields]
    def move(self,offset):
        selected=self.tree.selection()
        if not selected:return
        i=int(selected[0]);j=i+offset
        if not 0<=j<len(self.rows) or not self.rows[i].get('source') or not self.rows[j].get('source'):return
        self.rows[i],self.rows[j]=self.rows[j],self.rows[i]
        for index,row in enumerate(r for r in self.rows if r.get('source')):row['priority']=(index+1)*10
        self.refresh();self.tree.selection_set(str(j))
    def delete(self):
        for i in sorted((int(i) for i in self.tree.selection()),reverse=True):self.rows.pop(i)
        self.refresh()


class App(tk.Tk):
    def __init__(self):
        super().__init__();self.title('MikroTik SD-WAN — мастер настройки');self.geometry('1260x920');self.minsize(1020,760)
        self.path=ROOT/'config/discovered.json';self.messages=queue.Queue();self.busy=False;self.data=None;self.inventory=None;self.bound_connection=None
        top=ttk.Frame(self,padding=8);top.pack(fill='x')
        for label,fn in [('Открыть JSON',self.open),('Сохранить JSON',self.save),('Проверить',self.check),('Файлы RouterOS',self.export)]:ttk.Button(top,text=label,command=fn).pack(side='left',padx=3)
        ttk.Label(top,text='Все решения SD-WAN выполняются на MikroTik.').pack(side='right')
        connection=ttk.LabelFrame(self,text='Подключение к API MikroTik',padding=8);connection.pack(fill='x',padx=8)
        self.url=tk.StringVar(value='api://127.0.0.1:18728');self.username=tk.StringVar(value='admin');self.password=tk.StringVar();self.ca=tk.StringVar();self.identity=tk.StringVar()
        ttk.Label(connection,text='Адрес API').grid(row=0,column=0,sticky='w');ttk.Entry(connection,textvariable=self.url,width=48).grid(row=0,column=1,columnspan=3,sticky='ew',padx=6)
        ttk.Label(connection,text='Логин').grid(row=1,column=0,sticky='w');ttk.Entry(connection,textvariable=self.username,width=24).grid(row=1,column=1,sticky='ew',padx=6,pady=5)
        ttk.Label(connection,text='Пароль').grid(row=1,column=2,sticky='w');ttk.Entry(connection,textvariable=self.password,show='●',width=26).grid(row=1,column=3,sticky='ew',padx=6)
        ttk.Label(connection,text='CA для TLS').grid(row=2,column=0,sticky='w');ttk.Entry(connection,textvariable=self.ca,width=48).grid(row=2,column=1,columnspan=3,sticky='ew',padx=6)
        ttk.Button(connection,text='Выбрать CA',command=lambda:self.ca.set(filedialog.askopenfilename() or self.ca.get())).grid(row=2,column=4,padx=4)
        self.connect_button=ttk.Button(connection,text='Подключиться и получить настройки',command=self.connect);self.connect_button.grid(row=0,column=4,padx=4)
        ttk.Button(connection,text='Лаборатория',command=self.load_lab).grid(row=1,column=4,padx=4)
        ttk.Button(connection,text='Учётные данные из файла',command=self.load_credentials).grid(row=1,column=5,padx=4)
        ttk.Label(connection,text='api://адрес:8728 · apis://адрес:8729 (TLS) · https://адрес (REST) · http://localhost:18080 (стенд)').grid(row=3,columnspan=6,sticky='w',pady=(6,0))
        connection.columnconfigure(1,weight=1);connection.columnconfigure(3,weight=1)
        self.connection_info=tk.StringVar(value='Не подключено. Настройки роутера пока не прочитаны.')
        ttk.Label(self,textvariable=self.connection_info,padding=8).pack(fill='x')
        self.steps=ttk.Notebook(self);self.steps.pack(fill='both',expand=True,padx=8)
        self.setup=SetupWizard(self,self.steps,Table,PROBE_FIELDS)
        self.review=ttk.Frame(self.steps,padding=6);self.steps.add(self.review,text='3. Конфигурация и установка')
        self.summary=tk.StringVar(value='После подключения выберите WAN на шаге 1 и создайте конфигурацию на шаге 2.')
        ttk.Label(self.review,textvariable=self.summary,wraplength=1160).pack(fill='x',pady=4)
        operations=ttk.Frame(self.review,padding=4);operations.pack(fill='x');self.op_buttons=[];self.action_buttons={}
        for label,cmd in [('План изменений','plan'),('Подготовить контейнер','container-prepare'),('Установить на MikroTik','apply'),('Состояние','status'),('Журнал решений','events'),('Откат к исходному','rollback')]:
            button=ttk.Button(operations,text=label,command=lambda c=cmd:self.run(c));button.pack(side='left',padx=4);self.op_buttons.append(button);self.action_buttons[cmd]=button
        self.tabs=ttk.Notebook(self.review);self.tabs.pack(fill='both',expand=True)
        self.diagnostics=DiagnosticsPanel(self.steps,self);self.steps.add(self.diagnostics,text='Диагностика')
        self.log=tk.Text(self,height=8,font=('Consolas',10),wrap='word');self.log.pack(fill='both',padx=8,pady=6)
        for var in (self.url,self.username,self.password,self.ca):var.trace_add('write',lambda *args:self.connection_changed())
        self.refresh_buttons();self.after(100,self.poll)

    def connection_values(self):return (self.url.get().strip(),self.username.get().strip(),self.password.get(),self.ca.get().strip())
    def connection_matches(self):return self.bound_connection is not None and self.bound_connection==self.connection_values()
    def connection_changed(self):
        if self.bound_connection and not self.connection_matches():
            self.connection_info.set('Параметры подключения изменены. Получите настройки устройства заново.')
            self.diagnostics.clear()
        self.refresh_buttons()
    def refresh_buttons(self):
        if not hasattr(self,'action_buttons'):return
        for command,button in self.action_buttons.items():
            allowed=not self.busy and self.connection_matches() and (command not in ('plan','apply','container-prepare') or self.data is not None)
            button.configure(state='normal' if allowed else 'disabled')
        self.connect_button.configure(state='disabled' if self.busy else 'normal')
    def load_credentials(self):
        path=filedialog.askopenfilename(filetypes=[('JSON','*.json')])
        if path:
            try:
                creds=json.loads(Path(path).read_text(encoding='utf-8-sig'));creds=creds.get('edge',creds);self.username.set(creds['username']);self.password.set(creds['password'])
            except (OSError,ValueError,KeyError) as e:messagebox.showerror('Учётные данные',str(e),parent=self)
    def load_lab(self):
        try:
            creds=json.loads((ROOT/'runtime/credentials.json').read_text())['edge'];self.url.set('api://127.0.0.1:18728');self.username.set(creds['username']);self.password.set(creds['password'])
            self.connection_info.set('Параметры стенда подставлены. Нажмите «Подключиться и получить настройки».')
        except (OSError,ValueError,KeyError) as e:messagebox.showerror('Лаборатория',str(e),parent=self)
    def make_router(self,values):
        url,user,password,ca=values
        if not user:raise ValueError('Введите логин MikroTik.')
        return Router(ROOT,url,ca=ca or None,credentials_data={'username':user,'password':password})
    def connect(self):
        if self.busy:return
        self.diagnostics.clear('Подключение и чтение устройства…')
        values=self.connection_values();self.busy=True;self.refresh_buttons();self.connection_info.set('Подключение и чтение настроек…')
        def work():
            router=None
            try:
                router=self.make_router(values);inventory=discover(router)
                self.messages.put(('discovered',(values,inventory)))
            except Exception as e:self.messages.put(('error',str(e)))
            finally:
                if router:router.close()
        threading.Thread(target=work,daemon=True).start()
    def accept_generated(self,c,inventory):
        name=inventory['identity']['name'];safe=re.sub(r'[^A-Za-z0-9_.-]','_',name)
        self.path=ROOT/'config'/('discovered-'+safe+'.json');self.render_config(c)
        self.summary.set(f"Конфигурация для {name}: {len(c['wans'])} WAN, {len(c['policies'])} политик. Приоритет: {' → '.join(w['interface'] for w in c['wans'])}. Чтение и генерация не изменили MikroTik. Изменения устанавливаются отдельной кнопкой.")
        self.steps.select(self.review);self.refresh_buttons()
        self.log.insert('end','\nКонфигурация создана из прочитанных настроек. Локальные сети: '+', '.join(c['local_networks'])+'\n')
        self.log.insert('end','Включены connection/routing marks: симметричные ответы WAN и DNAT, привязка потоков к WAN и выборочная очистка conntrack при переключении/возврате.\n')
        if c.get('disable_fasttrack'):self.log.insert('end','В план включено отключение FastTrack для корректной работы политик. Исходное состояние сохраняется для отката.\n')
        if not any(n.get('action') in ('masquerade','src-nat') and n.get('disabled')!='true' for n in inventory.get('ip/firewall/nat',[])):self.log.insert('end','На устройстве не найден исходящий NAT. Генератор сохраняет текущую схему NAT/firewall; её нужно согласовать перед использованием интернета клиентами.\n')
    def render_config(self,c):
        validate(c);self.data=copy.deepcopy(c)
        for t in self.tabs.tabs():self.tabs.nametowidget(t).destroy()
        self.wans=Table(self.tabs,WAN_FIELDS,c['wans'],wan=True);self.tabs.add(self.wans,text='Каналы WAN')
        rows=[dict(name=k,**v) for k,v in c['sla_profiles'].items()]
        self.slas=Table(self.tabs,SLA_FIELDS,rows);self.tabs.add(self.slas,text='SLA-профили')
        self.policies=Table(self.tabs,POLICY_FIELDS,ordered(c));self.tabs.add(self.policies,text='Клиенты и приложения')
        ttk.Label(self.policies,text='Изменение групп, условий или порядка правил пересоздаёт управляемые исходящие соединения. Входящее управление сохраняется.',wraplength=1100).pack(fill='x',pady=5)
        self.groups=Table(self.tabs,GROUP_FIELDS,[{'name':name,'members':members} for name,members in c.get('groups',{}).items()]);self.tabs.add(self.groups,text='Группы адресов')
        self.policies.choices=lambda:{'source_group':['']+[r['name'] for r in self.groups.rows],'destination_group':['']+[r['name'] for r in self.groups.rows],'profile':[r['name'] for r in self.slas.rows],**({'in_interface':['']+[r['name'] for r in self.inventory.get('interface',[])]} if self.inventory else {})}
        health=ttk.Frame(self.tabs,padding=12);self.tabs.add(health,text='Контроль и возврат');self.health={}
        for row,(key,label) in enumerate(HEALTH_LABELS.items()):
            v=tk.StringVar(value=str(c['health'][key]));self.health[key]=v;ttk.Label(health,text=label).grid(row=row,column=0,sticky='w',pady=4);ttk.Entry(health,textvariable=v,width=12).grid(row=row,column=1,padx=10)
        controller=ttk.Frame(self.tabs,padding=12);self.tabs.add(controller,text='Контроллер')
        self.backend=tk.StringVar(value=next(k for k,v in BACKENDS.items() if v==c.get('controller_backend','routeros')))
        ttk.Label(controller,text='Где выполняются решения SD-WAN').grid(row=0,column=0,sticky='w',pady=5)
        choice=ttk.Combobox(controller,textvariable=self.backend,values=list(BACKENDS),state='readonly',width=34);choice.grid(row=0,column=1,sticky='w')
        ttk.Label(controller,text='Оба варианта работают на самом MikroTik. При остановке контейнера выбор WAN продолжает скрипт RouterOS.',wraplength=850).grid(row=1,columnspan=2,sticky='w',pady=10)
        params=container_settings(c)
        if 'container' not in c and self.inventory:
            arch=self.inventory.get('resource',{}).get('architecture-name','')
            if arch in ('arm','arm64'):params['image_file']='sdwan-controller-'+('armv5' if arch=='arm' else 'arm64')+'.tar'
        self.container_vars={};self.container_entries=[]
        for row,(key,label) in enumerate([('subnet','Отдельная сеть контейнера (/30)'),('storage','Каталог данных на MikroTik'),('image_file','Архив образа на MikroTik'),('poll_ms','Интервал опроса, мс'),('memory_max_bytes','Лимит памяти, байт')],2):
            var=tk.StringVar(value=str(params[key]));self.container_vars[key]=var
            ttk.Label(controller,text=label).grid(row=row,column=0,sticky='w',pady=4)
            entry=ttk.Entry(controller,textvariable=var,width=48);entry.grid(row=row,column=1,sticky='w',pady=4);self.container_entries.append(entry)
        ttk.Label(controller,text='Для контейнера заранее установите пакет container и разрешите device-mode с физическим подтверждением.\nЗагрузите подходящий scratch-архив на MikroTik, затем нажмите «Подготовить контейнер» и «Установить».\nПароль отдельного API-пользователя создаётся автоматически и хранится отдельно от образа и JSON. Сеть контейнера добавляется в локальные сети.',wraplength=1050).grid(row=8,columnspan=2,sticky='w',pady=10)
        self.backend.trace_add('write',self.backend_changed);self.backend_changed()
        settings=ttk.Frame(self.tabs,padding=12);self.tabs.add(settings,text='Файл и локальные сети')
        self.revision=tk.StringVar(value=c['revision']);ttk.Label(settings,text='Версия конфигурации').pack(anchor='w');ttk.Entry(settings,textvariable=self.revision,width=50).pack(anchor='w',pady=5)
        ttk.Label(settings,text='Локальные сети (одна на строку), маршрутизируются через main').pack(anchor='w');self.local=tk.Text(settings,height=5,width=65);self.local.pack(anchor='w');self.local.insert('1.0','\n'.join(c['local_networks']))
        ttk.Label(settings,text='Исходные маршруты и локальные сети получены при чтении MikroTik. Перечень изменений доступен кнопкой «План изменений».').pack(anchor='w',pady=10)
        self.title('MikroTik SD-WAN — '+str(self.path))
    def load(self,path):
        self.path=Path(path);c=json.loads(self.path.read_text(encoding='utf-8-sig'));self.render_config(c);self.steps.select(self.review);self.refresh_buttons()
    def collect(self):
        if self.data is None:raise ValueError('Сначала получите настройки и создайте конфигурацию, либо откройте готовый JSON.')
        c=copy.deepcopy(self.data);c['wans']=self.wans.rows;c['policies']=self.policies.rows
        groups={row['name']:row['members'] for row in self.groups.rows}
        if len(groups)!=len(self.groups.rows):raise ValueError('Повторяются имена групп')
        if groups:c['groups']=groups
        else:c.pop('groups',None)
        c['sla_profiles']={row['name']:{k:v for k,v in row.items() if k!='name'} for row in self.slas.rows}
        if len(c['sla_profiles'])!=len(self.slas.rows):raise ValueError('Повторяются имена SLA-профилей')
        c['health']={k:int(v.get()) for k,v in self.health.items()};c['revision']=self.revision.get().strip();c['local_networks']=[x.strip() for x in self.local.get('1.0','end').splitlines() if x.strip()]
        if BACKENDS[self.backend.get()]=='container':
            c['controller_backend']='container';c['container']={key:int(var.get()) if key in ('poll_ms','memory_max_bytes') else var.get().strip() for key,var in self.container_vars.items()}
            subnet=ipaddress.IPv4Network(c['container']['subnet'],strict=True)
            if not any(subnet.subnet_of(ipaddress.IPv4Network(item)) for item in c['local_networks']):
                c['local_networks'].append(str(subnet));self.local.insert('end','\n'+str(subnet))
        else:
            c.pop('controller_backend',None);c.pop('container',None)
        return validate(c)
    def backend_changed(self,*args):
        state='normal' if BACKENDS.get(self.backend.get())=='container' else 'disabled'
        for widget in self.container_entries:widget.configure(state=state)
    def open(self):
        path=filedialog.askopenfilename(filetypes=[('SD-WAN JSON','*.json')])
        if path:
            try:self.load(path)
            except Exception as e:messagebox.showerror('Файл',str(e))
    def save(self):
        try:
            c=self.collect();p=filedialog.asksaveasfilename(initialfile=self.path.name,initialdir=self.path.parent,defaultextension='.json',filetypes=[('JSON','*.json')])
            if p:Path(p).write_text(json.dumps(c,indent=2,ensure_ascii=False)+'\n',encoding='utf-8');self.path=Path(p);self.title('MikroTik SD-WAN — '+p)
        except Exception as e:messagebox.showerror('Проверка',str(e))
    def check(self):
        try:
            c=self.collect();overlaps=conflicts(c);messagebox.showinfo('Конфигурация корректна',f'{len(c["wans"])} WAN, {len(c["sla_profiles"])} SLA, {len(c["policies"])} политик.\nКонтроллер: {self.backend.get()}.\nПересечений с явным приоритетом: {len(overlaps)}.\n'+ '\n'.join(x['first']+' → '+x['later']+(' (полностью перекрыта)' if x['shadowed'] else '') for x in overlaps))
        except Exception as e:messagebox.showerror('Проверка',str(e))
    def export(self):
        try:
            c=self.collect();dest=filedialog.askdirectory(title='Каталог файлов RouterOS')
            if not dest:return
            from importlib.util import spec_from_file_location,module_from_spec
            spec=spec_from_file_location('deploy_cli',ROOT/'sdwan.py');m=module_from_spec(spec);spec.loader.exec_module(m);m.bundle(c,dest)
            messagebox.showinfo('Готово','Созданы JSON конфигурации и восемь файлов .rsc.\nДля защищённой установки используйте кнопку установки через API; ручная процедура описана в документации.')
        except Exception as e:messagebox.showerror('Экспорт',str(e))
    def run(self,command):
        if self.busy:return
        try:
            if not self.connection_matches():raise ValueError('Подключитесь к MikroTik и получите его настройки.')
            config=self.collect() if command in ('plan','apply','container-prepare') else None
            values=self.connection_values();expected=self.inventory['identity']['name'];self.busy=True;self.refresh_buttons()
            self.log.insert('end',f'\n--- {command} ---\n');self.log.see('end')
            def work():
                router=None;output=io.StringIO()
                try:
                    router=self.make_router(values)
                    if router.call('system/identity')['name']!=expected:raise ValueError('Имя подключённого роутера изменилось; получите настройки заново.')
                    spec=importlib.util.spec_from_file_location('sdwan_deploy_cli',ROOT/'sdwan.py');cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
                    with contextlib.redirect_stdout(output):
                        if command=='plan':print(json.dumps(cli.preflight(router,config,expected),indent=2,ensure_ascii=False))
                        elif command=='apply':cli.apply(router,config,expected)
                        elif command=='container-prepare':
                            from sdwan.container_runtime import prepare
                            print(json.dumps(prepare(router,config,expected),indent=2,ensure_ascii=False))
                        elif command=='diagnostics':
                            from sdwan.diagnostics import read
                            snapshot,active=read(router);self.messages.put(('diagnostics',(values,snapshot,active)));return
                        elif command=='status':print(json.dumps(router.status(),indent=2,ensure_ascii=False))
                        elif command=='events':print(json.dumps([r for r in router.call('log') if r.get('message','').startswith('SDWAN ')],indent=2,ensure_ascii=False))
                        elif command=='rollback':cli.rollback(router,expected)
                    self.messages.put(('operation',(output.getvalue(),0)))
                except Exception as e:
                    if command=='diagnostics':self.messages.put(('diagnostics_error',(values,str(e))))
                    else:self.messages.put(('operation',(output.getvalue()+str(e),1)))
                finally:
                    if router:router.close()
            threading.Thread(target=work,daemon=False).start()
        except Exception as e:self.busy=False;self.refresh_buttons();messagebox.showerror('Проверка',str(e),parent=self)
    def poll(self):
        try:
            kind,payload=self.messages.get_nowait();self.busy=False
            if kind=='discovered':
                values,inventory=payload
                if values!=self.connection_values():self.connection_info.set('Адрес или учётные данные изменились во время чтения. Подключитесь заново.')
                else:
                    self.diagnostics.clear('Устройство подключено. Нажмите «Обновить» на вкладке диагностики.')
                    self.bound_connection=values;self.inventory=inventory;self.identity.set(inventory['identity']['name']);self.data=None
                    for tab in self.tabs.tabs():self.tabs.nametowidget(tab).destroy()
                    self.summary.set('Выберите внешние WAN и создайте конфигурацию по прочитанным настройкам.')
                    self.connection_info.set(f"Подключено: {inventory['identity']['name']} · RouterOS {inventory['resource']['version']}. Получены интерфейсы, адреса, маршруты и текущие политики.")
                    self.setup.load_inventory(inventory);self.steps.select(self.setup.iface_page)
                    run=ROOT/'runtime';run.mkdir(exist_ok=True);stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                    (run/f'discovery-{stamp}.json').write_text(json.dumps(inventory,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
                    self.log.insert('end','\nНастройки прочитаны. Ни одна настройка MikroTik не изменена.\n')
                    for warning in inventory['warnings']:self.log.insert('end',warning+'\n')
            elif kind=='diagnostics':
                values,snapshot,active=payload
                if self.connection_matches() and values==self.connection_values():self.diagnostics.update_snapshot(snapshot,active)
            elif kind=='diagnostics_error':
                values,error=payload
                if values==self.connection_values():self.diagnostics.clear('Не удалось обновить диагностику: '+error)
            elif kind=='operation':
                output,code=payload;self.log.insert('end',output+f'\nКод завершения: {code}\n');self.log.see('end')
            else:
                self.bound_connection=None;self.connection_info.set('Подключение не выполнено: '+payload);self.log.insert('end','\n'+payload+'\n')
            self.refresh_buttons()
        except queue.Empty:pass
        self.after(100,self.poll)

if __name__=='__main__':App().mainloop()
