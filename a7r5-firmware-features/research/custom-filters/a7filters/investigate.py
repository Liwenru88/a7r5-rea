"""对锁定4.06组件重新定位；证据只到静态层，不放行安装门槛。"""
import io
import struct


PARAMETERS = (
    ('contrast', 0x1670, 0x28c5544, 0x263be78, 0x35613f0, 0x4030, 0x33f600, 0xa44, 0x02cf0d20, 0x02cf0b71, 0x02cf0b73),
    ('highlights', 0x1682, 0x28c556c, 0x263c05c, 0x3561378, 0x40f3, 0x33f6e4, 0xa46, 0x02cf0d40, 0x02cf0b75, 0x02cf0b77),
    ('shadows', 0x1694, 0x28c5594, 0x263c240, 0x3561300, 0x40f4, 0x33f730, 0xa45, 0x02cf0d80, 0x02cf0b79, 0x02cf0b7b),
    ('fade', 0x16a6, 0x28c55bc, 0x263c424, 0x3561288, 0x40f5, 0x33f778, 0xa47, 0x02cf0da0, 0x02cf0b7d, 0x02cf0b81),
    ('saturation', 0x16b8, 0x28c55e4, 0x263c608, 0x3561210, 0x4031, 0x33f64c, 0xa48, 0x02cf0dc0, 0x02cf0b83, 0x02cf0b85),
    ('sharpness', 0x16ca, 0x28c560c, 0x263c7ec, 0x3561198, 0x4032, 0x33f698, 0xd2e, 0x02cf0de0, 0x02cf0b87, 0x02cf0b89),
    ('fineness', 0x16dc, 0x28c5634, 0x263c9d0, 0x3561120, 0x40f6, 0x33f7c0, 0xd2f, 0x02cf0e00, 0x02cf0b8b, 0x02cf0b8d),
    ('clarity', 0x16ee, 0x28c565c, 0x263cbb4, 0x35610a8, 0x40f7, 0x33f80c, 0xd30, 0x02cf0e20, 0x02cf0b8f, 0x02cf0b91),
)
CP_BASE = 0x108000


