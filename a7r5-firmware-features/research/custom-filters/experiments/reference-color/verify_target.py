"""在AArch64执行独立参考算子；不加载或执行外部参考项目代码。"""
import argparse
import base64
import ctypes as c
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import time
import zlib

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC
from unicorn import arm64_const as reg

FEATURE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FEATURE))
from a7filters.reference_snapshot import load_edit_snapshot
sys.path.insert(0, str(FEATURE/'tests'))
from test_edit_reference import Matrix, Area, Chroma, ChromaSource, ChromaTables, YGamma
from test_edit_chain import Chain


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unpack(item):
    decoder = zlib.decompressobj()
    raw = decoder.decompress(base64.b64decode(item['zlib_base64'], validate=True), 256*1024+1)
    if (len(raw) != item['bytes'] or len(raw) > 256*1024 or not decoder.eof
            or decoder.unused_data or digest(raw) != item['sha256']):
        raise ValueError('参考向量大小或摘要不符')
    return raw


class Machine:
    def __init__(self, module):
        elf = ELFFile(io.BytesIO(module))
        if (len(module) > 128*1024 or elf['e_machine'] != 'EM_AARCH64'
                or elf['e_type'] != 'ET_EXEC' or not elf.little_endian
                or any(s['sh_type'] in ('SHT_REL', 'SHT_RELA') for s in elf.iter_sections())):
            raise ValueError('需要有界、无重定位的AArch64研究ELF')
        symbols = elf.get_section_by_name('.symtab')
        if symbols is None:
            raise ValueError('研究ELF缺少符号')
        self.symbols = {s.name: int(s['st_value']) for s in symbols.iter_symbols()
                        if s['st_shndx'] != 'SHN_UNDEF'}
        self.cpu = Uc(UC_ARCH_ARM64, 0)
        pages = {}
        for segment in elf.iter_segments():
            if segment['p_type'] != 'PT_LOAD':
                continue
            first, size, flags = segment['p_vaddr'], segment['p_memsz'], segment['p_flags']
            if flags not in (4, 5, 6) or not 0x10000 <= first < first+size < 0x10000000:
                raise ValueError('ELF代码范围或页权限无效')
            permission = UC_PROT_READ | (UC_PROT_WRITE if flags & 2 else 0) | (UC_PROT_EXEC if flags & 1 else 0)
            for page in range(first & ~4095, (first+size+4095) & ~4095, 4096):
                if page in pages:
                    raise ValueError('ELF各段不得共享映射页')
                pages[page] = permission
                self.cpu.mem_map(page, 4096, permission)
            self.cpu.mem_write(first, segment.data())
        self.cpu.mem_map(0x90000000, 0x100000, UC_PROT_READ | UC_PROT_WRITE)
        self.cpu.mem_map(0x90200000, 0x10000, UC_PROT_READ | UC_PROT_WRITE)
        self.cpu.mem_map(0x90300000, 4096, UC_PROT_READ | UC_PROT_EXEC)

    def call(self, symbol, *args):
        for i, value in enumerate(args):
            self.cpu.reg_write(getattr(reg, 'UC_ARM64_REG_X'+str(i)), value)
        self.cpu.reg_write(reg.UC_ARM64_REG_SP, 0x9020e000)
        self.cpu.reg_write(reg.UC_ARM64_REG_LR, 0x90300000)
        self.cpu.reg_write(reg.UC_ARM64_REG_FPCR, 0)
        self.cpu.emu_start(self.symbols[symbol], 0x90300000, count=4000000)
        if (self.cpu.reg_read(reg.UC_ARM64_REG_PC) != 0x90300000
                or self.cpu.reg_read(reg.UC_ARM64_REG_SP) != 0x9020e000):
            raise ValueError('AArch64算子未在预算内返回或栈未恢复')
        return self.cpu.reg_read(reg.UC_ARM64_REG_W0)


