"""Read-only readiness and evidence-based mode selection for the GUI/SDK."""
import re

VERSION = '7.24.5'
ARCHITECTURES = {'x86':'amd64', 'x86_64':'amd64', 'arm':'arm', 'arm64':'arm64'}
RESOURCE_FIELDS = 'version,board-name,architecture-name,platform,cpu,cpu-count,cpu-frequency,total-memory,free-memory,total-hdd-space,free-hdd-space,uptime'
CAPABILITY_FIELDS = {
    'system/package':'.id,name,version,disabled,scheduled',
    'system/device-mode':'mode,flagged,scheduler,fetch,container,l2tp,ipsec,attempt-count',
    'disk':'.id,slot,type,fs,size,free,disabled,mount-filesystem,mount-read-only,swap',
    'file':'.id,name,type,size',
}


def boolean(value):
    if value is True or value in ('true','yes','1'): return True
    if value is False or value in ('false','no','0'): return False
    return None


def records(value):
    return value if isinstance(value,list) else [value] if isinstance(value,dict) and value else []


def collect(router):
    """No passwords/keys/serials, tool execution, package changes or disk writes."""
    data={'errors':{}}
    for path,fields in CAPABILITY_FIELDS.items():
        try:
            data[path]=records(router.call(path+'/print',{'.proplist':fields},'POST'))
        except (RuntimeError,ValueError) as error:
            data[path]=[];data['errors'][path]=str(error)
    return data


def workload(config):
    wans=config.get('wans',[])
    return {'wans':len(wans), 'policies':len(config.get('policies',[])),
            'probes':sum(len(w.get('probes',[])) for w in wans),
            'vpn_wans':sum(w.get('kind')=='vpn' for w in wans),
            'overlay_tunnels':len(config.get('overlay',{}).get('tunnels',[]))}


def fingerprint(resource):
    keys=('architecture-name','board-name','cpu','cpu-count','cpu-frequency','total-memory')
    return {key:str(resource.get(key,'')) for key in keys}


def recommend(resource,config,catalog):
    arch=resource.get('architecture-name')
    if arch not in ARCHITECTURES:
        return {'backend':'routeros','confidence':'capability','automatic':False,
                'reason':'Архитектура не поддерживает локальный контейнер.','evidence':[]}
    fallback={'backend':'routeros','confidence':'unmeasured','automatic':False,
              'reason':'Нет подходящих замеров этой аппаратной платформы и нагрузки. RSC предложен как начальный вариант; производительность не подтверждена.','evidence':[]}
    signature=fingerprint(resource)
    if not all(signature.values()) or catalog.get('schema_version')!=1:
        return fallback
    choices=[]
    for profile in catalog.get('profiles',[]):
        if profile.get('platform')!=signature or profile.get('routeros_version')!=resource.get('version','').split()[0]:
            continue
        if not re.fullmatch(r'[a-f0-9]{64}',str(profile.get('report_sha256',''))) or profile.get('status')!='passed' or not profile.get('environment'):
            continue
        if profile.get('controller_source_sha256') != catalog.get('controller_source_sha256') or not catalog.get('controller_source_sha256'):
            continue
        limits=profile.get('workload',{})
        if any(type(limits.get(key)) is not int or limits[key]<value for key,value in workload(config).items()):
            continue
        for mode,measurement in profile.get('modes',{}).items():
            if mode not in ('routeros','container') or measurement.get('passed') is not True:
                continue
            cpu=measurement.get('cpu_mean_percent');peak=measurement.get('memory_peak_bytes')
            if type(cpu) not in (int,float) or not 0<=cpu<=100 or type(peak) is not int or peak<0:
                continue
            try: free=int(resource['free-memory'])
            except (KeyError,ValueError,TypeError): continue
            if peak>=free: continue
            choices.append((cpu,peak,mode,profile))
    if not choices: return fallback
    cpu,peak,mode,profile=min(choices,key=lambda row:(row[0],row[1],row[2]!='routeros'))
    return {'backend':mode,'confidence':'measured','automatic':False,
            'reason':'Режим предложен по успешному тесту совпадающей платформы и не меньшего числа WAN/политик/проб. Условия трафика приведены в отчёте; это не гарантия иной нагрузки.',
            'evidence':[{'report_sha256':profile['report_sha256'],'environment':profile['environment'],
                         'traffic':profile.get('traffic',{}),'cpu_mean_percent':cpu,'memory_peak_bytes':peak}]}


