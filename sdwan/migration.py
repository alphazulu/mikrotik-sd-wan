"""Host-side migration review; no rule adoption, disabling, or router writes."""
import json
from pathlib import Path

FIELDS=('.id','chain','action','comment','new-connection-mark','new-routing-mark',
        'connection-mark','src-address','dst-address','src-address-list',
        'dst-address-list','in-interface','out-interface','protocol','src-port',
        'dst-port','passthrough','jump-target','route-dst')
MANGLE_ACTIONS=('mark-connection','mark-routing','route')


def foreign_marks(rules):
    return [{key:row[key] for key in FIELDS if key in row} for row in rules
            if row.get('action') in MANGLE_ACTIONS
            and row.get('disabled') not in (True,'true','yes','1')
            and not str(row.get('comment','')).startswith('sdwan:v1:')]


def review(inventory=None):
    inventory=inventory or {}
    rules=foreign_marks(inventory.get('ip/firewall/mangle',[]))
    unreadable='ip/firewall/mangle' in inventory.get('unreadable_paths',[])
    return {'schema_version':1,'captured_utc':inventory.get('captured_utc'),
            'router_identity':inventory.get('identity',{}).get('name',''),
            'status':'review_required' if rules else 'not_checked' if unreadable or not inventory else 'no_mark_conflicts',
            'blocking_rules':rules}


def text(report):
    lines=['Проверка перехода на SD-WAN','']
    rules=report.get('blocking_rules',[])
    if rules:
        lines+=['ЧЕРНОВИК. Установка заблокирована сторонними mangle-правилами.',
                'До применения перенесите нужную логику в SD-WAN и отключите или согласуйте перечисленные старые правила.',
                'Текущая версия требует отключения перечисленных сторонних маркировок; автоматического объединения правил нет.',
                'Не отключайте все mangle подряд: от них могут зависеть VPN, филиалы и QoS.',
                'MSS, DSCP и packet-mark сами по себе в этот список не включаются.',
                'Сохраните исходный export/backup и доступ для восстановления.',
                'После миграции заново получите настройки и выполните «План изменений».',
                'Конфигуратор не отключает эти правила автоматически.','',
                'Требуют разбора (ID относятся к моменту чтения; это не команды отключения):']
        for row in rules:
            fields='; '.join(key+'='+str(row[key]).replace('\n',' ').replace('\r',' ') for key in FIELDS if key in row)
            lines.append('- '+fields)
    elif report.get('status')=='no_mark_conflicts':
        lines+=['В прочитанном снимке активных сторонних connection/routing marks не найдено.',
                'Это не подтверждение готовности к установке. API preflight и native installer повторно проверяют текущее устройство.']
    else:
        lines+=['Нет проверенного снимка mangle. Получите настройки целевого устройства перед установкой.']
    lines+=['','Этот отчёт предназначен для ручного разбора. Старые правила не изменены.']
    return '\n'.join(lines)+'\n'


def write(report,directory,*,basename='MIGRATION-REVIEW'):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/(basename+'.json')).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    (directory/(basename+'.txt')).write_text(text(report),encoding='utf-8')


def read(config_path):
    path=Path(str(config_path)+'.migration.json')
    if not path.exists():return review()
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict) or value.get('schema_version')!=1 or not isinstance(value.get('blocking_rules'),list):
        raise ValueError('Некорректный отчёт миграции рядом с JSON; получите настройки устройства заново.')
    if any(not isinstance(row,dict) for row in value['blocking_rules']):raise ValueError('Некорректные записи отчёта миграции.')
    return value
