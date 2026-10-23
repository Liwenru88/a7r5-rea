"""在新临时目录重建共享库并比对，不修改封包或访问设备。"""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
from runner import HERE,check,sha

def main():
    op=check()
    with tempfile.TemporaryDirectory(prefix='a7r5-jit-rebuild-') as temp:
        root=Path(temp);shutil.copyfile(HERE/'materials/jit_config.h',root/'jit_config.h')
        cmd=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu','--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
             '-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-fPIC','-shared','-fvisibility=hidden','-O2',
             '-Wall','-Wextra','-Werror','-Wl,--no-undefined','-Wl,-z,max-page-size=65536','-Wl,-init,_init',
             '-I',str(root),str(HERE/'src/runner.c'),'-o',str(root/'libJit.so')]
        got=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        if got.returncode:raise ValueError(got.stderr)
        actual=sha(root/'libJit.so')
        if actual!=op['payload']['sha256']:raise ValueError('重建摘要不符，不替换原包')
        print(json.dumps(dict(rebuild_identical=True,sha256=actual,camera_io=False)))

if __name__=='__main__':main()
