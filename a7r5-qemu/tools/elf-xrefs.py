"""定位 AArch64 ADRP/ADD 字符串引用与所属展开表函数。"""
import sys
import struct
from elftools.elf.elffile import ELFFile
from elftools.dwarf.callframe import FDE

with open(sys.argv[1], 'rb') as f:
    e = ELFFile(f)
    t = e.get_section_by_name('.text')
    data, base = t.data(), t['sh_addr']
    targets = {int(s, 0) for s in sys.argv[2:]}
    ranges = sorted((x['initial_location'], x['address_range']) for x in e.get_dwarf_info().EH_CFI_entries() if isinstance(x, FDE))
    import bisect
    starts = [a for a, _ in ranges]
    for off in range(0, len(data)-32, 4):
        w = struct.unpack_from('<I', data, off)[0]
        if w & 0x9f000000 != 0x90000000:
            continue
        imm = ((w >> 5) & 0x7ffff)*4 + ((w >> 29) & 3)
        if imm & 0x100000:
            imm -= 0x200000
        page = ((base+off) & ~4095) + imm*4096
        if not any((a & ~4095) == page for a in targets):
            continue
        for k in range(1, 8):
            v = struct.unpack_from('<I', data, off+k*4)[0]
            if v & 0xffc00000 == 0x91000000 and ((v >> 5) & 31) == (w & 31):
                target = page + ((v >> 10) & 0xfff)
                if target in targets:
                    pc = base + off
                    i = bisect.bisect_right(starts, pc)-1
                    a, n = ranges[i]
                    owner=f'{a:#x} size={n:#x}' if a<=pc<a+n else 'unavailable'
                    print(f'target={target:#x} xref={pc:#x} fde={owner}')
