#!/usr/bin/env python3
"""Check publication filenames, common secret formats and local Markdown links.

With a Git index, inspect the actual staged bytes. No credentials or matched
content are printed. This complements review; it is not a general secret oracle.
"""
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
import fnmatch
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
GENERATED = {'.git', '.venv', 'runtime', 'images', 'build', 'dist', '__pycache__', 'target'}
DENIED = (
    'all.rsc*', '*credentials*.json', '*secrets*.json', '*.backup', '*.pcap',
    '*.qcow2', '*.img', '*.npk', '*.png', '*.jpg', '*.jpeg', '*.key', '*.pem',
    '.env', '.env.*', 'handoff*.md', 'ospf-lte-review.md',
    '*.migration.json', '*.migration.txt', 'migration-review.json', 'migration-review.txt',
)
SECRETS = {
    'github-token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{25,})'),
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'aws-key': re.compile(rb'\bAKIA[A-Z0-9]{16}\b'),
    'telegram-token': re.compile(rb'\b\d{8,12}:[A-Za-z0-9_-]{30,}\b'),
    'device-export-header': re.compile(rb'(?mi)^#.*by RouterOS\s+\d'),
}


def contents():
    if (ROOT / '.git').exists():
        paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        result = {}
        for name in filter(None, paths):
            mode = subprocess.check_output(['git', 'ls-files', '-s', '--', name], cwd=ROOT).decode().split()[0]
            if mode not in ('100644', '100755'):
                raise ValueError('Only regular files are allowed: ' + name)
            result[name] = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
        return result
    result = {}
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if any(part in GENERATED for part in relative.parts) or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError('Symlinks are not publication inputs: ' + str(relative))
        if path.is_file():
            result[relative.as_posix()] = path.read_bytes()
    return result


def main():
    tree = contents()
    failures = []
    for name, data in tree.items():
        path = PurePosixPath(name)
        if any(part in GENERATED for part in path.parts):
            failures.append((name, 'generated/private directory'))
        if any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in DENIED):
            failures.append((name, 'private filename'))
        if name.startswith('config/discovered-') or name.startswith('config/local'):
            failures.append((name, 'device configuration snapshot'))
        if b'\0' in data or len(data) > 2 * 1024 * 1024:
            failures.append((name, 'binary/oversized file needs separate review'))
        for label, pattern in SECRETS.items():
            if pattern.search(data):
                failures.append((name, label))
        if path.suffix == '.md':
            for target in re.findall(r'\[[^\]\n]*\]\(([^)]+)\)', data.decode('utf-8')):
                target = target.strip('<>')
                if not target or target.startswith('#') or urlsplit(target).scheme:
                    continue
                target = unquote(target.split('#', 1)[0])
                resolved = (ROOT / path.parent / target).resolve()
                if not resolved.is_relative_to(ROOT) or resolved.relative_to(ROOT).as_posix() not in tree:
                    failures.append((name, 'missing local link: ' + target))
    result = {'pass': not failures, 'files': len(tree), 'findings': failures}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
