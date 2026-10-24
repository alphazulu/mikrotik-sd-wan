#!/usr/bin/env python3
"""Inspect final scratch archives and Docker contexts, without running Docker."""
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('scratch_build',ROOT/'container-controller/build.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)

def main():
    images=json.loads((ROOT/'dist/container/build-report.json').read_text());checks=[]
    for entry in images:
        archive=ROOT/entry['archive'];data=archive.read_bytes()
        assert hashlib.sha256(data).hexdigest()==entry['tar_sha256']
        compressed=archive.with_suffix('.tar.gz').read_bytes()
        assert hashlib.sha256(compressed).hexdigest()==entry['gzip_sha256'] and gzip.decompress(compressed)==data
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            manifest=json.load(tar.extractfile('manifest.json'))[0]
            config_bytes=tar.extractfile(manifest['Config']).read();config=json.loads(config_bytes)
            assert hashlib.sha256(config_bytes).hexdigest()==entry['image_config_sha256']
            assert config['config']['User']=='65532:65532' and 'Env' not in config['config']
            assert config['architecture']==entry['architecture'] and config.get('variant')==entry['variant']
            assert len(manifest['Layers'])==1
            layer=tar.extractfile(manifest['Layers'][0]).read()
            assert config['rootfs']['diff_ids']==['sha256:'+hashlib.sha256(layer).hexdigest()]
            with tarfile.open(fileobj=io.BytesIO(layer)) as fs:
                files=fs.getmembers();assert len(files)==1 and files[0].name=='sdwan-controller' and files[0].isfile() and files[0].mode==0o555
                binary=fs.extractfile(files[0]).read()
        assert hashlib.sha256(binary).hexdigest()==entry['binary_sha256']
        build.static_elf(binary,{'amd64':62,'arm64':183,'arm':40}[entry['architecture']])
        context=ROOT/'dist/container'/('armv5' if entry['variant'] else entry['architecture'])
        assert (context/'sdwan-controller').read_bytes()==binary
        assert (context/'Dockerfile').read_text().splitlines()[0]=='FROM scratch'
        checks.append({'architecture':entry['architecture'],'variant':entry['variant'],'pass':True,
                       'single_binary_only':True,'static_elf':True,'config_sha256':entry['image_config_sha256']})
    assert len(checks)==3
    (ROOT/'runtime/container-artifact-validation.json').write_text(json.dumps({'pass':True,'checks':checks,'daemon_required':False},indent=2)+'\n')
    print(json.dumps({'pass':True,'architectures':len(checks),'single_layer':'scratch/static binary only'}))

if __name__=='__main__':main()
