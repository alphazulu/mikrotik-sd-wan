"""Add an existing VPN client to the ordinary WAN collection."""
import tkinter as tk
from tkinter import ttk,messagebox
from sdwan.vpn_egress import add_wan,canonical,wan_flag

class VPNDialog(tk.Toplevel):
 def __init__(self,parent,config,inventory):
  super().__init__(parent);self.title('Добавить / настроить VPN WAN');self.transient(parent);self.result=None;self.cfg=canonical(config);self.inventory=inventory;self.links=[v for v in inventory.get('vpn_interfaces',[]) if not v.get('unsupported_reason')]
  body=ttk.Frame(self,padding=16);body.pack(fill='both',expand=True);self.vars={};physical=[w['name'] for w in config['wans'] if w.get('kind')!='vpn'];names={w['name'] for w in config['wans']};number=1
  while 'vpn'+str(number) in names:number+=1
  labels=[v['interface']+' ['+v['vpn_type']+']' for v in self.links]
  for row,(key,label,value,choices) in enumerate([('interface','Уже настроенный VPN',labels[0] if labels else '',labels),('name','Имя WAN','vpn'+str(number),None),('underlays','Физические WAN для самого туннеля',', '.join(physical),None)]):
   ttk.Label(body,text=label).grid(row=row,column=0,sticky='w',pady=6);var=tk.StringVar(value=value);self.vars[key]=var
   widget=ttk.Entry(body,textvariable=var,width=45) if choices is None else ttk.Combobox(body,textvariable=var,values=choices,state='readonly',width=43);widget.grid(row=row,column=1,sticky='ew',padx=8,pady=6)
   if key=='interface':widget.bind('<<ComboboxSelected>>',self.selected)
  self.nat=tk.BooleanVar(value=False);self.forward=tk.BooleanVar(value=False)
  ttk.Checkbutton(body,text='NAT для исходящих соединений, выбравших этот WAN',variable=self.nat).grid(row=3,columnspan=2,sticky='w',pady=5)
  ttk.Checkbutton(body,text='Разрешить в firewall соединения, выбравшие этот WAN',variable=self.forward).grid(row=4,columnspan=2,sticky='w',pady=5)
  ttk.Label(body,text='VPN добавляется в общую таблицу WAN. Эта операция не создаёт правил маршрутизации и не меняет порядок существующих политик. Затем выберите его в обычной политике по IP или Address List источника/назначения, либо в общей политике.\n\nПорядок физических WAN выше определяет только связь с VPN-сервером. Приоритет пользовательского трафика задаётся в политике. SLA, автоматическое переключение, возврат, drain и conntrack общие для всех WAN.\n\nПроверьте контрольные цели во вкладке WAN: они должны быть доступны через этот VPN. Пароли, сертификаты и закрытые ключи остаются в настроенном клиенте MikroTik. Изменения устанавливаются общей защищённой установкой.',wraplength=670).grid(row=5,columnspan=2,sticky='w',pady=12)
  bar=ttk.Frame(body);bar.grid(row=6,columnspan=2,sticky='e');ttk.Button(bar,text='Отмена',command=self.destroy).pack(side='left',padx=5);ttk.Button(bar,text='Сохранить WAN в проекте',command=self.accept).pack(side='left');self.selected();self.grab_set();self.wait_window()
 def selected(self,*args):
  label=self.vars['interface'].get();link=next((v for v in self.links if label==v['interface']+' ['+v['vpn_type']+']'),None)
  if not link:return
  old=next((w for w in self.cfg['wans'] if w['interface']==link['interface'] and w.get('kind')=='vpn'),None)
  if old:self.vars['name'].set(old['name']);self.vars['underlays'].set(', '.join(old['underlays']));self.nat.set(wan_flag(self.cfg,old,'masquerade'));self.forward.set(wan_flag(self.cfg,old,'allow_selected_forward'))
  else:self.nat.set(False);self.forward.set(False)
 def accept(self):
  try:
   label=self.vars['interface'].get();link=next((v for v in self.links if label==v['interface']+' ['+v['vpn_type']+']'),None)
   if link is None:raise ValueError('Получите настройки MikroTik с уже настроенным клиентом WireGuard, L2TP, SSTP или OpenVPN IP.')
   self.result=add_wan(self.cfg,link,name=self.vars['name'].get().strip(),underlays=[s.strip() for s in self.vars['underlays'].get().split(',') if s.strip()],masquerade=self.nat.get(),allow_selected_forward=self.forward.get(),routes=self.inventory.get('ip/route',[]));self.destroy()
  except (ValueError,KeyError) as e:messagebox.showerror('VPN WAN',str(e),parent=self)
