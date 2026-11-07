"""Release pins must describe the actual complete artifact set before upload."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('release_checksums_test',ROOT/'tools/release_checksums.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def fixture():
    report=[];images=[];assets={}
    for profile in ('base','web'):
        for arch in ('amd64','arm64','arm'):
            name='sdwan-controller-'+('web-' if profile=='web' else '')+('armv5' if arch=='arm' else arch)+'.tar.gz'
            data=('synthetic artifact '+name).encode();assets[name]=data
            row={'profile':profile,'architecture':arch,'variant':'v5' if arch=='arm' else None,
                 'version':'0.3.0','archive':'dist/container/'+name.removesuffix('.gz'),
                 'gzip_bytes':len(data),'gzip_sha256':hashlib.sha256(data).hexdigest(),
                 'image_config_sha256':format(len(report)+1,'064x'),'unit_coverage_source_sha256':'b'*64}
            report.append(row)
            images.append({'profile':profile,'architecture':arch,'filename':name,'bytes':len(data),
                           'sha256':row['gzip_sha256'],'image_config_sha256':row['image_config_sha256'],
                           'unit_coverage_source_sha256':row['unit_coverage_source_sha256'],
                           'url':'https://github.com/alphazulu/mikrotik-sd-wan/releases/download/v0.3.0/'+name})
    return report,{'schema_version':1,'release':'v0.3.0','images':images},assets


class ReleaseCatalogTests(unittest.TestCase):
    def test_exact_six_profiles_match_without_mutating_the_inputs(self):
        report,catalog,_=fixture();before=copy.deepcopy((report,catalog))
        release.validate_catalog(report,catalog,'0.3.0')
        self.assertEqual((report,catalog),before)

    def test_stale_hash_identity_source_size_or_filename_refuses_promotion(self):
        for field,value in [('sha256','c'*64),('image_config_sha256','c'*64),
                            ('unit_coverage_source_sha256','c'*64),('bytes',1),
                            ('filename','different.tar.gz')]:
            with self.subTest(field=field):
                report,catalog,_=fixture();catalog['images'][3][field]=value
                with self.assertRaisesRegex(ValueError,'differs'):release.validate_catalog(report,catalog,'0.3.0')

    def test_missing_duplicate_extra_and_unknown_rows_are_not_a_complete_set(self):
        for target in ('report','catalog'):
            for kind in ('missing','duplicate','extra','unknown','non-object'):
                with self.subTest(target=target,kind=kind):
                    report,catalog,_=fixture();rows=report if target=='report' else catalog['images']
                    if kind=='missing':rows.pop()
                    elif kind=='extra':rows.append(copy.deepcopy(rows[0]))
                    elif kind=='duplicate':rows[-1]=copy.deepcopy(rows[0])
                    elif kind=='unknown':rows[-1]['architecture']='mipsbe'
                    else:rows[-1]=None
                    with self.assertRaises(ValueError):release.validate_catalog(report,catalog,'0.3.0')

    def test_release_version_schema_and_arm_variant_must_match(self):
        for change in ('release','schema','package-version','mixed-build-version','arm-variant'):
            report,catalog,_=fixture();version='0.3.0'
            if change=='release':catalog['release']='v0.2.0'
            elif change=='schema':catalog['schema_version']=2
            elif change=='package-version':version='0.4.0'
            elif change=='mixed-build-version':report[0]['version']='0.2.0'
            else:report[2]['variant']='v7'
            with self.subTest(change=change),self.assertRaises(ValueError):release.validate_catalog(report,catalog,version)

    def test_download_url_cannot_point_to_another_repo_tag_or_archive(self):
        for suffix in ('?raw=1','#other','/another.tar.gz'):
            report,catalog,_=fixture();catalog['images'][0]['url']+=suffix
            with self.assertRaisesRegex(ValueError,'url'):release.validate_catalog(report,catalog,'0.3.0')
        for old,new in [('alphazulu/mikrotik-sd-wan','example/other'),('v0.3.0','v0.2.0')]:
            report,catalog,_=fixture();catalog['images'][0]['url']=catalog['images'][0]['url'].replace(old,new)
            with self.assertRaisesRegex(ValueError,'url'):release.validate_catalog(report,catalog,'0.3.0')

    def test_boolean_or_empty_archive_size_is_invalid(self):
        for value in (True,False,0,-1,'10'):
            report,catalog,_=fixture();catalog['images'][0]['bytes']=value
            with self.subTest(value=value),self.assertRaises(ValueError):release.validate_catalog(report,catalog,'0.3.0')

    def invoke(self,root,check=True):
        with patch.object(release,'ROOT',root),patch.object(sys,'argv',['release_checksums.py']+(['--check-catalog'] if check else [])),redirect_stdout(io.StringIO()):
            release.main()

    def project(self,root,catalog,report,assets):
        directory=root/'dist/container';directory.mkdir(parents=True)
        (root/'config').mkdir();(root/'config/container-images.json').write_text(json.dumps(catalog))
        (root/'container-controller').mkdir();(root/'container-controller/Cargo.toml').write_text('[package]\nversion = "0.3.0"\n')
        (directory/'build-report.json').write_text(json.dumps(report))
        for name,data in assets.items():(directory/name).write_bytes(data)
        return directory

    def test_cli_manifest_contains_only_six_verified_archives_and_the_report(self):
        report,catalog,assets=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=self.project(root,catalog,report,assets)
            (directory/'unreviewed.backup').write_bytes(b'private fixture bytes')
            self.invoke(root)
            rows=(directory/'SHA256SUMS').read_text().splitlines()
            self.assertEqual({line.split('  ')[1] for line in rows},set(assets)|{'build-report.json'})
            for line in rows:
                checksum,name=line.split('  ');self.assertEqual(checksum,hashlib.sha256((directory/name).read_bytes()).hexdigest())

    def test_cli_refuses_stale_catalog_before_writing_a_manifest(self):
        report,catalog,assets=fixture();catalog['images'][0]['sha256']='c'*64
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=self.project(root,catalog,report,assets)
            with self.assertRaises(ValueError):self.invoke(root)
            self.assertFalse((directory/'SHA256SUMS').exists())
            self.invoke(root,check=False)  # Local checksums do not claim to be CI release pins.
            self.assertTrue((directory/'SHA256SUMS').is_file())

    def test_cli_rejects_corrupted_archive_even_with_consistent_metadata(self):
        report,catalog,assets=fixture()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);directory=self.project(root,catalog,report,assets)
            (directory/next(iter(assets))).write_bytes(b'truncated')
            with self.assertRaises(AssertionError):self.invoke(root)
            self.assertFalse((directory/'SHA256SUMS').exists())


if __name__=='__main__':unittest.main()
