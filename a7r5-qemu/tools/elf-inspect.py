"""读取实验副本的 ELF 虚拟地址，不改动输入。"""
import argparse
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

p = argparse.ArgumentParser()
p.add_argument('elf')
p.add_argument('address', type=lambda x: int(x, 0))
p.add_argument('length', type=lambda x: int(x, 0), nargs='?', default=256)
p.add_argument('--string', action='store_true')
a = p.parse_args()
with Path(a.elf).open('rb') as f:
    e = ELFFile(f)
    s = next(s for s in e.iter_segments() if s['p_type'] == 'PT_LOAD' and
             s['p_vaddr'] <= a.address < a.address + a.length <= s['p_vaddr'] + s['p_filesz'])
    f.seek(s['p_offset'] + a.address - s['p_vaddr'])
    data = f.read(a.length)
if a.string:
    print(repr(data.split(b'\0')[0]))
else:
    for i in Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(data, a.address):
        print(f'{i.address:x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}')