def verify(module, fixture, snapshot):
    machine = Machine(module)
    cpu = machine.cpu
    table, source, output, coefficients, luma, parameters = (
        0x90000000, 0x90030000, 0x90040010, 0x90050000, 0x90051000, 0x90052000)
    cases = []
    p = snapshot.parameters
    if (unpack(fixture['main_gamma']) != p.gamma or unpack(fixture['y_gamma']) != p.y_gamma
            or tuple(fixture['cc1']) != p.cc1 or tuple(fixture['luma']) != p.luma):
        raise ValueError('黄金向量参数与锁定公开捕获不属于同一上下文')
    stages = ['main-gamma', 'rgb-ycc', 'y-gamma', 'ycc-rgb']
    if 'af_edit_ref_matrix16' in machine.symbols:
        stages += ['matrix16', 'area-comp', 'chroma-suppress']
    matrix_table, angles = 0x90060000, 0x90072000
    m = None
    if len(stages) == 7:
        cpu.mem_write(matrix_table, unpack(fixture['matrix_table']))
        cpu.mem_write(angles, unpack(fixture['matrix_angles']))
        cfg = fixture['matrix_parameters']
        m = Matrix(matrix_table, angles, 18432, 512,
                   *(cfg[n] for n in ('enabled', 'luma_smooth', 'chroma_smooth', 'scale_chroma', 'quadratic')),
                   (c.c_float*3)(*cfg['thresholds']))
    for stage in stages:
        row = fixture['goldens'][stage]
        raw, expected = unpack(row['input']), unpack(row['output'])
        pixels = len(raw)//6
        if pixels != 1024 or len(expected) != len(raw):
            raise ValueError('黄金向量维度不符')
        cpu.mem_write(source, raw)
        cpu.mem_write(output-16, b'\xa5'*(len(expected)+32))
        immutable = [(source, raw)]
        if stage == 'main-gamma':
            cpu.mem_write(table, p.gamma)
            immutable.append((table, p.gamma))
            status = machine.call('af_edit_ref_main_gamma', table, 65536, source, pixels, output)
        elif stage == 'rgb-ycc':
            coefficient_bytes, weights = struct.pack('<8h', *p.cc1), struct.pack('<3h', *p.luma)
            cpu.mem_write(coefficients, coefficient_bytes)
            cpu.mem_write(luma, weights)
            immutable += [(coefficients, coefficient_bytes), (luma, weights)]
            status = machine.call('af_edit_ref_rgb_ycc', source, pixels, coefficients, luma,
                                  int(p.keep_chroma_unclipped), output)
        elif stage == 'y-gamma':
            config = struct.pack('<hhh2xf', p.level, p.white, p.pivot, p.gain)
            cpu.mem_write(table, p.y_gamma)
            cpu.mem_write(parameters, config)
            immutable += [(table, p.y_gamma), (parameters, config)]
            status = machine.call('af_edit_ref_y_gamma', table, 32768, parameters, source, pixels, output)
        elif stage == 'ycc-rgb':
            status = machine.call('af_edit_ref_ycc_rgb', source, pixels, output)
        elif stage == 'matrix16':
            cpu.mem_write(parameters, bytes(m))
            immutable += [(parameters, bytes(m)), (matrix_table, unpack(fixture['matrix_table'])),
                          (angles, unpack(fixture['matrix_angles']))]
            height, width = row['shape']
            status = machine.call('af_edit_ref_matrix16', parameters, source, width, height, output)
        elif stage == 'area-comp':
            area = fixture['area_parameters']
            value = bytes(Area((c.c_float*16)(*area['coefficients']), area['selector']))
            cpu.mem_write(parameters, value)
            immutable.append((parameters, value))
            status = machine.call('af_edit_ref_area', parameters, source, pixels, output)
        else:
            cfg = fixture['chroma_source']
            value = ChromaSource((c.c_int16*3)(*cfg['slopes']), (c.c_int16*3)(*cfg['thresholds']),
                                 cfg['low_slope'], cfg['low_threshold'], cfg['gain_raw'], cfg['exposure_300'])
            locations = (0x90090000, 0x900a0000, 0x90000000, 0x900c0000)
            chunks = [unpack(fixture['chroma_tables'][name]) for name in
                      ('inverse_secondary', 'inverse_main', 'main_gamma', 'secondary_gamma')]
            for at, data in zip(locations, chunks):
                cpu.mem_write(at, data)
                immutable.append((at, data))
            tabs = ChromaTables(*locations, *(len(data)//2 for data in chunks))
            cpu.mem_write(parameters, bytes(value))
            cpu.mem_write(parameters+0x100, bytes(tabs))
            immutable += [(parameters, bytes(value)), (parameters+0x100, bytes(tabs))]
            status = machine.call('af_edit_ref_chroma_controls', parameters, parameters+0x100, parameters+0x200)
            expected_controls = bytes(Chroma(**fixture['chroma_expected']))
            if status or bytes(cpu.mem_read(parameters+0x200, 16)) != expected_controls:
                raise ValueError('AArch64色度参数解码与公开参数不符')
            immutable.append((parameters+0x200, expected_controls))
            status = machine.call('af_edit_ref_chroma', parameters+0x200, source, pixels, output)
        actual = bytes(cpu.mem_read(output, len(expected)))
        compared = len(expected)
        if stage == 'matrix16':
            # 原始采样窗不包含外侧邻点，原图边缘不能由人工窗边代替。
            compared_actual = b''.join(actual[(r*width+2)*6:(r*width+width-2)*6] for r in range(height))
            compared_expected = b''.join(expected[(r*width+2)*6:(r*width+width-2)*6] for r in range(height))
            compared = len(compared_expected)
        else:
            compared_actual, compared_expected = actual, expected
        if status != 0 or compared_actual != compared_expected:
            raise ValueError(stage+'的目标架构输出与公开向量不同')
        if (bytes(cpu.mem_read(output-16, 16)) != b'\xa5'*16
                or bytes(cpu.mem_read(output+len(expected), 16)) != b'\xa5'*16
                or any(bytes(cpu.mem_read(at, len(value))) != value for at, value in immutable)):
            raise ValueError(stage+'破坏输入、参数或输出保护区')
        # 捕获重复像素不等于不同颜色覆盖。
        colors = len({raw[i:i+6] for i in range(0, len(raw), 6)})
        cases.append(dict(stage=stage, pixels=pixels, compared_pixels=compared//6, distinct_input_triples=colors,
                          sha256=digest(actual), return_code=status,
                          original_capture_equal=True, inputs_and_guards_preserved=True))
    chain_result = None
    if 'af_edit_ref_color' in machine.symbols:
        if m is None:
            raise ValueError('链协调器缺少完整颜色阶段')
        raw = unpack(fixture['goldens']['matrix16']['input'])
        expected = unpack(fixture['goldens']['ycc-rgb']['output'])
        area = fixture['area_parameters']
        y_table, chain_work = 0x90080000, 0x900e0000
        chain = Chain(m, table, y_table, 65536, 32768,
                      (c.c_int16*8)(*p.cc1), (c.c_int16*3)(*p.luma), int(p.keep_chroma_unclipped),
                      Area((c.c_float*16)(*area['coefficients']), area['selector']),
                      Chroma(**fixture['chroma_expected']), YGamma(p.level, p.white, p.pivot, p.gain))
        cpu.mem_write(table, p.gamma)
        cpu.mem_write(y_table, p.y_gamma)
        cpu.mem_write(source, raw)
        cpu.mem_write(parameters, bytes(chain))
        cpu.mem_write(output-16, b'\xa5'*(len(expected)+32))
        height, width = fixture['goldens']['matrix16']['shape']
        status = machine.call('af_edit_ref_color', parameters, source, width, height, chain_work, output)
        if status or bytes(cpu.mem_read(output, len(expected))) != expected:
            raise ValueError('AArch64完整参考颜色子链与单色捕获不符')
        if (bytes(cpu.mem_read(output-16, 16)) != b'\xa5'*16 or
                bytes(cpu.mem_read(output+len(expected), 16)) != b'\xa5'*16):
            raise ValueError('AArch64颜色子链破坏输出保护区')
        original_output = bytes(cpu.mem_read(output, len(expected)))
        chain.levels.gain = float('nan')
        cpu.mem_write(parameters, bytes(chain))
        status = machine.call('af_edit_ref_color', parameters, source, width, height, chain_work, output)
        if status != 0xffffffff or bytes(cpu.mem_read(output, len(expected))) != original_output:
            raise ValueError('AArch64颜色子链中途失败发布了部分输出')
        chain_result = dict(pixels=len(raw)//6, distinct_input_triples=1,
                            published_single_color_patch_equal=True, late_error_did_not_publish=True,
                            workspace_bytes=49152)
    machine.cpu = None
    return cases, chain_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--capture-folder', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError('不覆盖已有回执')
    started = time.monotonic()
    module, raw = args.module.read_bytes(), args.fixture.read_bytes()
    fixture = json.loads(raw)
    snapshot = load_edit_snapshot(args.capture_folder)
    if fixture['commit'] != snapshot.provenance()['commit'] or fixture['context'] != 4:
        raise ValueError('黄金向量来源不符')
    cases, chain = verify(module, fixture, snapshot)
    receipt = dict(schema='edit-reference-aarch64/1', command=[sys.executable, *sys.argv],
                   result='PASS', cases=cases, reference_color_chain=chain, seconds=time.monotonic()-started,
                   module_sha256=digest(module), fixture_sha256=digest(raw),
                   provenance=snapshot.provenance(), target_instructions_executed=True,
                   full_imaging_chain_executed=False, current_cp_pixel_verified=False,
                   firmware_modified=False, camera_io=False)
    with args.report.open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    print(json.dumps(dict(result='PASS', stages=len(cases), seconds=receipt['seconds']), ensure_ascii=False))


if __name__ == '__main__':
    main()