def storage_options(resource,capabilities,required_bytes=16*1024*1024):
    result=[]
    for disk in capabilities.get('disk',[]):
        name=disk.get('slot','')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,70}',name): continue
        if boolean(disk.get('disabled','false')) is not False or boolean(disk.get('mount-read-only','false')) is not False: continue
        if boolean(disk.get('mount-filesystem')) is not True or disk.get('fs') not in ('ext4','btrfs'): continue
        try: free=int(disk['free'])
        except (KeyError,TypeError,ValueError): continue
        result.append({'path':name+'/sdwan-container','free_bytes':free,'medium':'external',
                       'writable':True,'sufficient':free>=required_bytes,'recommended':free>=required_bytes})
    flash=any(row.get('name')=='flash' and row.get('type')=='directory' for row in capabilities.get('file',[]))
    try: free=int(resource['free-hdd-space'])
    except (KeyError,ValueError,TypeError): free=None
    result.append({'path':('flash/' if flash else '')+'sdwan-container','free_bytes':free,
                   'medium':'internal','writable':'file' not in capabilities.get('errors',{}),
                   'sufficient':free is not None and free>=required_bytes,'recommended':False})
    return result


def assess(resource,capabilities,config,catalog=None):
    checks=[];missing=[];features=[]
    def add(key,state,detail): checks.append({'key':key,'state':state,'detail':detail})
    version=resource.get('version','').split()[0] if resource.get('version') else ''
    add('routeros-version','ready' if version==VERSION else 'blocked','Целевая проверенная версия RouterOS '+VERSION+'; обнаружена '+(version or 'неизвестная'))
    packages={row.get('name'):row for row in capabilities.get('system/package',[])}
    required=['routeros']+(['container'] if config.get('controller_backend')=='container' else [])
    if config.get('controller_backend')=='container':
        add('container-architecture','ready' if resource.get('architecture-name') in ARCHITECTURES else 'blocked','Поддерживаемая архитектура контейнера')
    for name in required:
        row=packages.get(name)
        if not row:
            state='unknown' if 'system/package' in capabilities.get('errors',{}) else 'missing'
            if state=='missing': missing.append(name)
        elif row.get('version')!=version: state='blocked'
        elif boolean(row.get('disabled','false')) is not False or row.get('scheduled') not in (None,'','none'): state='blocked'
        else: state='ready'
        add('package:'+name,state,'Пакет '+name+' должен быть включён и совпадать с версией RouterOS')
    modes=capabilities.get('system/device-mode',[]);mode=modes[0] if modes else {}
    required_features=['scheduler','fetch']
    if config.get('controller_backend')=='container': required_features.append('container')
    if any(w.get('vpn_type')=='l2tp' for w in config.get('wans',[])): required_features.append('l2tp')
    for name in required_features:
        value=boolean(mode.get(name));state='ready' if value is True else 'blocked' if value is False else 'unknown'
        if value is False: features.append(name)
        add('feature:'+name,state,'Разрешение device-mode '+name+'; для изменения нужно штатное физическое подтверждение')
    if boolean(mode.get('flagged')) is True: add('device-flagged','blocked','RouterOS сообщает flagged=yes')
    options=storage_options(resource,capabilities)
    if config.get('controller_backend')=='container':
        from .container_config import settings
        settings_data=settings(config)
        try: memory_ready=int(resource['free-memory'])>=settings_data['memory_max_bytes']
        except (KeyError,TypeError,ValueError): memory_ready=None
        add('container-memory','ready' if memory_ready is True else 'blocked' if memory_ready is False else 'unknown','Свободная RAM должна покрывать выбранный лимит контейнера; производительность этим не подтверждается')
        selected=settings_data['storage'];root=next((row for row in options if selected==row['path'] or selected.startswith(row['path'].rsplit('/',1)[0]+'/') and row['medium']=='external'),None)
        if root is None:
            internal=options[-1]
            if internal['path'].startswith('flash/') and selected.startswith('flash/') or not internal['path'].startswith('flash/') and not any(selected.startswith(row['path'].split('/')[0]+'/') for row in options[:-1]):
                root=internal
        if root is None: add('container-storage','unknown','Выбранный каталог не сопоставлен с доступным накопителем')
        else: add('container-storage','ready' if root['writable'] and root['sufficient'] else 'blocked','Свободное место и доступность выбранного накопителя; резерв установки 16 MiB')
    return {'ready':all(row['state']=='ready' for row in checks),'checks':checks,'missing_packages':missing,
            'disabled_features':features,'storage_options':options,
            'recommendation':recommend(resource,config,catalog or {'schema_version':1,'profiles':[]})}
