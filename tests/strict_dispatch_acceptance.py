"""Run the strict-dispatch contract on a disposable loopback-managed CHR."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sdwan.router import Router


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', required=True)
    parser.add_argument('--credentials', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.api_url).hostname != '127.0.0.1':
        parser.error('Use an isolated CHR through a loopback API forward')
    credentials = json.loads(args.credentials.read_text())
    router = Router(ROOT, args.api_url, credentials_data=credentials)
    name = 'strict-dispatch-contract'
    result = {'pass': False, 'cases': [], 'cleanup_errors': []}
    created = []
    files = []
    try:
        resource = router.call('system/resource')
        if (router.call('system/identity')['name'] != 'sdwan-strict-contract'
                or 'CHR' not in resource.get('board-name', '')
                or resource.get('version', '').split()[0] != '7.24.5'
                or router.call('system/script')
                or router.call('system/scheduler')
                or router.call('tool/netwatch')):
            raise ValueError('Requires a fresh disposable CHR 7.24.5 named sdwan-strict-contract')
        result['resource'] = resource
        result['sha256'] = {}
        payloads = [(local, remote, local.read_text()) for local, remote in [
            (ROOT / 'native/sdwan-config-state.rsc', 'contract-state.rsc'),
            (ROOT / 'native/sdwan-links.rsc', 'contract-links.rsc'),
            (ROOT / 'tests/strict_dispatch_acceptance.rsc', 'contract-tests.rsc'),
        ]]
        controller = ROOT / 'native/sdwan-controller.rsc'
        prelude = controller.read_text().split(':global sdwanStatusJSON', 1)[0]
        prelude += (':global sdwanContractControllerRuns; :set sdwanContractControllerRuns '
                    '($sdwanContractControllerRuns + 1); :delay 5s\n')
        payloads.append((controller, 'contract-controller.rsc', prelude))
        for local, remote, text in payloads:
            if router.file_entry(remote):
                raise ValueError('Contract file already exists: ' + remote)
            result['sha256'][local.name] = hashlib.sha256(local.read_bytes()).hexdigest()
            router.upload(remote, text)
            files.append(remote)
        source = '''
:global sdwanStrictContractStarted
:if ($sdwanStrictContractStarted = true) do={ :return "" }
:set sdwanStrictContractStarted true
:global sdwanStrictDispatchContractFailure
:onerror failure in={
    /import file-name=contract-state.rsc
    /import file-name=contract-links.rsc
    /import file-name=contract-tests.rsc
} do={ :set sdwanStrictDispatchContractFailure $failure }
'''
        for menu, values in [
            ('system/script', {'source': source}),
            ('system/scheduler', {'interval': '1s', 'on-event': '/system/script/run ' + name}),
        ]:
            identifier = router.call(menu + '/add', dict(
                values, name=name, policy='read,write,policy,test,sensitive'), 'POST')['ret']
            created.append((menu, identifier))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            rows = router.call('system/script/environment/print', {
                '.query': ['name=sdwanStrictDispatchContractJSON',
                           'name=sdwanStrictDispatchContractFailure', '#|'],
                '.proplist': 'name,value'}, 'POST')
            values = {x['name']: x.get('value', '') for x in rows}
            if values.get('sdwanStrictDispatchContractFailure'):
                raise RuntimeError(values['sdwanStrictDispatchContractFailure'])
            if values.get('sdwanStrictDispatchContractJSON'):
                result['cases'] = json.loads(values['sdwanStrictDispatchContractJSON'])
                result['pass'] = bool(result['cases']) and all(x['pass'] for x in result['cases'])
                break
            time.sleep(.2)
        else:
            raise TimeoutError('Contract did not finish')
    except Exception as error:
        result['error'] = str(error)
    finally:
        # Only after the fresh-router guard can these exact names belong to us.
        if created:
            names = {name, 'sdwan-controller', 'strict-contract-old-timer',
                     'strict-contract-postcommit-timeout', 'sdwan-strict-worker-0-extra',
                     'sdwan-strict-dispatch', 'sdwan-strict-worker-0',
                     'sdwan-strict-worker-1', 'sdwan-strict-timeout-0',
                     'sdwan-strict-timeout-1'}
            try:
                for menu, identifier in reversed(created):
                    router.call(menu + '/' + identifier, method='DELETE')
                pattern = r'/script:(' + '|'.join(re.escape(x) for x in names) + r')(/|$)'
                for job in router.call('system/script/job'):
                    if re.search(pattern, job.get('trace', '')):
                        try:
                            router.call('system/script/job/' + job['.id'], method='DELETE')
                        except RuntimeError:
                            if any(x['.id'] == job['.id'] for x in router.call('system/script/job')):
                                raise
                for row in router.call('system/script'):
                    if row['name'] in names:
                        router.call('system/script/' + row['.id'], method='DELETE')
                for row in router.call('tool/netwatch'):
                    if row.get('comment', '').startswith('sdwan:v1:probe:wan1:'):
                        router.call('tool/netwatch/' + row['.id'], method='DELETE')
            except Exception as error:
                result['cleanup_errors'].append(str(error))
        for filename in files:
            try:
                row = router.file_entry(filename)
                if row:
                    router.call('file/' + row['.id'], method='DELETE')
            except Exception as error:
                result['cleanup_errors'].append(str(error))
        router.close()
        result['pass'] = result['pass'] and not result['cleanup_errors']
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'pass': result['pass'], 'cases': len(result['cases'])}))
    return 0 if result['pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
