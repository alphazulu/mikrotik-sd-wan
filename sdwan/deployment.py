"""Stage and observe a router-local deployment; rollback never depends on this process."""
from datetime import datetime,timezone
import json
from pathlib import Path
import secrets
import time

TERMINAL={'committed','rolled-back','preparation-failed','recovery-failed'}
REQUIRED={'read','write','policy','test','sensitive','reboot'}


def read_state(router,token=None):
    if token:return json.loads(router.read_file('sdwan-txn-'+token+'.json'))
    try:link=json.loads(router.read_file('sdwan-deploy-current.json'))
    except ValueError as error:
        if str(error).startswith('Router file not found:'):return None
        raise
    return json.loads(router.read_file(link['path']))


def check_permissions(router):
    users=router.call('user/print',{'.proplist':'name,group','.query':['name='+router.username]},'POST')
    if not users:raise ValueError('Cannot read the deployment user group')
    groups=router.call('user/group/print',{'.proplist':'name,policy','.query':['name='+users[0]['group']]},'POST')
    allowed=set(groups[0]['policy'].split(',')) if groups else set()
    missing=REQUIRED-allowed
    if missing:raise ValueError('Native recovery requires user policies: '+', '.join(sorted(missing)))
    state=read_state(router)
    if state and state.get('phase') not in TERMINAL:raise ValueError('A native deployment is already pending: '+state.get('phase','unknown'))
    try:
        safe=router.call('safe-mode')
        if isinstance(safe,list):safe=safe[0] if safe else {}
        if safe.get('enabled') in (True,'true','yes'):raise ValueError('Exit the existing Safe Mode session before native transactional deployment')
    except RuntimeError:pass  # Availability of the read-only menu varies by RouterOS.


def start(router,package,expected,*,revision='',default_policy='',operation='apply',timeout=120,allow_no_default=False):
    if type(allow_no_default) is not bool:raise ValueError('allow_no_default must be boolean')
    if not 30<=timeout<=600:raise ValueError('Deployment deadline must be 30..600 seconds')
    check_permissions(router)
    token=secrets.token_hex(12)
    # Bootstrap/worker/watchdog must be uploaded before the native bootstrap can
    # run. Preserve their PREVIOUS files first, including distinct flash/root
    # copies, so updating the recovery framework itself is reversible too.
    prefixes=list(dict.fromkeys((router.storage_prefix,'')))
    names=[prefix+name for name in ('sdwan-deployment.rsc','sdwan-deploy-worker.rsc','sdwan-deploy-watchdog.rsc') for prefix in prefixes]
    files={row['name']:row['.id'] for row in router.file_records(names)}
    old_infrastructure={}
    for name in ('sdwan-deployment.rsc','sdwan-deploy-worker.rsc','sdwan-deploy-watchdog.rsc'):
        for prefix in prefixes:
            original=prefix+name
            if original in files:
                data=router.call('file/get',{'number':files[original],'value-name':'contents'},'POST')
                if not isinstance(data,dict) or 'ret' not in data:raise RuntimeError('Cannot archive previous deployment framework file')
                old_infrastructure[original]=data['ret']
            else:old_infrastructure[original]=None
    from .maintenance import require_backup_space
    require_backup_space(router,package)
    request={'token':token,'password':secrets.token_urlsafe(40),'identity':expected,'operation':operation,'revision':revision,'default_policy':default_policy,'allow_no_default':allow_no_default,'timeout_seconds':timeout,'created_utc':datetime.now(timezone.utc).isoformat()}
    run=router.root/'runtime';run.mkdir(exist_ok=True)
    key=run/('recovery-'+token+'.json')
    key.write_text(json.dumps({'token':token,'identity':expected,'backup_password':request['password'],'backup_file':router.storage_prefix+'sdwan-before-'+token+'.backup'},indent=2)+'\n')
    key.chmod(0o600)
    infrastructure_manifest={}
    for index,(original,text) in enumerate(old_infrastructure.items()):
        archive=''
        if text is not None:
            archive=router.storage_prefix+'sdwan-infra-prev-'+token+'-'+str(index)
            router.upload(archive,text)
            if router.read_file(archive)!=text:raise RuntimeError('Previous deployment framework archive verification failed')
        infrastructure_manifest[original]=archive
    router.upload('sdwan-deploy-request.json',json.dumps(request,separators=(',',':')))
    for name in ('sdwan-deploy-worker.rsc','sdwan-deploy-watchdog.rsc'):
        router.upload(name,(Path(package)/name).read_text(encoding='utf-8'))
    bootstrap=Path(package)/'sdwan-deployment.rsc'
    router.upload(bootstrap.name,bootstrap.read_text(encoding='utf-8'))
    # Bootstrap only archives files/registers disabled worker and saves a backup.
    router.call('import',{'file-name':router.storage_prefix+bootstrap.name},'POST')
    state=read_state(router,token)
    if state.get('phase')!='prepared' or not state.get('backup_ready'):raise RuntimeError('Native encrypted backup preparation failed')
    previous=state.get('previous')
    if not isinstance(previous,dict) or len(previous)<10:raise RuntimeError('Previous package archive manifest is incomplete; payload was not uploaded')
    # While prepared, the watchdog only reads this journal until our unique arm
    # token is uploaded. Extend and verify the manifest BEFORE any payload/arm.
    previous.update(infrastructure_manifest)
    journal='sdwan-txn-'+token+'.json'
    router.upload(journal,json.dumps(state,separators=(',',':')))
    verified=read_state(router,token)
    if verified.get('phase')!='prepared' or verified.get('previous')!=previous:raise RuntimeError('Deployment framework recovery manifest was not sealed; payload was not uploaded')
    end=time.monotonic()+8
    while True:
        rows=router.call('system/script/environment/print',{'.proplist':'name,value','.query':['name=sdwanDeployHeartbeatJSON']},'POST')
        if rows and json.loads(rows[0]['value']).get('token')==token:break
        if time.monotonic()>end:raise RuntimeError('Native watchdog did not start; payload was not uploaded')
        time.sleep(.3)
    try:
        for path in Path(package).iterdir():
            if path.name=='sdwan-deployment.rsc' or not path.is_file():continue
            if path.name not in {'sdwan-config.json','sdwan-controller.rsc','sdwan-install.rsc','sdwan-rollback.rsc','sdwan-dataplane.rsc','sdwan-links.rsc','sdwan-overlay.rsc','sdwan-vpn.rsc'}:continue
            text=path.read_text(encoding='utf-8');router.upload(path.name,text)
            if router.read_file(path.name)!=text:raise RuntimeError('Uploaded payload verification failed: '+path.name)
        router.upload('sdwan-deploy-arm.json',json.dumps({'token':token}))
    except Exception:
        try:router.upload('sdwan-deploy-abort.json',json.dumps({'token':token}))
        except Exception:pass  # The already armed local deadline remains authoritative.
        raise
    return token


