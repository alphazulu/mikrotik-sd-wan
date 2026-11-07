#!/usr/bin/env python3
"""Install pinned host-only coverage tooling; nothing is added to scratch images."""
import hashlib,io,os,platform,subprocess,tarfile,urllib.request
from pathlib import Path
from container_checks import ROOT,COV_VERSION
SHA256='b3f68e625481fed9b16444174f3fa5ebcdbde4a1878803a35eabe2dcefcdc41a'
def main():
 if platform.system()!='Linux' or platform.machine() not in ('x86_64','AMD64'):raise SystemExit('The pinned coverage runner requires a Linux amd64 host/WSL; release images still target all three architectures')
 env=os.environ.copy()
 for key,rel in {'CARGO_HOME':'runtime/toolchains/cargo','RUSTUP_HOME':'runtime/toolchains/rustup'}.items():env.setdefault(key,str(ROOT/rel))
 subprocess.run([str(Path(env['CARGO_HOME'])/'bin/rustup'),'component','add','llvm-tools-preview','rustfmt'],env=env,check=True)
 target=ROOT/f'runtime/toolchains/coverage/{COV_VERSION}/cargo-llvm-cov';target.parent.mkdir(parents=True,exist_ok=True)
 url=f'https://github.com/taiki-e/cargo-llvm-cov/releases/download/v{COV_VERSION}/cargo-llvm-cov-x86_64-unknown-linux-gnu.tar.gz'
 data=urllib.request.urlopen(url,timeout=60).read()
 if hashlib.sha256(data).hexdigest()!=SHA256:raise ValueError('Pinned coverage archive checksum mismatch')
 with tarfile.open(fileobj=io.BytesIO(data)) as archive:
  member=next(m for m in archive.getmembers() if Path(m.name).name=='cargo-llvm-cov' and m.isfile());binary=archive.extractfile(member).read()
 target.write_bytes(binary);target.chmod(0o755);print(target)
if __name__=='__main__':main()
