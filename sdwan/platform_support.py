"""Read-only readiness and evidence-based mode selection for the GUI/SDK."""
import re

VERSION = '7.24.5'
ARCHITECTURES = {'x86':'amd64', 'x86_64':'amd64', 'arm':'arm', 'arm64':'arm64'}
RESOURCE_FIELDS = 'version,board-name,architecture-name,platform,cpu,cpu-count,cpu-frequency,total-memory,free-memory,total-hdd-space,free-hdd-space,uptime'
CAPABILITY_FIELDS = {
    'system/package':'.id,name,version,disabled,scheduled',
    'system/device-mode':'mode,flagged,scheduler,fetch,container,l2tp,ipsec,attempt-count',
    'disk':'.id,slot,type,fs,size,free,disabled,mount-point,mounted,mount-filesystem,mount-read-only,swap',
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


def storage_path(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]{0,190}',value):return ''
    return value if all(part not in ('','.','..') for part in value.split('/')) else ''


def mount_point(disk):
    # An explicitly empty mount point must not become a directory on internal storage.
    return storage_path(disk.get('mount-point',disk.get('slot','')))


def disk_readiness(disk,capabilities):
    name=mount_point(disk)
    if not name:return 'unknown','Не определена точка монтирования выбранного накопителя',None
    if boolean(disk.get('disabled','false')) is not False:
        return 'blocked','Накопитель '+name+' выключен или его доступность неизвестна',None
    if boolean(disk.get('mount-read-only','false')) is not False:
        return 'blocked','Накопитель '+name+' доступен только для чтения или режим записи неизвестен',None
    if boolean(disk.get('mount-filesystem')) is False or boolean(disk.get('mounted')) is False:
        return 'blocked','Накопитель '+name+' не смонтирован',None
    mounted=boolean(disk.get('mounted'))
    if mounted is None:
        # Older API projections can omit the M flag; /file still proves the mount.
        mounted=any(row.get('name')==name and row.get('type')=='disk' for row in capabilities.get('file',[]))
    if not mounted:return 'unknown','Монтирование накопителя '+name+' не подтверждено',None
    if disk.get('fs') not in ('ext4','btrfs'):
        return 'blocked','Для контейнера нужен ext4/btrfs; файловая система '+name+' не подходит или неизвестна',None
    try:free=int(disk['free'])
    except (KeyError,TypeError,ValueError):return 'unknown','Свободное место на '+name+' неизвестно',None
    if free<0:return 'unknown','Неверное значение свободного места на '+name,None
    return 'ready','Накопитель '+name+' смонтирован и доступен для записи',free


def storage_options(resource,capabilities,required_bytes=16*1024*1024):
    result=[]
    if not any(path in capabilities.get('errors',{}) for path in ('disk','file')):
        for disk in capabilities.get('disk',[]):
            state,_,free=disk_readiness(disk,capabilities)
            if state!='ready':continue
            name=mount_point(disk)
            if not storage_path(name+'/sdwan-container'):continue
            result.append({'path':name+'/sdwan-container','free_bytes':free,'medium':'external',
                           'writable':True,'sufficient':free>=required_bytes,'recommended':free>=required_bytes})
    flash=any(row.get('name')=='flash' and row.get('type')=='directory' for row in capabilities.get('file',[]))
    try: free=int(resource['free-hdd-space'])
    except (KeyError,ValueError,TypeError): free=None
    result.append({'path':('flash/' if flash else '')+'sdwan-container','free_bytes':free,
                   'medium':'internal','writable':'file' not in capabilities.get('errors',{}),
                   'sufficient':free is not None and free>=required_bytes,'recommended':False})
    return result


def storage_check(capabilities,selected,options):
    if not storage_path(selected):return 'blocked','Каталог контейнера должен быть относительным путём без пустых компонентов, . или ..'
    if any(path in capabilities.get('errors',{}) for path in ('disk','file')):
        return 'unknown','Не удалось прочитать накопители или файлы; расположение контейнера не подтверждено'
    def contains(root):return bool(root) and (selected==root or selected.startswith(root+'/'))
    matches=[disk for disk in capabilities.get('disk',[]) if contains(mount_point(disk))]
    if matches:
        longest=max(len(mount_point(disk)) for disk in matches)
        matches=[disk for disk in matches if len(mount_point(disk))==longest]
        if len(matches)!=1:return 'unknown','Точка монтирования выбранного накопителя неоднозначна'
        state,detail,free=disk_readiness(matches[0],capabilities)
        if state!='ready':return state,detail
        if free<16*1024*1024:return 'blocked','Недостаточно места на '+mount_point(matches[0])+'; резерв установки 16 MiB'
        return 'ready',detail+'; резерв установки 16 MiB'
    # A failed/renamed disk must never fall through to the internal free-space value.
    for disk in capabilities.get('disk',[]):
        if contains(storage_path(disk.get('slot',''))):
            return 'blocked','Имя слота не подтверждает путь контейнера; точка монтирования: '+(mount_point(disk) or 'неизвестна')
    if any(row.get('type')=='disk' and contains(storage_path(row.get('name',''))) for row in capabilities.get('file',[])):
        return 'unknown','Параметры выбранного диска недоступны; его место и режим записи не подтверждены'
    internal=options[-1]
    if internal['path'].startswith('flash/') and not selected.startswith('flash/'):
        return 'blocked','Выберите постоянное хранилище flash/ или подтверждённый внешний диск'
    if internal['free_bytes'] is None:return 'unknown','Свободное место внутреннего хранилища неизвестно'
    return ('ready' if internal['writable'] and internal['sufficient'] else 'blocked',
            'Внутреннее хранилище; резерв установки 16 MiB. Для контейнера предпочтителен внешний диск')


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
        state,detail=storage_check(capabilities,settings_data['storage'],options)
        add('container-storage',state,detail)
    return {'ready':all(row['state']=='ready' for row in checks),'checks':checks,'missing_packages':missing,
            'disabled_features':features,'storage_options':options,
            'recommendation':recommend(resource,config,catalog or {'schema_version':1,'profiles':[]})}
