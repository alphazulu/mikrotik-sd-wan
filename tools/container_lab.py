#!/usr/bin/env python3
"""Separate CHR fabric for containers. Never reuses writable baseline disks."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT/'runtime/container-lab'
PROJECT = PROFILE/'project'
# Explicit host-port substitutions only. Guest service ports and metrics stay.
PORTS = {p: p+20000 for p in (
    18080,18081,18082,18083,18090,12222,12223,12224,12225,12230,
    18291,18292,18293,18294,18301,18728,24100,25100,
    22100,23100,23110,24099,28081,28082,28083)}

def prepare_profile():
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (ROOT/'lab.py',ROOT/'tools/probe_services.py')}
    manifest = PROFILE/'profile.json'
    if manifest.exists():
        assert json.loads(manifest.read_text())['source_hashes'] == hashes, 'Lab source changed; review profile before regeneration'
        return
    (PROJECT/'tools').mkdir(parents=True,exist_ok=True)
    (PROJECT/'images').mkdir(exist_ok=True)
    def transform(source):
        return re.sub(r'(?<![\d.])\d{5}(?![\d.])',
                      lambda match: str(PORTS.get(int(match[0]),int(match[0]))), source)
    source = transform((ROOT/'lab.py').read_text())
    assert "f'sdwan-{name}'" in source
    source = source.replace("f'sdwan-{name}'", "f'sdwan-container-{name}'")
    source = source.replace('name=sdwan-{name}', 'name=sdwan-container-{name}')
    (PROJECT/'lab.py').write_text(source)
    (PROJECT/'tools/probe_services.py').write_text(transform((ROOT/'tools/probe_services.py').read_text()))
    # Immutable downloaded raw/zip only; all qcow2 overlays are created locally.
    for name in ('chr-7.24.5.img','chr-7.24.5.img.zip'):
        backing=ROOT/'images'/name
        assert backing.is_file(), 'Missing downloaded CHR image'
        (PROJECT/'images'/name).symlink_to(backing)
    manifest.write_text(json.dumps({'source_hashes':hashes,'port_offset':20000,
                                   'project':str(PROJECT),'production_access':False},indent=2)+'\n')

def load():
    prepare_profile()
    spec=importlib.util.spec_from_file_location('sdwan_container_lab',PROJECT/'lab.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ROOT==PROJECT
    return module

if __name__=='__main__':
    prepare_profile()
    raise SystemExit(subprocess.call([sys.executable,str(PROJECT/'lab.py'),*sys.argv[1:]]))
