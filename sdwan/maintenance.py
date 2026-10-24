"""Infrequent deployment maintenance; no polling or periodic flash writes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from .deployment import read_state

TOKEN = r'[0-9a-f]{24}'
OWNED = re.compile(r'^(?:flash/)?sdwan-(?:txn-('+TOKEN+r')\.json|before-('+TOKEN+r')\.backup|(?:infra-)?prev-('+TOKEN+r')-\d+)$')
JOURNAL = re.compile(r'^(?:flash/)?sdwan-txn-('+TOKEN+r')\.json$')
TERMINAL = {'committed', 'rolled-back', 'preparation-failed'}


def _one(value):
    return value[0] if isinstance(value, list) else value


def _token(name):
    match = OWNED.fullmatch(name)
    return next((v for v in match.groups() if v), None) if match else None


def _date(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except (ValueError, TypeError, AttributeError):
        return None


def _valid_state(state, expected):
    return (isinstance(state, dict) and isinstance(state.get('token'), str)
            and re.fullmatch(TOKEN, state['token']) is not None
            and state.get('identity') == expected and isinstance(state.get('phase'), str)
            and type(state.get('backup_ready')) is bool
            and isinstance(state.get('previous'), dict)
            and all(isinstance(value, str) for value in state['previous'].values()))


def require_backup_space(router, package, reserve=1048576):
    """Check internal backup storage before uploading or mutating any file.

    It is a lower-bound preflight, not a prediction of compressed backup size.
    Native backup/save still verifies that the encrypted backup was created.
    """
    resource = _one(router.call('system/resource'))
    free = int(resource['free-hdd-space'])
    payload = sum(p.stat().st_size for p in Path(package).iterdir() if p.is_file())
    required = reserve + 2 * payload
    if free < required:
        raise ValueError(f'Not enough internal backup space: {free} bytes free; at least {required} required. Review completed archives before installation.')
    return {'free_bytes': free, 'minimum_required_bytes': required}


def backup_plan(router, expected, keep=3):
    if type(keep) is not int or not 1 <= keep <= 20:
        raise ValueError('Backup retention must be 1..20 completed transactions')
    if _one(router.call('system/identity'))['name'] != expected:
        raise ValueError('Router identity differs from expected identity')
    files = router.call('file/print', {'.proplist': '.id,name,type,size,last-modified,creation-time'}, 'POST')
    journals = [row for row in files if JOURNAL.fullmatch(row['name'])]
    states = {}
    groups = {}
    blocked = []
    for row in journals:
        token = JOURNAL.fullmatch(row['name'])[1]
        try:
            # Exact ID matters if flash and root contain distinct legacy copies.
            data = router.call('file/get', {'number': row['.id'], 'value-name': 'contents'}, 'POST')
            text = data['ret']
            if len(text) > 1048576:
                raise ValueError('oversized journal')
            state = json.loads(text)
            if not _valid_state(state, expected) or state['token'] != token:
                raise ValueError('unverified journal identity/token')
            if token in states and states[token] != state:
                raise ValueError('divergent flash/root journals')
            states[token] = state
            if state.get('phase') not in TERMINAL:
                blocked.append('Transaction is pending or requires recovery: ' + token)
            date = _date(state.get('created_utc')) or _date(row.get('last-modified', row.get('creation-time')))
            groups[token] = date
        except (ValueError, KeyError, TypeError):
            blocked.append('Unreadable or unverified transaction journal: ' + row['name'])
    current = read_state(router)
    if current is not None and not _valid_state(current, expected):
        blocked.append('Current journal has an invalid recovery schema')
        current = None
    if current and current.get('phase') not in TERMINAL:
        blocked.append('Current deployment is not safely completed')
    if current and current.get('token') not in states:
        blocked.append('Current journal is not in the verified inventory')
    file_names = {row['name'] for row in files}
    # Failed preparations/absent backups must not displace real recovery points.
    backed_up = {token for token, state in states.items()
                 if state.get('backup_ready') is True and
                 any(name in file_names for name in ('sdwan-before-'+token+'.backup', 'flash/sdwan-before-'+token+'.backup'))}
    known = sorted((token for token, date in groups.items() if date is not None and token in backed_up),
                   key=lambda token: (groups[token], token), reverse=True)
    protected = {token for token, date in groups.items() if date is None}
    protected.update(known[:keep])
    # Preserve all ties at the retention boundary; the router clock may have
    # low resolution. The current transaction is protected regardless of time.
    if len(known) >= keep:
        boundary = groups[known[keep - 1]]
        protected.update(token for token in known if groups[token] == boundary)
    if current:
        protected.add(current['token'])
    # A kept recovery manifest may refer to archives from another transaction.
    while True:
        previous = set(protected)
        for token in list(protected):
            for archive in states.get(token, {}).get('previous', {}).values():
                dependency = _token(archive) if isinstance(archive, str) else None
                if dependency:
                    protected.add(dependency)
        if previous == protected:
            break
    candidates = []
    for row in files:
        token = _token(row['name'])
        if token in states and token not in protected:
            candidates.append({'name': row['name'], 'id': row['.id'], 'size': int(row.get('size', 0)), 'token': token})
    # Keep the obsolete journal until its other files have been removed, so
    # an interrupted cleanup can be safely planned again without orphaning it.
    candidates.sort(key=lambda row: (row['token'], bool(JOURNAL.fullmatch(row['name'])), row['name']))
    return {'blocked': bool(blocked), 'reasons': blocked, 'keep': keep,
            'current_token': current.get('token') if current else None,
            'protected_tokens': sorted(protected), 'delete': candidates if not blocked else [],
            'reclaim_bytes': sum(row['size'] for row in candidates) if not blocked else 0,
            'policy': 'keep newest verified completed transactions plus current/dependencies/undated; leave orphan and unrelated files untouched'}


def prune_backups(router, expected, keep=3, *, execute=False):
    plan = backup_plan(router, expected, keep)
    if not execute:
        return plan
    if plan['blocked']:
        raise ValueError('Archive cleanup blocked: ' + '; '.join(plan['reasons']))
    removed = []
    removed_bytes = 0
    for row in plan['delete']:
        current = read_state(router)
        if current is not None and not _valid_state(current, expected):
            raise RuntimeError('Deployment changed during cleanup; invalid current journal')
        if (current.get('token') if current else None) != plan['current_token'] or (current and current.get('phase') not in TERMINAL):
            raise RuntimeError('Deployment changed during cleanup; remaining files were not removed')
        actual = router.file_records([row['name']])
        if not actual:
            continue
        if len(actual) != 1 or actual[0].get('.id') != row['id']:
            raise RuntimeError('Archive identity changed during cleanup')
        router.call('file/' + row['id'], method='DELETE')
        removed.append(row['name'])
        removed_bytes += row['size']
    return {'removed': removed, 'removed_files': len(removed), 'reclaim_bytes': removed_bytes,
            'current_token': plan['current_token'], 'protected_tokens': plan['protected_tokens']}
