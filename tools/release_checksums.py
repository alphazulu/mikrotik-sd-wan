#!/usr/bin/env python3
"""Write checksums only for the reviewed release asset set, never runtime data."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / 'dist/container'
    report = json.loads((directory / 'build-report.json').read_text())
    expected = {'sdwan-controller-'+profile+arch+'.tar.gz' for profile in ('','web-') for arch in ('amd64','arm64','armv5')}
    assert {Path(entry['archive']).with_suffix('.tar.gz').name for entry in report} == expected
    for entry in report:
        name = Path(entry['archive']).with_suffix('.tar.gz').name
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == entry['gzip_sha256']
    paths = [directory / name for name in sorted(expected)] + [directory / 'build-report.json']
    (directory / 'SHA256SUMS').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in paths))
    print('Release SHA256SUMS: six gzip archives and build-report.json')


if __name__ == '__main__':
    main()
