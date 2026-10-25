"""Optional existing-VPN configuration dialog; no router mutations or passwords."""
import tkinter as tk
from tkinter import ttk,messagebox
from sdwan.vpn_egress import configure,disable

class VPNDialog(tk.Toplevel):
 def __init__(self,parent,config,inventory):
  super().__init__(parent);self.title('VPN по Address List');self.transient(parent);self.result=None;self.cfg=config;self.inventory=inventory;self.links=[v for v in inventory.get('vpn_interfaces',[]) if not v.get('unsupported_reason')]
  body=ttk.Frame(self,padding=16);body.pack(fill='both',expand=True);self.vars={}
  physical=[w['name'] for w in config['wans'] if w.get('kind')!='vpn'];names={w['name'] for w in config['wans']};number=1
  while 'vpn'+str(number) in names:number+=1
  labels=[v['interface']+' ['+v['vpn_type']+']' for v in self.links]
  values=[('interface','Уже настроенный VPN',labels[0] if labels else '',labels),('name','Имя канала','vpn'+str(number),None),('list','Address List назначения','',inventory.get('address_list_names',[])),('underlays','Физические WAN для связи с сервером',', '.join(physical),None),('backups','Резервные выходы для целевого трафика',', '.join(physical),None)]
  for row,(key,label,value,choices) in enumerate(values):
   ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',pady=6);var=tk.StringVar(value=value);self.vars[key]=var
   if choices is None:entry=ttk.Entry(body,textvariable=var,width=45)
   else:entry=ttk.Combobox(body,textvariable=var,values=choices,state='readonly' if key=='interface' else 'normal',width=43)
   entry.grid(row=row,column=1,sticky='ew',padx=8,pady=6)
   if key=='interface':entry.bind('<<ComboboxSelected>>',self.selected)
  self.enabled=tk.BooleanVar(value=bool(config.get('vpn_egress',{}).get('enabled',False)));self.nat=tk.BooleanVar(value=config.get('vpn_egress',{}).get('masquerade',False));self.forward=tk.BooleanVar(value=config.get('vpn_egress',{}).get('allow_selected_forward',False))
  for row,(var,label) in enumerate([(self.enabled,'Включить опциональный VPN-egress'),(self.nat,'Добавить NAT только для выбранных SD-WAN соединений через VPN'),(self.forward,'Разрешить в firewall выбранные SD-WAN соединения через VPN')],len(values)):
   ttk.Checkbutton(body,text=label,variable=var).grid(row=row,columnspan=2,sticky='w',pady=5)
  ttk.Label(body,text='Первым используется VPN; затем выходы из списка резервов слева направо. Общий интернет-маршрут остаётся на физических WAN. При отказе SLA старые соединения этой политики закрываются, после восстановления приоритет возвращается.\n\nКонтрольные цели берутся из первого WAN: проверьте их во вкладке каналов — они должны подтверждать доступ к нужным ресурсам через VPN. Пароли и ключи остаются в существующем клиенте RouterOS.\n\nСнятие галочки VPN-egress исключает все VPN-выходы из проекта: политики сохраняют физические резервы, VPN-only политики удаляются. Существующие клиенты остаются настроенными; автодефолты подавлены до отката к исходному.\n\nПустой или будущий Address List допустим: он не перехватывает трафик. Изменения применяются только после просмотра плана и установки.',wraplength=650).grid(row=8,columnspan=2,sticky='w',pady=12)
  buttons=ttk.Frame(body);buttons.grid(row=9,columnspan=2,sticky='e');ttk.Button(buttons,text='Отмена',command=self.destroy).pack(side='left',padx=5);ttk.Button(buttons,text='Создать конфигурацию',command=self.accept).pack(side='left')
  self.selected();self.grab_set();self.wait_window()
 def selected(self,*args):
  label=self.vars['interface'].get();link=next((v for v in self.links if label==v['interface']+' ['+v['vpn_type']+']'),None)
  if not link:return
  old=next((w for w in self.cfg['wans'] if w['interface']==link['interface'] and w.get('kind')=='vpn'),None)
  if old:
   self.vars['name'].set(old['name']);self.vars['underlays'].set(', '.join(old['underlays']))
   p=next((p for p in self.cfg['policies'] if p['name']=='vpn-'+old['name']),None)
   if p:self.vars['list'].set(p.get('destination_list',''));self.vars['backups'].set(', '.join(p['wans'][1:]))
 def accept(self):
  try:
   if not self.enabled.get():
    self.result=disable(self.cfg);self.destroy();return
   label=self.vars['interface'].get();link=next((v for v in self.links if label==v['interface']+' ['+v['vpn_type']+']'),None)
   if link is None:raise ValueError('Получите настройки роутера с уже настроенным и включённым VPN-клиентом. Поддерживаются WireGuard, L2TP, SSTP и OpenVPN в режиме IP.')
   csv=lambda key:[s.strip() for s in self.vars[key].get().split(',') if s.strip()]
   self.result=configure(self.cfg,link,name=self.vars['name'].get().strip(),address_list=self.vars['list'].get().strip(),underlays=csv('underlays'),backups=csv('backups'),masquerade=self.nat.get(),allow_selected_forward=self.forward.get(),routes=self.inventory.get('ip/route',[]));self.destroy()
  except (ValueError,KeyError) as error:messagebox.showerror('VPN-egress',str(error),parent=self)
