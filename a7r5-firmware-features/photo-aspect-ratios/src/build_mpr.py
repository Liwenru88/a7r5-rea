"""为锁定的原厂 libmpr 添加自定义比例的 JPEG 读侧兼容。"""

import io
import struct

from elftools.elf.elffile import ELFFile

from build_cp import HERE, PatchSet, digest
from patches import arm64_b
from link_helpers import compile_helpers


STOCK = 'ba1aa289a142c2d0b41d0864a57a0d72a2c796de89c5caf215ebaf124143e9af'
JPEG_EXIT = 0x270ddc
RX_END = 0x2e82a4
CODE = 0x2e82a8
RW_OFFSET = 0x2e83a8


def build_mpr(raw, work):
    if digest(raw) != STOCK:
        raise ValueError('libmpr 原厂前像不符')
    source = ELFFile(io.BytesIO(raw))
    rx, rw, *_ = source.iter_segments()
    if (source['e_phoff'], rx['p_type'], rx['p_flags'], rx['p_offset'], rx['p_vaddr'],
        rx['p_filesz'], rx['p_memsz'], rw['p_offset']) != (64, 'PT_LOAD', 5, 0, 0, RX_END, RX_END, RW_OFFSET):
        raise ValueError('libmpr 原厂加载段不符')
    loads = [s for s in source.iter_segments() if s['p_type'] == 'PT_LOAD']
    align = lambda n: (n + 65535) & ~65535
    rx = align(max(s['p_vaddr'] + s['p_memsz'] for s in loads))
    rxfile = align(len(raw))
    externals = dict(aspect_mpr_native_aux_body=0x267180, aspect_mpr_native_thumb=0x267194,
        aspect_mpr_native_scn=0x2671d0, aspect_mpr_native_raw_metadata_body=0x26c7f0,
        aspect_mpr_native_raw_metadata_error=0x26cc10, aspect_mpr_native_tag=0x26f050,
        aspect_mpr_native_jpeg_size=0x274b44, aspect_mpr_native_jpeg_vtable=0x2fe800,
        aspect_mpr_native_cammeta=0x273bbc)
    code, symbols, link = compile_helpers(work / 'metadata',
        ['mpr_metadata.S', 'mpr_raw_metadata.c', 'mpr_jpeg_metadata.c'], rx, externals, prefix=bytes(512))
    patches = PatchSet(raw)
    for at, before, name, call in (
        (0x26717c, 'a16340b9', 'aspect_mpr_heif_aux_entry', False),
        (0x26c7ec, '41030a8b', 'aspect_mpr_raw_metadata_entry', False),
        (0x274320, '27feff97', 'aspect_mpr_jpeg_metadata', True)):
        opcode = struct.unpack('<I', arm64_b(at, symbols[name]))[0] | (0x80000000 if call else 0)
        patches.put(at, bytes.fromhex(before), struct.pack('<I', opcode), name)
    original_headers = raw[source['e_phoff']:source['e_phoff'] + source['e_phnum'] * 56]
    header_bytes = (source['e_phnum'] + 2) * 56
    headers = struct.pack('<II6Q', 6, 4, rxfile, rx, rx, header_bytes, header_bytes, 8)
    headers += original_headers + struct.pack('<II6Q', 1, 5, rxfile, rx, rx, len(code), len(code), 65536)
    if len(headers) > 512:
        raise ValueError('libmpr 独立段的程序头容量不足')
    code = headers + code[len(headers):]
    patches.put(32, struct.pack('<Q', source['e_phoff']), struct.pack('<Q', rxfile), 'mpr-program-headers')
    patches.put(56, struct.pack('<H', source['e_phnum']), struct.pack('<H', source['e_phnum'] + 2), 'mpr-header-count')
    result, proof = patches.finish()
    result += bytes(rxfile - len(result)) + code
    proof.update(target_sha256=digest(result), source_bytes=len(raw), target_bytes=len(result),
        symbols=symbols, RX=rx, rx_file=rxfile, mapped_PT_PHDR=True, metadata_link=link)
    final = ELFFile(io.BytesIO(result))
    for name in ('.rela.dyn', '.rela.plt', '.dynamic', '.dynsym', '.dynstr'):
        if final.get_section_by_name(name).data() != source.get_section_by_name(name).data():
            raise ValueError('libmpr 原厂动态表发生变化')
    return result, proof
