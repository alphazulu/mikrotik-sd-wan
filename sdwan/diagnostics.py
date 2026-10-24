"""Read-only, allowlisted operational view. Never makes routing decisions."""
import copy
from datetime import datetime,timezone,timedelta
import json
import re
from .policies import match_flow,ordered,conflicts

REASONS={'within SLA':'В пределах SLA','SLA threshold exceeded':'Превышен порог SLA','probe quorum unavailable':'Нет кворума контрольных целей','stale probe telemetry':'Измерения устарели','address/session changed: waiting for fresh probe generation':'Ожидание свежих проб после смены адреса/сессии','interface unavailable':'Интерфейс недоступен','ready':'Готов','first healthy WAN in policy order':'Первый исправный WAN в заданном порядке','no eligible WAN within SLA; policy fails closed':'Нет допустимого WAN по SLA; политика закрыта','degraded fallback explicitly allowed':'Разрешён резерв с нарушением SLA'}

REASONS['local Rust container intent; current RouterOS SLA validated']='Локальный Rust-контейнер; текущий SLA проверен RouterOS'

def seconds(value):
    if isinstance(value,(int,float)):return float(value)
    text=str(value);total=0
    for number,unit in re.findall(r'(\d+(?:\.\d+)?)(w|d|h|m|s)',text):total+=float(number)*{'w':604800,'d':86400,'h':3600,'m':60,'s':1}[unit]
    clock=re.search(r'(\d+):(\d+):(\d+(?:\.\d+)?)',text)
    if clock:total+=float(clock[1])*3600+float(clock[2])*60+float(clock[3])
    return total


