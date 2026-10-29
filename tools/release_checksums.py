#!/usr/bin/env python3
"""Write checksums only for the reviewed release asset set, never runtime data."""
from pathlib import Path
import argparse
import hashlib
import json
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def validate_catalog(report, catalog, version):
    """A release catalog must describe exactly the six archives being published."""
    expected={(profile,arch) for profile in ('base','web') for arch in ('amd64','arm64','arm')}
    if not isinstance(catalog,dict) or catalog.get('schema_version')!=1 or catalog.get('release')!='v'+version:
        raise ValueError('Image catalog schema/release differs from the package version')
    def indexed(rows, label):
        if not isinstance(rows,list) or len(rows)!=6:
            raise ValueError(label+': require exactly six image rows')
        result={}
        for row in rows:
            if not isinstance(row,dict) or not all(isinstance(row.get(k),str) for k in ('profile','architecture')):
                raise ValueError(label+': invalid image row')
            key=(row.get('profile'),row.get('architecture'))
            if key not in expected or key in result:
                raise ValueError(label+': unknown or duplicate architecture/profile')
            result[key]=row
        return result
    built=indexed(report,'Build report');pinned=indexed(catalog.get('images'),'Image catalog')
    for key,row in built.items():
        item=pinned[key]
        if row.get('version')!=version or row.get('variant')!=('v5' if key[1]=='arm' else None):
            raise ValueError('Build version/architecture variant differs from the release')
        name=Path(row['archive']).with_suffix('.tar.gz').name
        fields={'filename':name,'bytes':row['gzip_bytes'],'sha256':row['gzip_sha256'],
                'image_config_sha256':row['image_config_sha256'],
                'unit_coverage_source_sha256':row['unit_coverage_source_sha256'],
                'url':'https://github.com/alphazulu/mikrotik-sd-wan/releases/download/v'+version+'/'+name}
        if type(item.get('bytes')) is not int or item['bytes']<=0:
            raise ValueError('Image catalog has an invalid archive size')
        for field,value in fields.items():
            if item.get(field)!=value:
                raise ValueError('Image catalog differs from the build: '+key[0]+'/'+key[1]+' '+field)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-catalog',action='store_true',help='Require release pins to match this exact build (CI/release artifacts)')
    args=parser.parse_args()
    directory = ROOT / 'dist/container'
    report = json.loads((directory / 'build-report.json').read_text())
    if args.check_catalog:
        version=tomllib.loads((ROOT/'container-controller/Cargo.toml').read_text())['package']['version']
        validate_catalog(report,json.loads((ROOT/'config/container-images.json').read_text()),version)
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
