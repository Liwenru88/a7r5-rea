"""同一原C4源到Gamma的原字段复制/格式化及完整选表消费；不提供ISP像素。"""
import hashlib
import struct

from .access_evidence import CP_SHA, require_source
from .cp_machine import WORK, STACK, STOP
from .cp_gamma406 import TABLE, record

SHOT = WORK + 0x20100
CURVE = WORK + 0x24000
GAMMA = 0x1f6a088
STATS = 0x1f12bb0
CALL_STACK = STACK + 0x8000
FACTORY = (0, 3, 2, 1, 16, 15, 17, 18, 5, 13, 19, 20)


def _ram(machine, address, size):
    if any(first <= address and address + size <= last
           for first, last in machine.ram_ranges):
        return
    if any(address < last and first < address + size
           for first, last in machine.ram_ranges):
        raise ValueError('Gamma研究RAM与已有部分映射冲突')
    machine.map_ram(address, size)


def _declared(machine, address, size):
    return any(first <= address <= address + size <= last
               for first, last in machine.ram_ranges)


def _run(machine, start, end=STOP, *, args=(), window=False):
    machine.register('sp', CALL_STACK)
    machine.register('lr', STOP | 1)
    result = machine.run(start, end, arguments=args, preserve_state=True,
                         returned=False, limit=1000000,
                         stop_before=(0xb0de92, 0x4eacd8, 0x4e93e4))
    if result['status'] != 'WINDOW_EXECUTED' or machine.register('sp') != CALL_STACK:
        raise ValueError('原Gamma链未按声明边界结束：' + str(result))
    return list(machine.writes)