def view(status,config=None,*,identity='',version='',router_uptime=None,router_addresses=()):
    status=dict(status)
    for key in ('samples','selected','states','policies','last_cleanup'):
        if not isinstance(status.get(key),dict):status[key]={}
    config=config or {};now=status.get('uptime_seconds',0);age=max(0,(router_uptime if router_uptime is not None else now)-now)
    health=config.get('health',{});limit=health.get('stale_seconds',10)
    stale=not status.get('enabled',False) or bool(status.get('error')) or age>limit or (config.get('revision') and status.get('revision')!=config['revision'])
    result={'received_utc':datetime.now(timezone.utc).isoformat(),'identity':identity,'routeros_version':version,'revision':status.get('revision'),'controller':status.get('controller','not installed'),'enabled':status.get('enabled',False),'error':status.get('error',''),'controller_age_seconds':round(age,1),'telemetry_stale':bool(stale),'conntrack_removed':status.get('conntrack_removed',0),'wans':[],'policies':[],'sla':[],'events':[],'router_addresses':list(router_addresses),'overlaps':conflicts(config) if config.get('policies') else []}
    backend=status.get('backend','routeros')
    metadata=status.get('container') if isinstance(status.get('container'),dict) else {}
    result['backend']=backend
    result['container']={key:metadata[key] for key in ('active','protocol','boot_id','generation','owner_instance','lease_remaining_seconds','rejection','rejections','last_rejection','error') if key in metadata}
    result['controller_mode']='unknown' if stale else ('container' if backend=='container' and metadata.get('active') is True else 'routeros-fallback' if backend=='container' else 'routeros')
    specs={w['name']:w for w in config.get('wans',[])}
    for name,sample in status.get('samples',{}).items():
        spec=specs.get(name,{})
        row={k:sample.get(k) for k in ('kind','address','gateway','route_gateway','link_ready','carrier','warming','up','total','epoch','rtt_us','jitter_us','loss_basis_points','sample_age_seconds')}
        row.update(name=name,interface=sample.get('interface',spec.get('interface','')),apn_profile=sample.get('apn_profile',spec.get('apn_profile','')),stale=stale or sample.get('stale',False),reason=REASONS.get(sample.get('link_reason'),sample.get('link_reason','')),quorum=health.get('quorum'),sample_age_seconds=None if sample.get('sample_age_seconds') is None else sample['sample_age_seconds']+age)
        if row['stale']:row['reason']='Измерения устарели: '+str(row['reason'])
        result['wans'].append(row)
    for key,state in status.get('states',{}).items():
        profile,_,wan=key.partition('/')
        row={k:state.get(k) for k in ('state','verdict','good_windows','bad_windows','hold_remaining_seconds','recover_windows_remaining')}
        row.update(profile=profile,wan=wan,reason=REASONS.get(state.get('reason'),state.get('reason','')))
        if state.get('verdict')=='degraded':
            thresholds=config.get('sla_profiles',{}).get(profile,{})
            sample=status['samples'].get(wan,{})
            exceeded=[]
            for metric,field,scale,label in [('rtt_us','rtt_ms',1000,'RTT'),('jitter_us','jitter_ms',1000,'jitter'),('loss_basis_points','loss_percent',100,'потери')]:
                if metric in sample and field in thresholds and sample[metric]>thresholds[field]*scale:exceeded.append(f"{label} {sample[metric]/scale:g} > {thresholds[field]:g}")
            if exceeded:row['reason']+=': '+', '.join(exceeded)
        result['sla'].append(row)
    default_profile=next((p['profile'] for p in config.get('policies',[]) if not p['source']),'default')
    for row in result['wans']:
        state=status['states'].get(default_profile+'/'+row['name'],{})
        row.update(profile=default_profile,state=state.get('state','unknown'),verdict=state.get('verdict','unknown'))
        if row['link_ready'] and not row['warming']:
            detail=next((s for s in result['sla'] if s['profile']==default_profile and s['wan']==row['name']),{})
            row['reason']=detail.get('reason',row['reason'])

    for p in ordered(config) if config.get('policies') else []:
        name=p['name'];selected=status.get('selected',{}).get(name,'none');detail=status.get('policies',{}).get(name,{})
        row={k:copy.deepcopy(p[k]) for k in ('name','source','table','profile','mode','wans','priority','source_group','destination','destination_group','in_interface','protocol','src_ports','dst_ports') if k in p}
        row.update(selected=selected,reason=REASONS.get(detail.get('reason'),detail.get('reason','Первый доступный WAN в порядке политики' if selected!='none' else 'Нет допустимого WAN')),candidates=[{'wan':w,**copy.deepcopy(status.get('states',{}).get(p['profile']+'/'+w,{}))} for w in p['wans']],last_cleanup=copy.deepcopy(status.get('last_cleanup',{}).get(name,{})))
        shadow=next((x['first'] for x in result['overlaps'] if x['later']==name and x['shadowed']),None)
        row['effective']=shadow is None
        if shadow:row['reason']='Полностью перекрыта правилом '+shadow+'; '+row['reason']
        result['policies'].append(row)
    for event in status.get('events',[]):
        row={k:event[k] for k in ('seq','uptime_seconds','revision','type','policy','wan','from','to','reason','removed') if k in event}
        if isinstance(event.get('uptime_seconds'),(int,float)) and router_uptime is not None:
            row['estimated_utc']=(datetime.fromisoformat(result['received_utc'])-timedelta(seconds=max(0,router_uptime-event['uptime_seconds']))).isoformat(timespec='seconds')
        result['events'].append(row)
    return result


def read(router):
    status=router.status();identity=router.call('system/identity')['name']
    try:config=json.loads(router.read_file('sdwan-active.json'))
    except ValueError as error:
        if not str(error).startswith('Router file not found:'):raise
        config=None
    addresses=[x['address'].split('/')[0] for x in router.call('ip/address/print',{'.proplist':'address,disabled,invalid'},'POST') if x.get('disabled') not in (True,'true','yes') and x.get('invalid') not in (True,'true','yes')]
    resource=router.call('system/resource')
    if isinstance(resource,list):resource=resource[0]
    return view(status,config,identity=identity,version=resource.get('version',''),router_uptime=seconds(resource.get('uptime',0)),router_addresses=addresses),config


def explain(config,report,**flow):
    if not config:raise ValueError('На устройстве нет действующей конфигурации SD-WAN')
    decision=match_flow(config,router_addresses=report.get('router_addresses',()),**flow)
    if decision.get('bypass'):return decision
    policy=next((p for p in report['policies'] if p['name']==decision['policy']),{})
    decision.update(selected=policy.get('selected','none'),wan_reason=policy.get('reason',''),telemetry_stale=report.get('telemetry_stale',False),scope='new outbound connection; existing connection marks may differ')
    return decision
