"""Tk operational dashboard, fed only by read-only snapshots."""
import json
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from .diagnostics import explain,REASONS


class DiagnosticsPanel(ttk.Frame):
    def __init__(self,parent,app):
        super().__init__(parent,padding=8);self.app=app;self.report=None;self.active_config=None;self.received_at=None;self.initial_stale=False;self.last_auto=0
        self.summary=tk.StringVar(value='Подключитесь к MikroTik и обновите диагностику.');self.auto=tk.BooleanVar(value=False)
        bar=ttk.Frame(self);bar.pack(fill='x')
        ttk.Button(bar,text='Обновить',command=lambda:app.run('diagnostics')).pack(side='left')
        ttk.Checkbutton(bar,text='Автообновление каждые 5 с',variable=self.auto).pack(side='left',padx=10)
        ttk.Button(bar,text='Экспорт диагностики JSON',command=self.export).pack(side='right')
        ttk.Label(self,textvariable=self.summary,wraplength=1150).pack(fill='x',pady=8)
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True)
        self.wans=self.table('Каналы WAN',[('name','WAN',70),('interface','Интерфейс',130),('kind','Тип',70),('apn_profile','APN профиль',120),('address','IP',130),('gateway','Шлюз',125),('state','SLA общей политики',170),('rtt','RTT, мс',85),('jitter','Jitter, мс',85),('loss','Потери, %',85),('age','Возраст проб, с',110),('quorum','Цели / кворум',115),('reason','Причина',350)])
        self.policies=self.table('Политики и выбор WAN',[('name','Политика',130),('priority','Приоритет',90),('source','Источник',150),('match','Условия потока',350),('profile','SLA',100),('mode','Режим',80),('selected','Выбран WAN',110),('wans','Порядок WAN',200),('reason','Причина выбора',300)])
        self.sla=self.table('SLA и возврат',[('profile','Профиль',100),('wan','WAN',80),('state','Состояние',110),('verdict','Текущее окно',120),('good_windows','Хороших окон',110),('bad_windows','Плохих окон',110),('recover_windows_remaining','Окон до возврата',130),('hold_remaining_seconds','Hold-down, с',110),('reason','Причина',400)])
        self.events=self.table('История переключений',[('seq','№',65),('estimated_utc','Время UTC (оценка по ПК)',210),('uptime_seconds','Uptime, с',95),('revision','Конфигурация',170),('type','Событие',95),('object','Объект',160),('from','Было',110),('to','Стало',110),('removed','Удалено CT',95),('reason','Причина',400)])
        frame=ttk.LabelFrame(self,text='Проверка нового исходящего соединения по действующей конфигурации',padding=6);frame.pack(fill='x',pady=8)
        self.flow={}
        for i,(key,label,initial) in enumerate([('source','IP клиента',''),('destination','IP назначения',''),('protocol','Протокол','tcp'),('src_port','Порт источника',''),('dst_port','Порт назначения','443'),('in_interface','Входной интерфейс/VLAN','')]):
            ttk.Label(frame,text=label).grid(row=0,column=i,sticky='w',padx=3)
            var=tk.StringVar(value=initial);self.flow[key]=var
            widget=ttk.Combobox(frame,textvariable=var,values=('tcp','udp','icmp'),state='readonly',width=9) if key=='protocol' else ttk.Entry(frame,textvariable=var,width=18)
            widget.grid(row=1,column=i,sticky='ew',padx=3)
        ttk.Button(frame,text='Показать политику',command=self.explain_flow).grid(row=1,column=6,padx=5)
        self.flow_result=tk.StringVar(value='Для VLAN указывайте логический входной интерфейс RouterOS. Уже установленные соединения используют сохранённую метку.')
        ttk.Label(frame,textvariable=self.flow_result,wraplength=1150).grid(row=2,columnspan=7,sticky='w',pady=6)
        self.detail=tk.Text(self,height=4,wrap='word');self.detail.pack(fill='x');self.detail.configure(state='disabled')
        self.policies.bind('<<TreeviewSelect>>',self.policy_detail)
        self.after(1000,self.tick)

    def table(self,title,columns):
        frame=ttk.Frame(self.tabs);self.tabs.add(frame,text=title)
        tree=ttk.Treeview(frame,columns=[x[0] for x in columns],show='headings',height=9)
        for key,label,width in columns:tree.heading(key,text=label);tree.column(key,width=width,minwidth=55,stretch=False)
        y=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);x=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        tree.tag_configure('bad',foreground='#b3261e');tree.tag_configure('wait',foreground='#8a5700');tree.tag_configure('good',foreground='#166534')
        return tree

    def tick(self):
        now=time.monotonic()
        if self.report and self.received_at is not None:
            elapsed=now-self.received_at
            limit=(self.active_config or {}).get('health',{}).get('stale_seconds',10)
            self.report['telemetry_stale']=self.initial_stale or elapsed>limit
            self.report['display_age_seconds']=round(elapsed,1)
            self.summary.set(self.summary_base+f' · снимок получен {elapsed:.0f} с назад'+(' · ДАННЫЕ УСТАРЕЛИ' if self.report['telemetry_stale'] else ''))
            for i,row in enumerate(self.report['wans']):
                if self.wans.exists(str(i)):
                    if row['sample_age_seconds'] is not None:self.wans.set(str(i),'age',f"{row['sample_age_seconds']+elapsed:.1f}")
                    if self.report['telemetry_stale']:self.wans.set(str(i),'state','Устарел');self.wans.item(str(i),tags=('bad',))
        if self.auto.get() and now-self.last_auto>=5 and self.app.steps.select()==str(self) and not self.app.busy and self.app.connection_matches():
            self.last_auto=now;self.app.run('diagnostics')
        self.after(1000,self.tick)

    @staticmethod
    def fill(tree,rows):
        selected=tree.selection();tree.delete(*tree.get_children());cols=tree['columns']
        for i,row in enumerate(rows):tree.insert('',tk.END,iid=str(i),values=[row.get(k,'—') if row.get(k) is not None else '—' for k in cols],tags=(row.get('_tag',''),))
        if selected and tree.exists(selected[0]):tree.selection_set(selected[0])

    def clear(self,message='Подключение изменилось. Получите свежую диагностику.'):
        self.report=None;self.active_config=None;self.received_at=None;self.summary.set(message)
        for tree in (self.wans,self.policies,self.sla,self.events):tree.delete(*tree.get_children())
        self.flow_result.set('Нет свежих данных для объяснения потока.')
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.configure(state='disabled')

    def update_snapshot(self,report,config):
        self.report=report;self.active_config=config;self.received_at=time.monotonic();self.initial_stale=report['telemetry_stale']
        state='Остановлен' if not report['enabled'] else ('Устаревшая телеметрия' if report['telemetry_stale'] else 'Работает')
        self.summary_base=f"{report['identity']} · RouterOS {report['routeros_version']} · {report['revision'] or 'нет SD-WAN'} · {state} · возраст статуса {report['controller_age_seconds']} с · удалено conntrack: {report['conntrack_removed']}"+(' · ОШИБКА: '+report['error'] if report['error'] else '')
        mode=report.get('controller_mode','routeros')
        self.summary_base+=' · '+{'container':'Решения: локальный Rust-контейнер','routeros-fallback':'Решения: резервный скрипт RouterOS','routeros':'Решения: скрипт RouterOS','unknown':'Контроллер: нет свежих данных'}.get(mode,mode)
        if report.get('container',{}).get('error'):self.summary_base+=' · '+report['container']['error']
        self.summary.set(self.summary_base)
        def ms(value):return '—' if value is None or value>=2147483647 else f'{value/1000:.3f}'
        rows=[]
        for r in report['wans']:
            row=dict(r,rtt=ms(r['rtt_us']),jitter=ms(r['jitter_us']),loss='—' if r['loss_basis_points'] is None else f"{r['loss_basis_points']/100:.2f}",age='—' if r['sample_age_seconds'] is None else f"{r['sample_age_seconds']:.1f}",quorum=f"{r['up']}/{r['total']} · нужно {r['quorum']}")
            row['state']='Устарел' if r['stale'] else ('Прогрев' if r['warming'] else ({'healthy':'Исправен','degraded':'Нарушение SLA','down':'Недоступен','recovering':'Восстановление','unknown':'Нет измерений'}.get(r['state'],r['state']) if r['link_ready'] else 'Нет линии / IP'));row['_tag']='bad' if r['stale'] or not r['link_ready'] else ('wait' if r['warming'] or r['state'] in ('recovering','unknown') else 'good' if r['state']=='healthy' else 'bad');rows.append(row)
        self.fill(self.wans,rows)
        rows=[]
        for r in report['policies']:
            match=', '.join(f'{key}={r[key]}' for key in ('source_group','destination','destination_group','in_interface','protocol','src_ports','dst_ports') if r.get(key) and r[key]!='any')
            rows.append(dict(r,source=r.get('source') or 'Все остальные',priority=r.get('priority','после явных'),match=match or 'Любой поток',wans=' → '.join(r['wans']),_tag='bad' if r['selected']=='none' else 'good'))
        self.fill(self.policies,rows);self.fill(self.sla,[dict(r,_tag='good' if r['state']=='healthy' else 'wait' if r['state']=='recovering' else 'bad') for r in report['sla']])
        self.fill(self.events,[dict(r,object=r.get('policy') or r.get('wan','')) for r in reversed(report['events'])]);self.policy_detail()

    def policy_detail(self,event=None):
        text='Приоритет: меньшее число выполняется раньше; общая политика всегда последняя.'
        if self.report:
            selected=self.policies.selection()
            if selected:
                row=self.report['policies'][int(selected[0])]
                text=f"{row['name']}: {row['reason']}. SLA: {row['profile']}, режим: {row['mode']}."
                text+='\nКандидаты: '+'; '.join(f"{c['wan']}: {c.get('state','unknown')} — {REASONS.get(c.get('reason'),c.get('reason','нет измерений'))}" for c in row['candidates'])
                cleanup=row.get('last_cleanup') or {}
                if cleanup:text+=f"\nПоследняя очистка conntrack: {cleanup.get('from','?')} → {cleanup.get('to','?')}, удалено {cleanup.get('removed',0)}."

            elif self.report['overlaps']:text+='\nПересечения с явным порядком: '+json.dumps(self.report['overlaps'],ensure_ascii=False)
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',text);self.detail.configure(state='disabled')

    def explain_flow(self,*,fresh_lists=False):
        try:
            if not self.report:raise ValueError('Сначала обновите диагностику')
            if not fresh_lists and any(p.get('destination_list') for p in (self.active_config or {}).get('policies',[])):
                self.app.run('address-lists');return
            flow={k:v.get().strip() for k,v in self.flow.items()}
            for key in ('src_port','dst_port'):flow[key]=int(flow[key]) if flow[key] else None
            result=explain(self.active_config,self.report,**flow)
            self.flow_result.set(result['reason'] if result.get('bypass') else f"Политика {result['policy']} → WAN {result['selected']} · SLA {result['profile']} · {result['wan_reason']}"+(' · СТАТУС УСТАРЕЛ' if result['telemetry_stale'] else ''))
        except (ValueError,TypeError) as error:self.flow_result.set(str(error))

    def export(self):
        if not self.report:return
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='sdwan-diagnostics.json',filetypes=[('JSON','*.json')])
        if path:
            try:Path(path).write_text(json.dumps(self.report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            except OSError as error:messagebox.showerror('Экспорт',str(error),parent=self)
