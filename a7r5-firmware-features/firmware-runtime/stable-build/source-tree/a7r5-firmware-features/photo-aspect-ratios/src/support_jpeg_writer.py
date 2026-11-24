#!/usr/bin/env python3
"""JPEG本张私有Exif与即时CamMeta缓存；执行完整原生add/header/get，无设备IO。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile
from unicorn import UC_HOOK_MEM_WRITE, UC_PROT_READ
from unicorn import arm64_const as A

HERE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(HERE), str(HERE / 'tests')]
from support_native_mpr import NativeMpr
from build_mpr import JPEG_EXIT as JPEG_METADATA_HOOK, STOCK as MPR_SHA256

OBJ, ADD, FIN, READ, CACHE = 0x50000000, 0x50020000, 0x50030000, 0x50040000, 0x50050000
GEN, MAIN, THM, SCN, DST = 0x52000000, 0x52010000, 0x52020000, 0x52030000, 0x53000000
CROPS = ((9504,5872),(6240,3856),(4752,2936),
         (9504,3976),(6240,2608),(4752,1992),
         (7920,6336),(5200,4160),(3968,3168),
         (9504,5136),(6240,3376),(4752,2568))
ORIGINALS = ((9504,6336),(6240,4160),(4752,3168))
sha = lambda data: hashlib.sha256(data).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def rebased_elf(raw, bias):
    """为既有原生模型配置第二实际装载偏移；代码字节不变，按ELF规则重定位。"""
    if not bias:
        return raw
    elf = ELFFile(io.BytesIO(raw)); result = bytearray(raw)
    for index, segment in enumerate(elf.iter_segments()):
        at = elf['e_phoff'] + index * elf['e_phentsize']
        for offset, key in ((16, 'p_vaddr'), (24, 'p_paddr')):
            struct.pack_into('<Q', result, at + offset, segment[key] + bias)
    symbols = elf.get_section_by_name('.dynsym')
    for index, symbol in enumerate(symbols.iter_symbols()):
        if symbol['st_value'] and symbol['st_shndx'] != 'SHN_ABS':
            struct.pack_into('<Q', result, symbols['sh_offset'] + index * symbols['sh_entsize'] + 8,
                             symbol['st_value'] + bias)
    for section in elf.iter_sections():
        if section['sh_type'] != 'SHT_RELA':
            continue
        for index, relocation in enumerate(section.iter_relocations()):
            at = section['sh_offset'] + index * section['sh_entsize']
            struct.pack_into('<Q', result, at, relocation['r_offset'] + bias)
            if relocation['r_info_type'] == 1027:
                struct.pack_into('<q', result, at + 16, relocation['r_addend'] + bias)
    return bytes(result)


class JpegWriter(NativeMpr):
    """真实JPEG ctor→add→header wrapper→完整writer→generic get缓存。"""
    def __init__(self, raw, bias=0):
        self.bias = bias
        self.raw_sha256 = sha(raw)
        self.observed_writes = []
        self.source = b''
        super().__init__(rebased_elf(raw, bias))
        # 原生Exif getter比较当前机型名；明确模型外部board数据，
        # 不借bias=0恰好映射的ELF零页读取NULL+8。
        self.u.mem_write(0x50060000, bytes(0x1000))
        self.u.mem_write(0x50060008, b'ILCE-7RM5\0')
        board_symbol = next(s['st_value'] for s in ELFFile(io.BytesIO(raw)).get_section_by_name('.dynsym').iter_symbols()
                            if s.name == '_ZN3mpr13gp_paramBoardE')
        self.u.mem_write(board_symbol + bias, struct.pack('<Q', 0x50060000))
        self.u.hook_add(UC_HOOK_MEM_WRITE, self.write)

    def write(self, u, access, address, size, value, data):
        self.observed_writes.append((address, size))

    def hook(self, u, pc, size, data):
        name = self.extrev.get(pc)
        if name == 'strnlen':
            return self.ret(len(bytes(u.mem_read(self.reg(0), self.reg(1))).split(b'\0', 1)[0]))
        if name == 'XML_ParserCreate':
            # 沿原生分配失败分支省略XMP；不替代TIFF/Exif/编码头或返回结果。
            self.calls[name] = self.calls.get(name, 0) + 1
            return self.ret(0)
        return super().hook(u, pc if name else pc - self.bias, size, data)

    def call(self, at, args):
        return super().call(at + self.bias, args)

    def ptr(self, address):
        return struct.unpack('<Q', self.u.mem_read(address, 8))[0]

    @staticmethod
    def sof(wh, prefix='SOI'):
        frame = bytes.fromhex('ffc0001108') + struct.pack('>HH', wh[1], wh[0]) + bytes.fromhex('03011100021100031100ffd9')
        if prefix == 'DQT':
            return bytes.fromhex('ffdb000300') + frame
        if prefix == 'PAD':
            return bytes(32) + bytes.fromhex('ffdb000300') + frame
        return bytes.fromhex('ffd8') + frame

    def area(self, at, pointer, length):
        self.u.mem_write(at, struct.pack('<III4xQQ16x', 0, 0, length, pointer, pointer))

    def prepare(self, wh, source_wh=ORIGINALS[0], prefix='SOI', jpeg=None, kind='JPEG', reuse=False):
        self.wh = tuple(wh)
        self.main_bytes = self.sof(wh, prefix) if jpeg is None else bytes(jpeg)
        u = self.u
        if not reuse:
            u.mem_write(OBJ, bytes(0x2000))
        else:
            require(struct.unpack('<I', u.mem_read(OBJ + 0x16f4, 4))[0] == 1, '连续add必须处于原生pending状态1')
        u.mem_write(ADD, bytes(0x1000)); u.mem_write(FIN, bytes(0x1000))
        source = bytearray(0x1000)
        struct.pack_into('<4I', source, 0x5c, *source_wh, *source_wh)
        self.source = bytes(source)
        u.mem_write(GEN, self.source); u.mem_write(DST, bytes(0x80000))
        for pointer in (MAIN, THM, SCN):
            u.mem_write(pointer, self.main_bytes + bytes(0x2000))
        u.mem_write(ADD, struct.pack('<Q', GEN))
        self.area(ADD + 0xe8, DST, 0x80000)
        self.area(ADD + 0x148, MAIN, len(self.main_bytes))
        self.area(ADD + 0x118, THM, 0x1000)
        self.area(ADD + 0x1a8, SCN, len(self.main_bytes))
        self.area(FIN, DST, 0x80000)
        self.area(FIN + 0x30, THM, 0x1000)
        self.area(FIN + 0x60, MAIN, len(self.main_bytes))
        self.area(FIN + 0x90, THM, 0x1000)
        self.area(FIN + 0xc0, SCN, len(self.main_bytes))
        constructor = {'JPEG': 0x27079c, 'RAW': 0x26ab74, 'HEIF': 0x26d6bc}[kind]
        if not reuse:
            self.call(constructor, [OBJ])
        self.add_before = bytes(u.mem_read(ADD, 0xa78))
        u.mem_protect(GEN, 0x1000, UC_PROT_READ)
        self.observed_writes.clear()
        guards = {index: 0xace00000 + index for index in range(19, 30)}
        for index, value in guards.items():
            u.reg_write(getattr(A, 'UC_ARM64_REG_X' + str(index)), value)
        vectors = {index: 0xabcd0000 + index for index in range(8, 16)}
        for index, value in vectors.items():
            u.reg_write(getattr(A, 'UC_ARM64_REG_Q' + str(index)), value)
        self.add_result = self.call(0x27420c, [OBJ, ADD])
        require(all((u.reg_read(getattr(A, 'UC_ARM64_REG_Q' + str(index))) & ((1 << 64) - 1)) == value
                    for index, value in vectors.items()), 'add改变ABI规定保留的SIMD低64位')
        require(all(u.reg_read(getattr(A, 'UC_ARM64_REG_X' + str(index))) == value
                    for index, value in guards.items()), 'add改变callee-saved寄存器')
        require(u.reg_read(A.UC_ARM64_REG_SP) == 0x701f0000, 'add没有恢复栈')
        require(self.add_result == 0, '原生add失败')
        self.add_writes = list(self.observed_writes)
        self.meta_after_add = bytes(u.mem_read(OBJ + 0xf10, 0x3f0))
        self.source_pointer = self.ptr(OBJ + 8)
        self.private_source = bytes(u.mem_read(OBJ + 0x13c0, 0xbc))
        require(bytes(u.mem_read(GEN, 0x1000)) == self.source, '共享GEN被改变')
        require(bytes(u.mem_read(ADD, 0xa78)) == self.add_before, '外部add_if被改变')
        return self.add_result

    def header(self):
        self.header_result = self.call(0x274730, [OBJ, FIN])
        require(bytes(self.u.mem_read(GEN, 0x1000)) == self.source, 'header污染共享GEN')
        require(bytes(self.u.mem_read(ADD, 0xa78)) == self.add_before, 'header污染外部add_if')
        return self.header_result

    def values(self):
        app = self.ptr(OBJ + 0x1798)
        exif = self.ptr(app + 0x48)
        result = []
        for tag in (0xa002, 0xa003):
            ref = self.call(0x26f050, [exif, tag])
            require(ref != 0, '原生Exif缺少尺寸字段')
            entry, value = struct.unpack('<QQ', self.u.mem_read(ref, 16))
            require(struct.unpack('<HI', self.u.mem_read(entry + 2, 6)) == (4, 1), 'Exif字段不是LONG×1')
            result.append(struct.unpack('<I', self.u.mem_read(value, 4))[0])
        return tuple(result)

    def cache(self):
        self.u.mem_write(READ, bytes(0x400)); self.u.mem_write(CACHE, bytes(0x1000))
        self.u.mem_write(READ + 8, struct.pack('<Q', CACHE))
        require(self.call(0x274548, [OBJ, READ]) == 0, '原生generic get失败')
        meta = bytes(self.u.mem_read(CACHE, 0x3f0))
        require(meta == bytes(self.u.mem_read(OBJ + 0xf10, 0x3f0)), 'generic get没有完整复制本张缓存')
        return meta

    def native_meta(self):
        self.u.mem_write(READ, bytes(0x400)); self.u.mem_write(CACHE, bytes(0x1000))
        self.u.mem_write(READ + 8, struct.pack('<Q', CACHE))
        require(self.call(0x270c48, [OBJ, READ, 2]) == 0, '完整JPEG getter失败')
        return bytes(self.u.mem_read(CACHE, 0x3f0))

    def native_header(self):
        prefix = bytes(self.u.mem_read(DST, 6))
        require(prefix[:4] == bytes.fromhex('ffd8ffe1'), '原生Exif header未序列化到本张输出')
        length = 4 + int.from_bytes(prefix[4:6], 'big')
        require(10 < length < 0x80000, '原生APP1长度越界')
        body = self.main_bytes[2:] if self.main_bytes[:2] == bytes.fromhex('ffd8') else self.main_bytes
        return bytes(self.u.mem_read(DST, length)) + body


def at(raw, address, length):
    for segment in ELFFile(io.BytesIO(raw)).iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= address < segment['p_vaddr'] + segment['p_filesz']:
            offset = segment['p_offset'] + address - segment['p_vaddr']
            return raw[offset:offset + length]
    raise ValueError('MPR地址未映射')


def geometry(meta):
    return (meta[0], *struct.unpack_from('<II', meta, 4), meta[0xc], struct.unpack_from('<I', meta, 0x10)[0])


