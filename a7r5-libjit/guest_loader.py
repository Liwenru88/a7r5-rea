"""从保留源码构建QEMU加载夹具；不依赖历史客体运行目录。"""
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent


def build(directory):
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('夹具输出不能经过符号链接')
    directory.mkdir(parents=True, exist_ok=False)
    sdk = HERE.parent / 'a7r5-qemu/sdk/lib'
    sources = [HERE/'src/guest-loader-start.S', HERE/'src/guest-loader.c']
    argv = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-linux-gnu',
            '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-nostdlib', '-ffreestanding',
            '-fno-stack-protector', '-O2', '-fPIE', '-pie', '-Wl,-e,_start',
            '-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1', '-Wl,-z,max-page-size=65536',
            *map(str, sources), str(sdk/'libc-2.25.so'), str(sdk/'libdl-2.25.so'),
            '-o', str(directory/'loader')]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    record = {'argv': argv, 'returncode': result.returncode, 'stderr': result.stderr,
              'sources': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
              'camera_io': False}
    if result.returncode == 0:
        record['sha256'] = hashlib.sha256((directory/'loader').read_bytes()).hexdigest()
    (directory/'build.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
    if result.returncode:
        raise ValueError('QEMU加载夹具构建失败：'+result.stderr)
    return directory/'loader'
