"""只重建、逐字节比对目标ELF；不执行产物、不访问设备或网络。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
PACKAGE=HERE if (HERE/'config.json').exists() else HERE/'packages/ram-key-install-20261021-01'
WORK=next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())


def main():
    materials=PACKAGE/'materials';sources=PACKAGE/'rebuild-sources'
    libc=WORK/'a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if digest(libc)!='f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9':raise ValueError('目标libc变化')
    common=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu','--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
            '-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-O2','-Wall','-Wextra','-Werror',
            '-Wl,--no-undefined','-Wl,-z,max-page-size=65536','-I',str(materials)]
    result=dict(camera_io=False,ssh_started=False,executed_artifacts=False,rebuilt={})
    with tempfile.TemporaryDirectory() as tmp:
        for name,source,shared in [('ssh-service.arm64',sources/'ssh-service/launcher.c',False),
                                   ('boot-hook.so',sources/'ssh-service/boot_hook.c',True),
                                   ('root.arm64.so',sources/'src/root_once.c',True)]:
            output=Path(tmp)/name
            command=common+(['-fPIC','-shared'] if shared else ['-fPIE','-pie','-Wl,-e,_start','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',str(sources/'src/start.S')])
            if name=='root.arm64.so':command+=['-fvisibility=hidden']
            command+=[str(source),str(libc),'-o',str(output)]
            value=subprocess.run(command,capture_output=True,text=True,timeout=60)
            if value.returncode:raise RuntimeError('重建失败：'+name+': '+value.stderr)
            if output.read_bytes()!=(materials/name).read_bytes():raise ValueError('重建字节不同：'+name)
            result['rebuilt'][name]=dict(bytes=output.stat().st_size,sha256=digest(output),identical=True)
    result['status']='passed'
    (PACKAGE/'verification/rebuild.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
