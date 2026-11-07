#!/usr/bin/env python3
"""Publish or verify the exact reviewed asset set, preserving existing releases."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

NAMES = {f'sdwan-controller-{profile}{arch}.tar.gz'
         for profile in ('', 'web-') for arch in ('amd64', 'arm64', 'armv5')}
NAMES |= {'build-report.json', 'SHA256SUMS'}


def local_assets(directory, tag):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Require an exact version tag')
    if {path.name for path in directory.iterdir()} != NAMES:
        raise ValueError('Require exactly eight reviewed release files')
    hashes = {}
    for line in (directory / 'SHA256SUMS').read_text().splitlines():
        parts = line.split('  ')
        if len(parts) != 2 or not re.fullmatch('[0-9a-f]{64}', parts[0]) or parts[1] in hashes:
            raise ValueError('Invalid or duplicate checksum entry')
        hashes[parts[1]] = parts[0]
    if hashes.keys() != NAMES - {'SHA256SUMS'}:
        raise ValueError('Checksum manifest differs from the reviewed file set')
    for name, expected in hashes.items():
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError('Local release checksum differs: ' + name)
    report = json.loads((directory / 'build-report.json').read_text())
    if not isinstance(report, list) or len(report) != 6 or any(row.get('version') != tag[1:] for row in report):
        raise ValueError('Build report differs from the release tag')
    return {name: (hashlib.sha256((directory / name).read_bytes()).hexdigest(),
                   (directory / name).stat().st_size) for name in NAMES}


def gh(args):
    return subprocess.run(['gh', *args], text=True, capture_output=True)


def view(repository, tag, run):
    result = run(['api', 'repos/' + repository + '/releases/tags/' + tag])
    if result.returncode == 0:
        return json.loads(result.stdout)
    if '(HTTP 404)' in result.stderr:
        return None
    raise RuntimeError('Cannot inspect release; no publication attempted')


def publish(directory, repository, tag, run=gh):
    expected = local_assets(directory, tag)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('Invalid repository')
    existing = view(repository, tag, run)
    created = existing is None
    if created:
        # If another publisher wins this race, verify its result below.
        run(['release', 'create', tag, '--repo', repository, '--verify-tag',
             '--title', tag, '--generate-notes', *[str(directory / name) for name in sorted(NAMES)]])
        existing = view(repository, tag, run)
    if existing is None or existing.get('draft') or existing.get('tag_name') != tag:
        raise RuntimeError('Published release is missing, still a draft or has a different tag')
    assets = existing.get('assets', [])
    if len(assets) != 8 or {row['name'] for row in assets} != NAMES:
        raise ValueError('Existing release asset set differs; nothing overwritten')
    if any(row['size'] != expected[row['name']][1] for row in assets):
        raise ValueError('Existing release asset size differs; nothing overwritten')
    with tempfile.TemporaryDirectory(prefix='sdwan-release-') as folder:
        result = run(['release', 'download', tag, '--repo', repository, '--dir', folder])
        if result.returncode:
            raise RuntimeError('Cannot download release for verification')
        downloaded = Path(folder)
        if {path.name for path in downloaded.iterdir()} != NAMES:
            raise ValueError('Downloaded release asset set differs')
        for name, (digest, size) in expected.items():
            data = (downloaded / name).read_bytes()
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Downloaded release checksum differs: ' + name)
    return {'pass': True, 'action': 'created-or-concurrent' if created else 'verified-existing',
            'files_verified': 8, 'existing_notes_or_assets_overwritten': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.directory, args.repository, args.tag)))


if __name__ == '__main__':
    main()
