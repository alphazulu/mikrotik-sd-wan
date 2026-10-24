#!/usr/bin/env python3
"""Build static Rust binaries and minimal Docker-save archives without a daemon."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tarfile
import tomllib

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {
    'amd64': ('x86_64-unknown-linux-musl', 62, None),
    'arm64': ('aarch64-unknown-linux-musl', 183, None),
    'armv5': ('armv5te-unknown-linux-musleabi', 40, 'v5'),
}

def static_elf(data: bytes, machine: int) -> None:
    if data[:4] != b'\x7fELF' or data[5] != 1:
        raise ValueError('Expected little-endian ELF')
    bits = data[4]
    if struct.unpack_from('<H', data, 18)[0] != machine:
        raise ValueError('ELF architecture mismatch')
    if bits == 2:
        offset = struct.unpack_from('<Q', data, 32)[0]
        stride, count = struct.unpack_from('<HH', data, 54)
    elif bits == 1:
        offset = struct.unpack_from('<I', data, 28)[0]
        stride, count = struct.unpack_from('<HH', data, 42)
    else:
        raise ValueError('Unsupported ELF class')
    for n in range(count):
        kind = struct.unpack_from('<I', data, offset + n * stride)[0]
        if kind in (2, 3):  # PT_DYNAMIC / PT_INTERP
            raise ValueError('Image binary must be fully static (no dynamic loader)')

def add(tar: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, 0
    info.uid, info.gid = 0, 0
    tar.addfile(info, io.BytesIO(data))

def packed(value: object) -> bytes:
    return json.dumps(value, separators=(',', ':'), sort_keys=True).encode()

def image(binary: bytes, architecture: str, variant: str | None, destination: Path, profile: str = 'base') -> dict:
    name='sdwan-controller'+('-web' if profile=='web' else '')
    version=tomllib.loads((ROOT/'container-controller/Cargo.toml').read_text())['package']['version']
    layer_io = io.BytesIO()
    with tarfile.open(fileobj=layer_io, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        add(tar, name, binary, 0o555)
    layer = layer_io.getvalue()
    diff_id = hashlib.sha256(layer).hexdigest()
    config = {'architecture': architecture, 'os': 'linux',
              'config': {'User': '65532:65532', 'WorkingDir': '/',
                         'Entrypoint': ['/'+name],
                         'Cmd': ['run', '/config/controller.json']},
              'rootfs': {'type': 'layers', 'diff_ids': ['sha256:' + diff_id]},
              'history': [{'created_by': 'COPY static binary; FROM scratch'}]}
    if variant:
        config['variant'] = variant
    config_bytes = packed(config)
    config_name = hashlib.sha256(config_bytes).hexdigest() + '.json'
    layer_name = diff_id + '/layer.tar'
    manifest = [{'Config': config_name,
                 'RepoTags': [name+':'+version], 'Layers': [layer_name]}]
    with tarfile.open(destination, 'w', format=tarfile.USTAR_FORMAT) as tar:
        add(tar, config_name, config_bytes)
        add(tar, layer_name, layer)
        add(tar, 'manifest.json', packed(manifest))
    archive = destination.read_bytes()
    compressed = gzip.compress(archive, compresslevel=9, mtime=0)
    destination.with_suffix('.tar.gz').write_bytes(compressed)
    return {'architecture': architecture, 'variant': variant, 'base': 'scratch','profile':profile,'version':version,
            'filesystem_entries': [name], 'binary_bytes': len(binary),
            'tar_bytes': len(archive), 'gzip_bytes': len(compressed),
            'binary_sha256': hashlib.sha256(binary).hexdigest(),
            'image_config_sha256': config_name.removesuffix('.json'),
            'tar_sha256': hashlib.sha256(archive).hexdigest(),
            'gzip_sha256': hashlib.sha256(compressed).hexdigest(),
            'archive': str(destination.relative_to(ROOT))}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--architectures', nargs='+', choices=TARGETS, default=list(TARGETS))
    parser.add_argument('--profiles',nargs='+',choices=['base','web'],default=['base','web'])
    args = parser.parse_args()
    env = os.environ.copy()
    for key,path in {'RUSTUP_HOME':'runtime/toolchains/rustup','CARGO_HOME':'runtime/toolchains/cargo',
                     'CARGO_TARGET_DIR':'runtime/container-build','RUSTC':'runtime/toolchains/cargo/bin/rustc'}.items():env.setdefault(key,str(ROOT/path))
    cargo=str(Path(env['CARGO_HOME'])/'bin/cargo')
    rustc = [env['RUSTC']]
    sysroot = Path(subprocess.check_output(rustc + ['--print', 'sysroot'], env=env, text=True).strip())
    linker = sysroot/'lib/rustlib/x86_64-unknown-linux-gnu/bin/rust-lld'
    env['RUSTFLAGS'] = '-C target-feature=+crt-static -C relocation-model=static -C linker=' + str(linker)
    output = ROOT/'dist/container'
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for profile,key in [(p,k) for p in args.profiles for k in args.architectures]:
        target, machine, variant = TARGETS[key]
        subprocess.run([cargo, 'build', '--locked',
                        '--release', '--target', target, '--manifest-path',
                        str(ROOT/'container-controller/Cargo.toml'), '-j1']+(['--features','web'] if profile=='web' else ['--no-default-features']), env=env, check=True)
        binary = (Path(env['CARGO_TARGET_DIR'])/target/'release/sdwan-router-controller').read_bytes()
        static_elf(binary, machine)
        architecture = 'arm' if variant else key
        name='sdwan-controller'+('-web' if profile=='web' else '')
        reports.append(image(binary, architecture, variant, output/f'{name}-{key}.tar',profile))
        context=output/(('web-' if profile=='web' else '')+key)
        context.mkdir(exist_ok=True)
        temporary=context/(name+'.tmp')
        temporary.write_bytes(binary);temporary.chmod(0o555);temporary.replace(context/name)
        (context/'Dockerfile').write_bytes((ROOT/'container-controller'/('Dockerfile.web' if profile=='web' else 'Dockerfile')).read_bytes())
        (context/'.dockerignore').write_text('*\n!Dockerfile\n!'+name+'\n')
        print(json.dumps(reports[-1]), flush=True)
        (output/'build-report.json').write_text(json.dumps(reports, indent=2)+'\n')

if __name__ == '__main__':
    main()
