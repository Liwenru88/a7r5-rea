"""纯参数ARMv7适配器与同包AP/CP原指令联验；无实际CP挂钩或硬件后端。"""
import hashlib
import io
import struct

from .access_evidence import AP_SHA, CP_SHA, require_source, arm64_cpu, run64
from .cp_machine import CpMachine, WORK, STACK
from .investigate import AP, PARAMETERS


def collect(ap_raw, cp, adapter_raw):
    require_source(ap_raw, AP_SHA, 'AP')
    require_source(cp, CP_SHA, 'CP')
    from elftools.elf.elffile import ELFFile
    from unicorn import UC_PROT_READ, UC_PROT_EXEC, arm64_const as a64
    if len(adapter_raw) > 0x20000:
        raise ValueError('CP参数适配器超出隔离文件预算')
    elf = ELFFile(io.BytesIO(adapter_raw))
    if elf['e_machine'] != 'EM_ARM' or elf['e_type'] != 'ET_EXEC' or not elf.little_endian:
        raise ValueError('CP参数适配器必须为独立小端ARM测试ELF')
    if any(s['sh_type'] in ('SHT_REL', 'SHT_RELA') for s in elf.iter_sections()):
        raise ValueError('CP参数适配器不能依赖运行时重定位')
    table = elf.get_section_by_name('.symtab')
    if table is None:
        raise ValueError('CP参数适配器缺少符号表')
    symbols = {s.name:int(s['st_value']) for s in table.iter_symbols() if s['st_shndx'] != 'SHN_UNDEF'}
    names = ('af_cp406_overlay', 'af_cp406_matches', 'af_validate')
    if any(n not in symbols or not 0x92000000 <= symbols[n] < 0x92010000 or not symbols[n] & 1
           for n in names):
        raise ValueError('CP参数适配器函数或Thumb地址不符')
    m = CpMachine(cp)
    for segment in elf.iter_segments():
        if segment['p_type'] != 'PT_LOAD':
            continue
        start, end, flags = segment['p_vaddr'], segment['p_vaddr'] + segment['p_memsz'], segment['p_flags']
        if flags not in (4, 5) or not ((start == 0x10000 and end <= 0x11000) or
                                       0x92000000 <= start < end <= 0x92020000):
            raise ValueError('CP参数适配器映射或权限超出隔离预算')
        pages = set(range(start & ~4095, (end + 4095) & ~4095, 4096))
        if pages & m.pages:
            raise ValueError('CP参数适配器与既有映射重叠')
        permission = UC_PROT_READ | (UC_PROT_EXEC if flags == 5 else 0)
        m.cpu.mem_map(start & ~4095, len(pages) * 4096, permission)
        m.cpu.mem_write(start, segment.data())
        m.pages.update(pages)
    m.map_ram(0x157c000, 0x1000)
    m.map_ram(0x16af000, 0x1000)
    m.map_ram(0x16ba000, 0x1000)
    ap = arm64_cpu(AP(ap_raw), [0x3550000, 0x4b72000])
    ap_output = WORK + 0x100
    root, private, preset, context = WORK + 0x4000, WORK + 0x9000, WORK + 0x800, WORK + 0x1000
    original = bytes((i * 17 + 3) % 256 for i in range(0xe70))
    selectors = list(range(10)) + [17, 18]
    cases = []
    for position, base in enumerate(selectors):
        for register, value in ((a64.UC_ARM64_REG_X0, base), (a64.UC_ARM64_REG_X1, position),
                                (a64.UC_ARM64_REG_X2, ap_output)):
            ap.reg_write(register, value)
        ap.reg_write(a64.UC_ARM64_REG_LR, WORK + 0xf000)
        run64(ap, 0x3550354)
        wire = ap.mem_read(ap_output, 1)[0]
        values = (-9,9,-8,7,6,5,4,3) if position & 1 else (9,-9,8,0,-6,0,1,9)
        raw = struct.pack('<BB8b64x', base, 0, *values)
        m.put(preset, raw)
        m.put(root, original)
        # 深层帧/校准字段是显式零夹具；没有把0xe70前缀误认为完整上下文根。
        m.put(private, b'\0' * 0x4c00)
        m.put(private - 4, b'\xa5' * 4)
        m.put(private + 0xe70, b'\x5a' * 4)
        if m.run(symbols['af_cp406_overlay'], arguments=(preset, root, private, 0xe70))['r0'] != 0:
            raise ValueError('目标CP纯参数适配器拒绝合法预设')
        expected = bytearray(original)
        expected[0xa40:0xa44] = struct.pack('<I', wire)
        for row, value in zip(PARAMETERS, values):
            expected[row[7]] = value & 255
        if m.read(private, 0xe70) != bytes(expected) or m.read(root, 0xe70) != original:
            raise ValueError('目标CP纯参数适配与同包AP原基底映射/八字段不符')
        if m.read(private - 4, 4) != b'\xa5'*4 or m.read(private + 0xe70, 4) != b'\x5a'*4:
            raise ValueError('目标CP纯参数适配破坏边界')
        if m.run(symbols['af_cp406_matches'], arguments=(preset, private, 0xe70))['r0'] != 0:
            raise ValueError('目标CP纯参数字段匹配失败')
        m.run(0xafd2da, arguments=(private, context))
        m.put(WORK + 0x2000, struct.pack('<5I', 0x60daa5, 0, 0x4bf3e1, 0, 0))
        m.run(0x9071cc, 0x9071fa, arguments=(context, WORK+0x2000, 6), returned=False)
        output = WORK + 0x3000
        m.run(0x9053f8, 0x905446, arguments=(output, 0x157c278), returned=False)
        if m.read(output + 0x20, 6) != struct.pack('<I2B', wire, values[5], values[6]):
            raise ValueError('目标适配输出未进入原CP锐度/精细度派生字段')
        box = WORK + 0x6000
        m.word(STACK + 0xe024, context)
        m.word(box + 0x104, WORK + 0x500)
        m.register('fp', output)
        m.register('sl', box)
        m.run(0x240da8, 0x240df0, returned=False)
        if m.register('r8') != private:
            raise ValueError('目标适配颜色窗口未读取私有根')
        m.run(0x24119a, 0x241280, returned=False)
        if (m.read(output + 0x2e, 1) != bytes([wire]) or
                m.read(output + 0x30, 1) != bytes([values[4] & 255]) or
                m.read(output + 0x33, 1) != bytes([values[0] & 255])):
            raise ValueError('目标适配未进入原CP颜色选择/饱和度/对比度字段')
        cases.append(dict(base_selector=base, original_ap_wire=wire, values=list(values),
                          prefix_sha256=hashlib.sha256(bytes(expected)).hexdigest(),
                          native_context_constructor=True, native_sharpness_prefix=True,
                          native_color_selector_saturation_contrast=True,
                          original_frame_fields_preserved=True))
    # 在同一目标CPU上确认合法LUT文档也不会降级成纯参数输出。
    m.put(preset, struct.pack('<BB8b', 17, 1, *values) + b'\x01'*32 + b'\x02'*32)
    previous = m.read(private, 0xe70)
    rejected = m.run(symbols['af_cp406_overlay'], arguments=(preset, root, private, 0xe70))['r0']
    if rejected != 0xffffffff or m.read(private, 0xe70) != previous:
        raise ValueError('目标适配器没有拒绝未经验证的LUT成像载荷')
    return dict(schema='a7r5-target-cp406-parameters/1', ap_sha256=AP_SHA, cp_sha256=CP_SHA,
                adapter_sha256=hashlib.sha256(adapter_raw).hexdigest(), adapter_bytes=len(adapter_raw),
                cases=cases, lut_rejected_without_write=True, native_adapter_instructions_executed=True,
                original_ap_translator='0x3550354', original_cp_context='0xafd2da',
                actual_ap_cp_transport=False, actual_cp_hook_installed=False,
                frame_lifetime_proven=False, image_pixels_proven=False,
                fixture_boundaries=['explicit preset driver', 'frame prefix bytes',
                    'private full context root with zero deep metadata', 'stops before consumer queue'],
                camera_io=False, firmware_modified=False)