class AP:
    def __init__(self, raw):
        from elftools.elf.elffile import ELFFile
        self.raw = raw
        self.elf = ELFFile(io.BytesIO(raw))
        self.segments = [s for s in self.elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        self.relocations = {}
        for section in self.elf.iter_sections():
            if section['sh_type'] == 'SHT_RELA':
                for r in section.iter_relocations():
                    if r['r_info_type'] == 1027:
                        self.relocations[r['r_offset']] = r['r_addend']

    def offset(self, address, size):
        for s in self.segments:
            if s['p_vaddr'] <= address and address+size <= s['p_vaddr']+s['p_filesz']:
                return s['p_offset']+address-s['p_vaddr']
        raise ValueError(f'AP地址未映射：{address:#x}')

    def read(self, address, size):
        off = self.offset(address, size)
        return self.raw[off:off+size]

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def ptr(self, address):
        if address in self.relocations:
            return self.relocations[address]
        return struct.unpack('<Q', self.read(address, 8))[0]


def instructions(decoder, raw, address):
    return [{'address': hex(i.address), 'mnemonic': i.mnemonic, 'operands': i.op_str}
            for i in decoder.disasm(raw, address)]


def probe_list_lookup(ap):
    """仅执行当前AP的查找循环；描述符/记录放在隔离夹具中，不修改输入。"""
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_X0, UC_ARM64_REG_X21
    start, end = 0x1bd91d0, 0x1bd9204
    holder, descriptor, table = 0x90000000, 0x90000100, 0x90001000
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(0x1bd9000, 0x1000)
    cpu.mem_write(0x1bd9000, ap.read(0x1bd9000, 0x1000))
    cpu.mem_map(holder, 0x3000)
    cpu.mem_write(holder, struct.pack('<Q', descriptor))

    def run(rows, wanted):
        cpu.mem_write(descriptor+0x54, struct.pack('<I', len(rows)))
        cpu.mem_write(descriptor+0x58, struct.pack('<Q', table))
        raw = bytearray(len(rows)*128)
        for index, (menu, selector) in enumerate(rows):
            struct.pack_into('<I', raw, index*128+4, menu)
            struct.pack_into('<I', raw, index*128+0x34, selector)
        cpu.mem_write(table, bytes(raw))
        cpu.reg_write(UC_ARM64_REG_X0, holder)
        cpu.reg_write(UC_ARM64_REG_X21, wanted)
        cpu.emu_start(start, end, count=1024)
        if cpu.reg_read(UC_ARM64_REG_PC) != end:
            raise ValueError('AP查找窗口未在有界指令数内退出')
        return cpu.reg_read(UC_ARM64_REG_X0) & 0xffffffff

    current = [(ap.u32(0x3f4a280+i*128+4), ap.u32(0x3f4a280+i*128+0x34))
               for i in range(19)]
    for menu, selector in current:
        if run(current, menu) != selector:
            raise ValueError('当前19条记录原指令查找结果不符')
    # 菜单ID仅为合成夹具，不把未分配ID声明为真实菜单注册结果。
    proposed = [(0x100000+i, i) for i in range(32)] + [(0x100020, 16)]
    for menu, selector in proposed:
        if run(proposed, menu) != selector:
            raise ValueError('33条合成记录原指令查找结果不符')
    if any(run(rows, 0x7fffffff) != 0xffffffff for rows in (current, proposed)):
        raise ValueError('未命中菜单身份未返回原厂-1哨兵')
    return dict(status='LOOKUP_WINDOW_EXECUTED', start=hex(start), end_exclusive=hex(end),
                current_rows=19, synthetic_rows=33, queries=54,
                source='locked current AP instructions; isolated descriptor/record fixtures',
                external_calls=0, firmware_modified=False, renderer_capacity_proven=False,
                native_model_indices_extended=False, full_menu_boot_verified=False)


def inspect_binaries(ap_bytes, cp):
    from capstone import Cs, CS_ARCH_ARM64, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN
    ap = AP(ap_bytes)
    ad = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    cd = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
    descriptor, records = 0x5858b08, 0x3f4a280
    if (ap.u32(descriptor+0x54), ap.ptr(descriptor+0x58), ap.u32(descriptor+0x64)) != (19, records, 0x690):
        raise ValueError('当前AP列表前像不符')
    if (ap.ptr(descriptor+0x78), ap.ptr(descriptor+0x80)) != (0x1c05f18, 0x1c6f208):
        raise ValueError('当前AP选择读写前像不符')
    selectors = (0, 1, 2, 3, 4, 5, 17, 18, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16)
    rows = []
    for i, selector in enumerate(selectors):
        address = records+i*128
        if (ap.u32(address), ap.u32(address+4), ap.u32(address+0x34)) != (0x84c+i, 0x84c+i, selector):
            raise ValueError('当前AP列表行或枚举变化')
        rows.append(dict(address=hex(address), menu_id=hex(ap.u32(address)), selector=selector,
                         name_resource=hex(ap.u32(address+8)), field_4c=hex(ap.u32(address+0x4c))))
    results = []
    for index, (name, pid, get, set_, send, msg, recv, field, backup, fl2, fl3) in enumerate(PARAMETERS):
        bindings = []
        for slot in range(18):
            off = 0x56648a4+(pid+slot-0x163a)*32
            model = struct.unpack_from('<I', ap_bytes, off-12)[0]
            physical = struct.unpack_from('<I', ap_bytes, off)[0]
            expected = backup+2*slot if slot < 16 else (fl2 if slot == 16 else fl3)
            if (model, physical) != (pid+slot, expected):
                raise ValueError('当前AP参数绑定变化：'+name)
            bindings.append(dict(index=slot, model_id=hex(model), backup_id=hex(physical)))
        setter = instructions(ad, ap.read(set_, 0x120), set_)
        sender = instructions(ad, ap.read(send, 0xc4), send)
        receiver = instructions(cd, cp[recv-CP_BASE:recv-CP_BASE+16], recv)
        if not any(i['operands'] == f'w1, #{pid:#x}' for i in setter if i['mnemonic'] == 'mov'):
            raise ValueError('参数setter属性ID不符：'+name)
        if not any(i['operands'].endswith(f', #{msg:#x}') for i in sender if i['mnemonic'] == 'mov'):
            raise ValueError('AP通知ID不符：'+name+' '+str(sender))
        if not any(i['mnemonic'] == 'strb.w' and i['operands'] == f'r1, [r0, #{field:#x}]' for i in receiver):
            raise ValueError('CP接收字段不符：'+name)
        if struct.pack('<2I', msg, recv | 1) not in cp:
            raise ValueError('CP分派记录缺失：'+name)
        results.append(dict(name=name, bindings=bindings, getter=hex(get), setter=hex(set_),
                            ui_callback=hex(0x2209918+index*0x154), ap_message_sender=hex(send),
                            message_id=hex(msg), cp_receiver=hex(recv), cp_state_offset=hex(field),
                            cp_receiver_instructions=receiver))
    imports = {}
    dynsym = ap.elf.get_section_by_name('.dynsym')
    plt = ap.elf.get_section_by_name('.plt')
    for index, r in enumerate(ap.elf.get_section_by_name('.rela.plt').iter_relocations()):
        name = dynsym.get_symbol(r['r_info_sym']).name
        if name.startswith('Backup_') or name in ('open', 'fsync', 'rename', 'mkdir', 'write', 'close'):
            imports[name] = hex(plt['sh_addr']+32+index*16)
    storage = {hex(a): instructions(ad, ap.read(a, n), a) for a, n in
               ((0x35b88d8, 16), (0x35b8908, 36), (0x24a453c, 156), (0x2fb7bac, 224))}
    return dict(status='STATIC_MAPPINGS_RECONFIRMED_ON_406',
                address_convention='AP linked VA (convert through PT_LOAD); CP mapped VA',
                list=dict(descriptor=hex(descriptor), descriptor_file_offset=hex(ap.offset(descriptor, 0x90)),
                          records=hex(records), count=19, valid_positions=18, stride=128, rows=rows,
                          proposed_valid_positions=32, compatible_table_records_including_special=33,
                          capacity_proven=False),
                parameters=results, storage_imports=imports, storage_instructions=storage,
                list_lookup_probe=probe_list_lookup(ap),
                gates=dict(ui_32_capacity=False, internal_persistence=False, frame_snapshot=False),
                remaining=['32项列表实例容量/导航/所有身份查找尚未证明',
                           'Backup_write接口不证明扩展存储空间及掉电语义',
                           'CP接收不证明副本更新/逐帧引用；锐度范围末端仍需追踪'],
                installable_candidate_allowed=False)