def wait(router,token,expected,*,timeout=120,confirm=True):
    end=time.monotonic()+timeout+120;ack=False;last_phase=None;last_error=None
    while time.monotonic()<end:
        try:
            state=read_state(router,token);phase=state.get('phase')
            if phase!=last_phase:
                print('Native deployment: '+str(phase),flush=True);last_phase=phase
            if phase=='committed':return {'token':token,'phase':phase,'backup_file':state['backup_name']+'.backup'}
            if phase in TERMINAL:raise RuntimeError('Native deployment '+str(phase)+': '+str(state.get('error','unknown failure')))
            if phase=='await-confirm' and confirm and not ack:
                fresh=router.fresh()
                try:
                    if fresh.call('system/identity')['name']!=expected:raise RuntimeError('Management endpoint identity changed')
                    ready=state['operation']=='rollback'
                    if not ready:
                        status=fresh.status()
                        selected=status.get('selected',{}).get(state.get('default_policy'))
                        explicitly_closed=state.get('allow_no_default') is True and status.get('default_admission_closed') is True
                        ready='error' not in status and status.get('revision')==state.get('revision') and (selected not in (None,'none') or explicitly_closed)
                        if status.get('backend')=='container':ready=ready and status.get('container',{}).get('active') is True
                    if ready:
                        fresh.upload('sdwan-deploy-ack.json',json.dumps({'token':token}));ack=True
                finally:fresh.close()
        except (OSError,ConnectionError,json.JSONDecodeError) as error:
            last_error=type(error).__name__;router.close()
        except ValueError as error:
            # During binary restore/reboot RouterOS may answer file/print
            # before the transaction file is visible again. Retry only this
            # exact journal within the existing deadline; never retry writes
            # or hide unrelated validation/identity errors.
            if str(error)!='Router file not found: sdwan-txn-'+token+'.json':raise
            last_error='transaction journal temporarily unavailable';router.close()
        time.sleep(.5)
    raise RuntimeError('Deployment status unavailable; native watchdog remains responsible for recovery. Last transport error: '+str(last_error))
