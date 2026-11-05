"""原网格查询对象及内存初始化链的有界离线证据；不提供设备后端。"""
import hashlib
import struct

from .access_evidence import CP_SHA, require_source
from .cp_context406 import BANKS, CONTEXT, INPUT, _call, _prepare, layout
from .cp_machine import STACK, STOP


MODULE_BYTES = 0x678
CAPABILITY = 0x119df40
DEFAULT_INIT = 0x767984
QUERY = 0x415160
CLASSIFIER = 0x25df9c
MEMORY_INIT = 0x230c10
MEMORY_CHAIN = (MEMORY_INIT, 0x4eacd8, 0x4e93e4, 0x53cd40, 0xbaa258, 0x5c9034)
THREAD_INIT = 0x5e3b58
THREAD_TABLE = 0x19e391c
THREAD_RAM, THREAD_RAM_BYTES = 0x19d4000, 0x12000
GIC_CONTEXT, GIC_READ = 0x195068c, 0x5e5f08
COLOR_ENTRIES = (0x240d34, 0x232fe0, 0x231eb8, 0x71d37c,
                 0x230da8, 0x231234, 0x231654, 0x71a05e, 0x71f674)


def _blob(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), hex=raw.hex())


def _initialize_thread_tables(machine, stack):
    """执行原静态上下文表生产器；不填TCB或替代原锁/服务。"""
    require_source(machine.raw, CP_SHA, 'CP')
    if struct.unpack_from('<3I', machine.raw, 0x20148) != (0x106f000, 0x8a3b40, 0x1197000):
        raise ValueError('原线程表不在已锁定BSS布局中')
    machine.map_ram(THREAD_RAM, THREAD_RAM_BYTES)
    before = machine.read(THREAD_RAM, THREAD_RAM_BYTES)
    if any(before):
        raise ValueError('原线程初始化区不是声明的BSS零初值')
    machine.register('sp', stack)
    machine.register('lr', STOP | 1)
    machine.stop_before, machine.boundary, machine.writes = set(), None, []
    # 此原函数为ARM，不能使用强制Thumb入口的普通run()包装器。
    machine.cpu.emu_start(THREAD_INIT, STOP, count=100000)
    if machine.register('pc') != STOP or machine.register('sp') != stack:
        raise ValueError('原静态线程表初始化未正常返回')
    pointers = struct.unpack('<4I', machine.read(THREAD_TABLE, 16))
    if pointers != tuple(0x19d41a8 + i * 0x878 for i in range(4)):
        raise ValueError('原线程表未由原生产器生成四个静态上下文')
    writes = list(machine.writes)
    if any(not THREAD_RAM <= int(w['address'], 16) < THREAD_RAM + THREAD_RAM_BYTES
           and not STACK <= int(w['address'], 16) < STACK + 0x10000 for w in writes):
        raise ValueError('原线程表生产器写入了声明BSS/栈外区域')
    return dict(entry=hex(THREAD_INIT), original_caller='0x5ccc44',
                status='RETURNED', table=hex(THREAD_TABLE), pointers=list(map(hex, pointers)),
                mapped_zero_bss=[hex(THREAD_RAM), THREAD_RAM_BYTES], write_count=len(writes),
                writes=writes, table_bytes=_blob(machine.read(THREAD_TABLE, 16)),
                initialized_region_sha256=hashlib.sha256(
                    machine.read(THREAD_RAM, THREAD_RAM_BYTES)).hexdigest(),
                host_filled_context=False, complete_scheduler_initialized=False)


