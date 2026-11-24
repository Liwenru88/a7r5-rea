"""复用已有严格 A64 链接器；不允许未解析符号或动态绝对指针。"""
import importlib.util
from pathlib import Path
import subprocess

from aspect_sizes import generate

HERE = Path(__file__).resolve().parent
LINKER = HERE.parents[1] / 'firmware-runtime/dependencies/native12-combined/upstream/firmware/r5/src/lib/strict_ap_link.py'


def compile_helpers(work, names, rx, externals, *, prefix=b''):
    work.mkdir(parents=True, exist_ok=True)
    generate(work)
    objects = []
    for name in names:
        obj = work / (name.replace('.', '_') + '.o')
        command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-none-elf', '-Oz',
                   '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fno-vectorize',
                   '-fno-slp-vectorize', '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
                   '-mgeneral-regs-only', '-Wall', '-Wextra', '-Werror', '-fstack-usage',
                   '-I', str(HERE), '-I', str(work), '-c', str(HERE / name), '-o', str(obj)]
        subprocess.run(command, check=True, capture_output=True)
        objects.append(obj)
    spec = importlib.util.spec_from_file_location('r5_aspect_strict_link', LINKER)
    linker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(linker)
    code, data, memory, symbols, relocations, layout = linker.link(objects, rx, rx + 65536, prefix, externals)
    if data or memory or len(code) > 65536:
        raise ValueError('画幅辅助段含可写数据或超过独立窗口')
    (work / 'rx.bin').write_bytes(code)
    return code, symbols, dict(relocations=relocations, layout=layout)