def execute_from_context(machine, context):
    """复用调用者的真实C4对象，不接收第二个可手工同步的wire参数。

    C4源及校准仍可能为显式离线夹具。原shot构造完整执行；源字段复制和
    Gamma输入格式化是明确的原窗口，不宣称执行完整313c4c/8453ee或ISP。
    """
    require_source(machine.raw, CP_SHA, 'CP')
    if not _declared(machine, context, 0xc4):
        raise ValueError('Gamma的C4上下文未在声明RAM中')
    source = machine.word(context)
    if not _declared(machine, source, 0xe70):
        raise ValueError('Gamma的C4源参数根未在声明RAM中')
    wire = machine.word(source + 0xa40)
    if wire not in FACTORY:
        raise ValueError('Gamma同源研究仅支持已列出的原厂基底')
    domain = machine.word(context + 12)
    extra = machine.word(context + 0x5c)
    if not _declared(machine, domain, 0x40) or not _declared(machine, extra, 0xf2):
        raise ValueError('Gamma的原C4域或附属元数据缺少声明来源')
    domain_code = machine.word(domain + 0x3c)
    if domain_code > 2:
        raise ValueError('Gamma研究域会进入未取证的原系统服务')
    saved_sp = machine.register('sp')
    if not STACK + 0x9000 <= saved_sp <= STACK + 0xfa00:
        raise ValueError('Gamma独立工作栈不能覆盖原描述符栈帧')
    parent = machine.read(saved_sp, 0x600)
    source_before = machine.read(source, 0xe70)
    context_before = machine.read(context, 0xc4)
    domain_before = machine.read(domain, 0x40)
    extra_before = machine.read(extra, 0xf2)
    for address, size in ((WORK + 0x20000, 0x6000), (0x1964000, 0x3000),
                          (0x1992000, 0x1000), (0x1f69000, 0x3000),
                          (0x1986000, 0x1000), (0x18d1000, 0x1000),
                          (0x1f12000, 0x2000)):
        _ram(machine, address, size)
    # 明确保留原shot默认构造及原全局调试/强制覆盖门控，未提供系统后端。
    machine.put(SHOT - 16, b'\xa5' * (0x2000 + 32))
    machine.put(GAMMA - 16, b'\xa5' * (0x54 + 32))
    machine.put(CURVE - 16, b'\xa5' * (0x800 + 32))
    trace, captures, phases = [], {}, []
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ

    def observe(cpu, at, size, data):
        if at in (0x89913e, 0x314bd8, 0x313fce, 0x315b00, 0x315a82,
                  0x84560a, 0xaa6710, 0xaa7ea4, 0xaa81ca, 0x41363c):
            trace.append(hex(at))
        if at == 0xaa81ca:
            pointer = machine.register('r0')
            captures['input'] = machine.read(pointer, 0x3c)
            captures['input_pointer'] = pointer
            captures['output_pointer'] = machine.register('r1')
        if len(trace) > 128:
            raise ValueError('Gamma原链轨迹超出预算')

    handle = machine.cpu.hook_add(UC_HOOK_CODE, observe)

    def read_curve(cpu, access, address, size, value, data):
        pointer = captures.get('curve_pointer')
        if pointer is not None and address < pointer + 516 and pointer < address + size:
            captures['curve_coverage'].update(range(max(address, pointer) - pointer,
                min(address + size, pointer + 516) - pointer))

    read_handle = machine.cpu.hook_add(UC_HOOK_MEM_READ, read_curve)
    try:
        def phase(name, start, end=STOP, *, args=(), window=False, stats=False):
            writes = _run(machine, start, end, args=args, window=window)
            allowed = ((SHOT, SHOT + 0x2000), (GAMMA, GAMMA + 0x54),
                       (CURVE, CURVE + 0x800), (STACK, saved_sp))
            if stats:
                allowed += ((STATS, STATS + 0x1000),)
            for write in writes:
                at = int(write['address'], 16)
                if not any(first <= at < at + write['bytes'] <= last
                           for first, last in allowed):
                    raise ValueError('原Gamma链写入未声明的结果/工作栈：' + str(write))
            phases.append(dict(name=name, entry=hex(start),
                               end='return' if not window else hex(end),
                               writes=len(writes), original_complete=not window))

        # 原对象位于BSS；只在两侧布置保护字节，内部经原清零函数初始化。
        # 5f58b0为ARM函数，通过原Thumb BLX调用窗口进入，保持实际ISA切换。
        phase('original_shot_bss_zero', 0x7196dc, 0x7196e0,
              args=(SHOT, 0x2000), window=True)
        phase('original_gamma_bss_zero', 0x7196dc, 0x7196e0,
              args=(GAMMA, 0x54), window=True)
        phase('original_shot_defaults', 0x89913e, args=(SHOT,))
        # 原313c4c的参数复制段：fp为同一个原C4，r0在原指令内解引用。
        # 314eb6/314eba执行source+a40→shot+cdc，不由宿主复制两处wire。
        machine.register('fp', context)
        machine.register('sb', SHOT)
        machine.register('r4', 0x19648d8)
        machine.register('r8', STATS)
        machine.register('r0', source)
        phase('original_source_copy_window', 0x314bd8, 0x314f02,
              window=True, stats=True)
        machine.register('fp', context)
        machine.register('sb', SHOT)
        machine.register('r8', STATS)
        phase('original_domain_copy_window', 0x313fce, 0x313fe4,
              window=True, stats=True)
        machine.register('fp', context)
        machine.register('sb', SHOT)
        phase('original_active_copy_window', 0x315b00, 0x315b10, window=True)
        machine.register('fp', context)
        machine.register('sb', SHOT)
        phase('original_auxiliary_copy_window', 0x315a82, 0x315a96, window=True)
        if machine.word(SHOT + 0xcdc) != wire:
            raise ValueError('原C4到shot的基底复制不符')
        machine.register('r8', SHOT)
        phase('original_gamma_formatter_and_full_selector', 0x84560a, 0x845704,
              window=True)
        raw = captures.get('input')
        if (raw is None or struct.unpack_from('<I', raw, 0x10)[0] != wire or
                captures['output_pointer'] != GAMMA + 4):
            raise ValueError('原Gamma格式化/完整选择未消费同一基底源')
        parameters = machine.read(GAMMA + 4, 0x50)
        routes = [struct.unpack_from('<I', parameters, offset)[0]
                  for offset in (0x30, 0x34, 0x40)]
        column = parameters[0x38]
        if any(route >= 63 for route in routes) or column >= 7:
            raise ValueError('原完整Gamma路由或列越界')
        pointer = machine.word(TABLE + routes[0] * 28 + column * 4)
        selected = record(machine.raw, machine, pointer)
        captures['curve_pointer'] = pointer
        captures['curve_coverage'] = set()
        phase('original_gamma_constructor', 0x41363c,
              args=(0, GAMMA + 4, CURVE))
        values = machine.read(CURVE + 0x24c, 516)
        if len(captures['curve_coverage']) != 516:
            raise ValueError('原Gamma构造没有读取所选记录的完整129点')
        for address, size in ((SHOT, 0x2000), (GAMMA, 0x54), (CURVE, 0x800)):
            if (machine.read(address - 16, 16) != b'\xa5' * 16 or
                    machine.read(address + size, 16) != b'\xa5' * 16):
                raise ValueError('原Gamma链越过独立输出保护区')
        if (machine.read(source, 0xe70) != source_before or
                machine.read(context, 0xc4) != context_before or
                machine.read(domain, 0x40) != domain_before or
                machine.read(extra, 0xf2) != extra_before or
                machine.read(saved_sp, 0x600) != parent):
            raise ValueError('原Gamma链改变同C4源或颜色父栈描述符')
        return dict(status='OFFLINE_C4_SOURCE_TO_GAMMA_VERIFIED',
            source=hex(source), source_wire=wire, context=hex(context),
            wire_copy='original 0x314eb6/0x314eba: [C4]+0xa40 -> shot+0xcdc',
            formatter='original 0x845678/0x84567c: shot+0xcdc -> input+0x10',
            domain_source=hex(domain + 0x3c), domain_code=domain_code,
            native_input_mode=raw[8], native_input_active=raw[11],
            native_input_sha256=hashlib.sha256(raw).hexdigest(),
            routes=routes, column=column, selected_pointer=hex(pointer),
            selected_record_sha256=hashlib.sha256(selected).hexdigest(),
            values_sha256=hashlib.sha256(values).hexdigest(),
            selected_curve_bytes_read=len(captures['curve_coverage']),
            output_nodes_equal_base_record=values == selected[:516],
            native_adjustments_preserved=True,
            original_full_selector_returned=True, original_constructor_returned=True,
            original_shot_default_constructor=True, full_shot_producer_executed=False,
            full_outer_formatter_executed=False, phases=phases, calls=trace,
            original_source_unchanged=True, parent_stack_preserved=True,
            gamma_route_may_be_overridden_by_native_mode=True,
            captured_calibration=False, original_domain_names_verified=False,
            actual_isp_pixels=False, camera_io=False, input_modified=False)
    finally:
        machine.cpu.hook_del(handle)
        machine.cpu.hook_del(read_handle)
        machine.register('sp', saved_sp)