def execute(cp, wire=19, bank=BANKS[1]):
    """只执行已有来源夹具及原函数；查询结果、掩码和分配输出均不伪造。"""
    require_source(cp, CP_SHA, 'CP')
    if wire not in (0, 19, 20) or bank not in BANKS:
        raise ValueError('本网格上下文探针仅覆盖ST/FL2/FL3及原双银行')
    machine = _prepare(cp, wire, (0, 0, 0, 0, 0, 0, 1, 0), bank)
    from unicorn import UC_HOOK_CODE
    obj = INPUT + 0x1b40
    trace, queries, allocation, decisions, rebuilds, os_reads = [], [], [], [], [], []
    phase = ['query-before']
    pending = []
    decision_returns = []

    def observe(cpu, at, size, data):
        if pending and pending[-1][0] == at:
            _, query = pending.pop()
            query['result'] = machine.register('r0')
        if decision_returns and decision_returns[-1][0] == at:
            _, decision = decision_returns.pop()
            decision['result'] = machine.register('r0')
        if at == QUERY:
            owner = machine.register('r0')
            alternate = int(bool(machine.read(owner + 0x660, 1)[0])) if owner else 0
            record = owner + 0x180 + (16 if alternate else 0) if owner else 0
            query = dict(phase=phase[0], object=hex(owner),
                         inline_record=hex(record),
                         physical_base=hex(machine.word(record + 4)) if owner else '0x0',
                         alternate=alternate, diagnostic=machine.register('r1'))
            queries.append(query)
            pending.append((machine.register('lr') & ~1, query))
        if at in COLOR_ENTRIES:
            trace.append(hex(at))
        if at == 0x231234:
            grid_root, grid_pipe = machine.register('r0'), machine.register('r1')
            grid_state, grid_stage = machine.word(grid_root), machine.word(grid_pipe + 16)
            decision = dict(caller_return=hex(machine.register('lr') & ~1),
                state_grid_mode=machine.read(grid_state + 1, 1)[0],
                source_wire=machine.read(grid_state + 0x2e, 1)[0],
                source_grid_selector=machine.read(grid_state + 0x2f, 1)[0],
                stage_grid_index=machine.read(grid_stage + 11, 1)[0],
                state_grid_parameters=_blob(machine.read(grid_state + 0x36, 8)))
            decisions.append(decision)
            decision_returns.append((machine.register('lr') & ~1, decision))
        if at == 0x231654:
            grid_pipe = machine.register('r1')
            owner = machine.word(grid_pipe + 12)
            rebuilds.append(dict(address=hex(at), output_context=hex(owner),
                                 allocated_grid_pointer=hex(machine.word(owner + 0x6b0))))
        if at in (0x231c52, 0x231dea) and rebuilds:
            rebuilds[-1]['original_null_output_branch'] = hex(at)
        if at in MEMORY_CHAIN:
            item = dict(address=hex(at), registers={
                'r' + str(i): hex(machine.register('r' + str(i))) for i in range(4)})
            if at in (0x4eacd8, 0x4e93e4):
                item['stack_argument_5'] = hex(machine.word(machine.register('sp')))
            allocation.append(item)
        if phase[0] == 'original-grid-allocation-prefix' and at in (0x5c9050, 0x5c9054, 0x5e5ef8):
            os_reads.append(dict(address=hex(at), registers={
                'r' + str(i): hex(machine.register('r' + str(i))) for i in range(4)}))
        if len(trace) > 64 or len(queries) > 8 or len(allocation) > 12:
            raise ValueError('原网格探针调用轨迹超出预算')

    hook = machine.cpu.hook_add(UC_HOOK_CODE, observe)
    try:
        capability_before = machine.read(CAPABILITY, 0x100)
        if any(capability_before):
            raise ValueError('平面镜像BSS能力前缀不是本探针声明的零初值')
        before = machine.read(obj, MODULE_BYTES)
        first = machine.run(QUERY, arguments=(obj, 0))
        if first['status'] != 'RETURNED' or first['r0'] != 4:
            raise ValueError('未初始化的原查询没有保留错误码4')
        pending.pop()[1]['result'] = first['r0']
        phase[0] = 'default-init'
        initialized = machine.run(DEFAULT_INIT, arguments=(obj,), limit=2000000)
        after = machine.read(obj, MODULE_BYTES)
        init_writes = list(machine.writes)
        if initialized['status'] != 'RETURNED':
            raise ValueError('原默认ModuleSetter初始化未返回')
        if any(not obj <= int(w['address'], 16) < obj + MODULE_BYTES
               and not 0x90100000 <= int(w['address'], 16) < 0x90110000
               for w in init_writes):
            raise ValueError('原默认初始化写入了声明对象/栈外区域')
        bases = tuple(machine.word(obj + 0x184 + i * 8) for i in range(4))
        if bases != (0xf3830000, 0xf3930000, 0xf3a30000, 0xf3c30000):
            raise ValueError('原默认LUT寄存器基址不符')
        phase[0] = 'query-after'
        queried = machine.run(QUERY, arguments=(obj, 0))
        if queried['status'] != 'RETURNED' or queried['r0'] != 0:
            raise ValueError('原初始化后查询未返回真实分类0')
        pending.pop()[1]['result'] = queried['r0']

        phase[0] = 'original-color-wrapper'
        produced = machine.run(0x23091c, arguments=(CONTEXT, bank), limit=2000000,
                               stop_before=(0x73edc8, 0xb0de92, 0x4eacd8))
        if produced.get('boundary', {}).get('address') != '0x73edc8':
            raise ValueError('原C4生产器未到声明的dispatch前边界')
        root, aggregate, stack = (machine.register(n) for n in ('r0', 'r1', 'sp'))
        pipe = layout(machine, root, aggregate, bank)
        state, color = machine.word(root), machine.word(pipe + 8)
        if machine.word(state + 0x1ec) != obj:
            raise ValueError('原C4状态没有保留同一ModuleSetter对象')
        root_before = machine.read(root, 32)
        init = _call(machine, 0x719f2e, (root, pipe), stack,
                     stop_before=(0xb0de92, 0x4eacd8))
        apply = _call(machine, 0x719ef6, (root, pipe), stack,
                      stop_before=(0xb0de92, 0x722396, 0x4eacd8, 0x414f44))
        if init['status'] != 'RETURNED' or apply['status'] != 'RETURNED':
            raise ValueError('原颜色初始化/完整包装器未返回')
        if machine.read(root, 32) != root_before or layout(machine, root, aggregate, bank) != pipe:
            raise ValueError('原颜色包装器改变了所属别名')
        wrapper_queries = [q for q in queries if q['phase'] == phase[0]]
        if not wrapper_queries or any(q.get('result') != 0 for q in wrapper_queries):
            raise ValueError('完整原颜色包装器未消费已初始化的真实查询分类')
        output_context, allocation_record, stage = (machine.word(pipe + at) for at in (12, 20, 16))
        source, published, output = (machine.word(color + 0x184), machine.word(color + 0x20),
                                     machine.word(output_context + 0x6b0))
        if published or output:
            raise ValueError('没有原分配服务时意外出现网格发布指针')
        wrapper_snapshot = dict(root=hex(root), aggregate=hex(aggregate), pipe=hex(pipe),
            state=hex(state), state_module_setter=hex(machine.word(state + 0x1ec)),
            color=hex(color), color_header=_blob(machine.read(color, 0x44)),
            grid_source_cache=hex(source), grid_cache_bytes=_blob(machine.read(color + 0x180, 16)),
            grid_source_prefix=_blob(machine.read(source, 24)) if source else None,
            published_grid_pointer=hex(published), output_context=hex(output_context),
            allocated_grid_pointer=hex(output), stage=hex(stage),
            stage_bytes=_blob(machine.read(stage, 24)),
            allocation_record=hex(allocation_record),
            allocation_record_before=_blob(machine.read(allocation_record, 40)),
            calls=list(trace), grid_decisions=list(decisions), init=init, apply=apply)

        # 原网格状态机把一次构造拆到连续调用；不能把首帧的缓存更新当成表生成。
        frames = [dict(frame=1, counter_after=machine.read(output_context + 0x27, 1)[0],
                       calls=list(trace), result=apply)]
        for frame in range(2, 5):
            start = len(trace)
            previous = machine.read(output_context + 0x27, 1)[0]
            frame_result = _call(machine, 0x719ef6, (root, pipe), stack,
                                stop_before=(0xb0de92, 0x722396, 0x4eacd8, 0x414f44))
            if frame_result['status'] != 'RETURNED':
                raise ValueError('原连续颜色调用没有在空输出保护分支返回')
            frames.append(dict(frame=frame, counter_before=previous,
                counter_after=machine.read(output_context + 0x27, 1)[0],
                calls=trace[start:], result=frame_result))
        if [f['counter_after'] for f in frames] != [1, 2, 3, 4]:
            raise ValueError('原网格四次调用的构造状态机不符')
        if len(rebuilds) != 1 or not rebuilds[0].get('original_null_output_branch'):
            raise ValueError('第四次原调用未执行一次原表构造器：' + str(rebuilds))
        if machine.word(output_context + 0x6b0) or machine.word(color + 0x20):
            raise ValueError('未获原分配缓冲时意外发布网格输出')
        wrapper_snapshot.update(continuous_frames=frames, all_calls=trace,
                                all_grid_decisions=decisions, grid_rebuilds=rebuilds)

        phase[0] = 'original-grid-allocation-prefix'
        # 原静态表可由原指令生成。仍不提供GIC映射、锁、服务句柄或物理地址。
        thread_init = _initialize_thread_tables(machine, stack)
        memory = _call(machine, MEMORY_INIT, (root, pipe), stack,
                       stop_before=(GIC_READ, 0xb0de92, 0x60ebaa))
        if memory.get('boundary', {}).get('address') != hex(GIC_READ):
            raise ValueError('原分配链没有到达声明的GICC初始化边界')
        if [int(x['address'], 16) for x in allocation] != list(MEMORY_CHAIN):
            raise ValueError('原网格分配链出现未声明调用顺序：' + str(allocation))
        allocation.append(dict(memory['boundary'], stopped_before_execution=True))
        if ([x['address'] for x in os_reads] != ['0x5c9050', '0x5c9054', '0x5e5ef8']
                or os_reads[1]['registers']['r0'] != '0x19d41a8'):
            raise ValueError('原分配链没有实际消费刚生产的核0上下文')
        if (machine.register('r0') != GIC_CONTEXT or machine.register('r1') != 0
                or machine.word(GIC_CONTEXT + 8) != 0):
            raise ValueError('原GICC映射缺失的停止前提不符')
        if machine.word(output_context + 0x6b0) or machine.word(color + 0x20):
            raise ValueError('停止边界前意外发布了网格缓冲')
        if machine.read(CAPABILITY, 0x100) != capability_before:
            raise ValueError('探针意外改变了BSS能力掩码')
        if any('result' not in q for q in queries):
            raise ValueError('原查询返回值未完整观察')
        return dict(wire=wire, bank=hex(bank), module_setter=hex(obj),
            module_setter_before=_blob(before), module_setter_after=_blob(after),
            default_init=initialized, default_init_write_trace=init_writes,
            native_lut_register_bases=list(map(hex, bases)), queries=queries,
            capability_prefix=_blob(capability_before), capability_written=False,
            wrapper=wrapper_snapshot, allocation_calls=allocation, allocation_result=memory,
            original_thread_initialization=thread_init, original_os_reads=os_reads,
            missing_gic_cpu_interface_field=hex(GIC_CONTEXT + 8),
            allocation_record_after=_blob(machine.read(allocation_record, 40)),
            output_pointer_published=False, physical_register_access=False,
            actual_evf_jpg_binding=False, actual_isp_pixels=False, frame_release_verified=False)
    finally:
        machine.cpu.hook_del(hook)
        machine.cpu = None


