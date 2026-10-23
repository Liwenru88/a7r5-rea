"""从固定源码构建 macOS QEMU，仅更新项目内原生模拟器。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

LAB=Path(__file__).resolve().parent.parent
REF=LAB/'source'
NATIVE=LAB/'build'


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    if sys.platform!='darwin':raise RuntimeError('仅用于 macOS')
    manifest=json.loads((REF/'qemu/manifest.json').read_text())
    archive=REF/'qemu/vendor/qemu-11.1.2.tar.xz'
    patch=REF/'qemu/qemu-sony-native.patch'
    assert sha(archive)==manifest['base_sha256']
    assert sha(patch)==manifest['patch_sha256']
    NATIVE.mkdir(exist_ok=True)
    source=NATIVE/'qemu-11.1.2'
    if not source.exists():
        def safe(member,dest):
            if member.issym() and member.name.endswith('/EmulatorPkg/Unix/Host/X11IncludeHack') and member.linkname=='/opt/X11/include':return None
            return tarfile.data_filter(member,dest)
        with tarfile.open(archive) as f:f.extractall(NATIVE,filter=safe)
        subprocess.run(['patch','--batch','-p1','-d',str(source),'-i',str(patch)],check=True)
        for name,want in manifest['dtc_source_files'].items():
            p=REF/'qemu/dtc'/name
            assert not p.is_symlink() and sha(p)==want,name
        shutil.copytree(REF/'qemu/dtc',source/'subprojects/dtc',dirs_exist_ok=True)
    for name,want in manifest['source_files'].items():assert sha(source/name)==want['after'],name
    build=NATIVE/'qemu-build';build.mkdir(exist_ok=True)
    env=os.environ.copy();env.update(PIP_NO_INDEX='1',PYTHONDONTWRITEBYTECODE='1')
    if not (build/'build.ninja').exists():
        subprocess.run([str(source/'configure'),'--target-list=aarch64-softmmu',
            '--without-default-features','--enable-tcg','--enable-pixman','--enable-fdt=internal',
            '--disable-opengl','--disable-download','--disable-docs','--disable-containers',
            '--disable-werror','--disable-tools','--python='+sys.executable],cwd=build,env=env,check=True)
    subprocess.run(['ninja','-j8','qemu-system-aarch64'],cwd=build,env=env,check=True)
    binary=build/'qemu-system-aarch64'
    subprocess.run(['file',str(binary)],check=True)
    subprocess.run([str(binary),'--version'],check=True)
    result={'platform':sys.platform,'source_sha256':sha(archive),'patch_sha256':sha(patch),
        'binary':str(binary.relative_to(LAB)),'binary_sha256':sha(binary),
        'guest_rebuilt':False}
    import fcntl
    from app_paths import open_vm_lock
    with open_vm_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        target=LAB/'bin/qemu-system-aarch64'
        temporary=target.with_suffix('.part')
        shutil.copy2(binary,temporary);temporary.replace(target)
        from runtime_manifest import update_manifest
        update_manifest({'binary':target})
    (NATIVE/'build-receipt.json').write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
