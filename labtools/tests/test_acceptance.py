import copy,fcntl,hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from sdwan_lab.acceptance import attest,completed,match_attestation


def fixture():
    report={'pass':True,'status':'passed','kind':'release','failures':[],'required_seconds':172800,'elapsed_seconds':172801,'native_seconds':86400,'phase_samples':{'native':100,'container':100},'measured_started_utc':1,'container_started_utc':86401,'finished_utc':172802,'pid':99999999,'commit':'a'*40,'source_sha256':'b'*64,'image_id':'c'*64,'container_coverage_source_sha256':'d'*64}
    data=json.dumps(report).encode();plan={'bindings':{'controller_source_sha256':'d'*64,'images':{'web':{'image_config_sha256':'c'*64}},'native_sources':{'controller.rsc':'e'*64}}}
    proof={'schema_version':1,'ready':True,'soak_report_sha256':hashlib.sha256(data).hexdigest(),'process_exited':True,'locks_released':True,'restoration_verified':True,'coverage_verified':True,'frozen_source_verified':True,'native_sources':{'controller.rsc':'e'*64},**{key:report[key] for key in ['commit','source_sha256','image_id','container_coverage_source_sha256','pid']}}
    return report,data,proof,plan

class AcceptanceTests(unittest.TestCase):
    def test_two_full_phases_and_finite_completed_timeline_are_required(self):
        report,_,_,_=fixture();completed(report)
        for change in [{'native_seconds':86399},{'native_seconds':100000},{'elapsed_seconds':float('nan')},{'required_seconds':172799},{'pid':True},{'finished_utc':None},{'failures':None},{'phase_samples':{'native':True,'container':100}}]:
            with self.subTest(change=change),self.assertRaises(ValueError):completed(dict(report,**change))
    def test_proof_binds_exact_report_native_runtime_and_covered_image(self):
        _,data,proof,plan=fixture();self.assertTrue(match_attestation(proof,data,plan))
        for key,value in [('restoration_verified',False),('process_exited',False),('coverage_verified',False),('soak_report_sha256','f'*64),('image_id','f'*64),('native_sources',{'controller.rsc':'f'*64})]:
            with self.subTest(key=key),self.assertRaises(ValueError):match_attestation(dict(proof,**{key:value}),data,plan)
        changed=copy.deepcopy(plan);changed['bindings']['native_sources']['controller.rsc']='0'*64
        with self.assertRaisesRegex(ValueError,'Native runtime'):match_attestation(proof,data,changed)
    def test_running_soak_is_rejected_before_reading_source_or_coverage(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);file=root/'running.json';file.write_text('{"status":"running"}')
            with self.assertRaisesRegex(ValueError,'Full original48h'):attest(file,root/'absent-repo',root/'absent-coverage')

    def test_attest_verifies_real_git_manifest_without_writing_frozen_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source';source.mkdir();(source/'native').mkdir();(source/'tools').mkdir()
            (source/'native/controller.rsc').write_text(':put "fixture"\n')
            (source/'tools/container_checks.py').write_text('def source_digest(root): return "'+'d'*64+'"\n')
            def git(*args):return subprocess.check_output(['git',*args],cwd=source,stderr=subprocess.DEVNULL).decode().strip()
            git('init');git('add','.');git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','Synthetic acceptance fixture')
            report,_,_,_=fixture();report['commit']=git('rev-parse','HEAD')
            manifest={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in git('ls-files').splitlines()}
            report['source_sha256']=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
            report_file=root/'network-soak.json';report_file.write_text(json.dumps(report))
            (root/'network-soak-before.json').write_text(json.dumps({'status':'restored','pid':report['pid']}))
            for name in ('network-soak.lock','lab.lock'):(root/name).touch()
            coverage=root/'coverage.json';coverage.write_text(json.dumps({'pass':True,'source_sha256':'d'*64}))
            proof=attest(report_file,source,coverage)
            self.assertTrue(proof['ready']);self.assertEqual(proof['native_sources'],{'controller.rsc':manifest['native/controller.rsc']})
            self.assertEqual(git('status','--porcelain'),'');self.assertFalse(list(source.rglob('__pycache__')))
            with (root/'lab.lock').open('rb') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with self.assertRaisesRegex(ValueError,'locks are busy'):attest(report_file,source,coverage)
            (source/'native/controller.rsc').write_text('changed')
            with self.assertRaisesRegex(ValueError,'worktree changed'):attest(report_file,source,coverage)