def collect(cp):
    require_source(cp, CP_SHA, 'CP')
    return dict(schema='a7r5-original-grid-context406/2', cp_sha256=CP_SHA,
        status='ORIGINAL_QUERY_THREAD_INIT_AND_ALLOCATION_PREFIX_VERIFIED',
        cases=[execute(cp, wire, bank) for wire in (0, 19, 20) for bank in BANKS],
        source_module_initialization='original 0x767984 relocated to the source-owned inline object',
        query_record_semantics='inline DevLutSetter +4 is physical register base, not allocated table pointer',
        fixture_boundaries=['same bounded synthetic current-CP C4/runtime properties as cp_context406',
            'BSS capability table remains original flat-image zero, not a running-camera capture',
            'original full startup not executed; original default initializer is called directly',
            'original ARM initializer 0x5e3b58 produces four static per-core context pointers; full scheduler/startup not executed',
            'original allocation consumes the initialized core0 pointer; stop before 0x5e5f08 reads absent GICC mapping from 0x195068c+8',
            'no host-filled output table pointer, service handle, capability bits, MMIO or device forwarding'],
        camera_io=False, input_modified=False, complete_startup=False,
        actual_runtime_capability=False, actual_evf_jpg_binding=False,
        actual_isp_pixels=False, frame_release_verified=False)
