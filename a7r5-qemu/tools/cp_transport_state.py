"""从固定原厂 CP 与只读现场生成传输前提报告；不产生 ACK 或参数通知。"""
import hashlib
import re
import struct

CP_SHA = '3269bf62426339791fcfbe8529698cd4accbe6c3d2ea61cd7c368a90ab7ee7c8'


def analyze(cp, runtime, trace):
    if len(cp) != 17617008 or hashlib.sha256(cp).hexdigest() != CP_SHA:
        raise ValueError('CP 固定原件身份不符')
    if len(runtime) != 0x500000:
        raise ValueError('CP 运行时区域长度不符')

    def word(address):
        if not 0x1500000 <= address <= 0x19ffffc:
            raise ValueError('CP 现场地址越界')
        return struct.unpack_from('<I', runtime, address-0x1500000)[0]

    def rom_word(address):
        return struct.unpack_from('<I', cp, address-0x108000)[0]

    def rom_string(address):
        if not 0x108000 <= address < 0x11d5070:
            raise ValueError('CP 原厂名称指针越界')
        value = cp[address-0x108000:address-0x108000+96].split(b'\0', 1)[0]
        return value.decode('ascii')

    # 原厂 0x60b3e8 用配置组选择 +0xc 掩码，+0x10 选择执行核；不是 ready 字段。
    group = word(0x195e9dc)
    if group > 31:
        raise ValueError('CP 配置组超出掩码宽度')
    entries = []
    for n in range(14):
        attr, argument, function, groups, cpus = struct.unpack_from('<5I', cp, 0xe7a948-0x108000+n*20)
        entries.append({'name': rom_string(rom_word(0xe7aa64+n*4)), 'attributes': attr,
                        'argument': argument, 'function': function, 'group_mask': groups,
                        'cpu_mask': cpus, 'selected_by_original_group': bool(groups & (1 << group)),
                        # in_asm 是首次翻译记录，不是函数返回或处理完成回执。
                        'entry_translation_observed': f'0x{function & ~1:08x}:' in trace})
    abort = re.search(r'with DFSR (0x[0-9a-f]+) DFAR (0x[0-9a-f]+)', trace)
    fault=[]
    if abort:
        dfsr=int(abort[1],16)
        status=(dfsr&15)|((dfsr>>6)&16)
        kind='translation_fault' if status in (5,7) else (
             'permission_fault' if status in (13,15) else (
             'unmodeled_MMIO' if status==8 and int(abort[2],16)>=0xf0000000 else 'data_abort'))
        fault=[f'{kind}:{abort[2]}']
    callback = word(0x193eb08)
    return {'configuration_group': group, 'initializers': entries,
            'cross_domain_callback_pointer': callback,
            'notify_mode': word(0x157aa30),
            'first_data_abort': {'DFSR': abort[1], 'DFAR': abort[2]} if abort else None,
            'transmission_blockers': fault +
                                     (['cross_domain_callback_unregistered'] if not callback else []) +
                                     ['AP_peer_not_connected', 'no_AP_request_submitted'],
            'CP_service_ready_proven': False, 'AP_init_processed': False,
            'CP_generated_0x2040': False, 'ISP_pixels_verified': False,
            'scope': 'boot_observation_only; no message submitted; no reply generated'}
