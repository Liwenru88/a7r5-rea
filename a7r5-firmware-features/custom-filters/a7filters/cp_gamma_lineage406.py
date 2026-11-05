"""执行4.06的A/Q、owner和Gamma参数准备窗口；绝不执行寄存器或图像后端。"""
import hashlib
import struct

from .access_evidence import CP_SHA, require_source
from .cp_machine import CpMachine, STACK, WORK


WINDOWS = (
    (0xae3a70, 0x1a), (0xae2d14, 0x10), (0x462f16, 0x1c),
    (0x46bfd0, 0xc8), (0x462036, 0x26), (0xaec71a, 6),
    (0xaac91a, 0x28), (0xaac94a, 0x20), (0xaa72c6, 0x22),
    (0xaa7332, 0x3c), (0xaa7fa8, 0x28), (0xaa86d0, 0x50),
    (0xaa7186, 0x7e), (0xaa7208, 0x1e), (0xaa7f6c, 0x24),
    (0x470a4a, 0xa), (0x470aa8, 0x6e), (0x470be6, 0x1e),
    (0x470c22, 0xc), (0x470c32, 0x6e), (0x47101a, 0x44), (0x471ca4, 0x50),
    (0x845bac, 4), (0xaac9fe, 4), (0xaa77dc, 0x12),
    (0x47d85c, 2), (0x47d8f0, 8), (0x47d9a4, 8), (0x47d9ba, 0x10),
    (0x47914e, 0x36), (0x481042, 0x20),
    (0xaa6412, 0x5a), (0xae3a4c, 0xa),
)
HARDWARE = (0x755b80, 0x755ba4)


def audit(raw):
    """显式RAM夹具执行原CPU代码，来源不完整时仅记录缺口，不发布成像资格。"""
    require_source(raw, CP_SHA, 'CP')
    if not __debug__:
        raise ValueError('原指令证据审计不能禁用断言')
    machine = CpMachine(raw)
    for first, size in ((WORK + 0x10000, 0x10000), (0x190b000, 0x3000),
                        (0x1913000, 0x1000), (0x1640000, 0x1000),
                        (0x1986000, 0x1000), (0x1f69000, 0x4000),
                        (0x1f6d000, 0x5000)):
        machine.map_ram(first, size)
    machine.enable_initialized_data(0x1192000, 0x1000)
    a1, a2, sp = WORK + 0x1000, WORK + 0x10000, STACK + 0xc000
    phases, inputs = [], []
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ

    def observed_read(cpu, access, address, size, value, data):
        inputs.append((address, size))

    handle = machine.cpu.hook_add(UC_HOOK_MEM_READ, observed_read)
    forbidden = HARDWARE + (0x5b8f58, 0x5b8d6c, 0x5b8910, 0x5c067c,
                            0x5c88dc, 0xb0de92, 0xb0df02)

    def guard_backend(cpu, at, size, data):
        if at in forbidden and at not in machine.stop_before:
            raise ValueError('来源窗口意外进入系统／寄存器后端：' + hex(at))

    guard = machine.cpu.hook_add(UC_HOOK_CODE, guard_backend)

    def phase(name, start, end=None, *, args=(), stops=(), writes=(), limit=4096):
        inputs.clear()
        machine.register('sp', sp)
        machine.register('lr', 0x9000f001)
        result = machine.run(start, arguments=args, stop_before=stops,
                             **({} if end is None else dict(end=end)),
                             returned=False, preserve_state=True, limit=limit)
        for item in machine.writes:
            at = int(item['address'], 16)
            if not any(lo <= at < at + item['bytes'] <= hi
                       for lo, hi in ((STACK, STACK + 0x10000),) + writes):
                raise ValueError('来源窗口写入越出声明范围：' + str(item))
        phases.append(dict(name=name, start=hex(start),
                           end=hex(end) if end is not None else 'return_or_boundary',
                           result=result, writes=list(machine.writes)))
        return result

    try:
        getters = []
        for selector in (0, 1, 2, 0xffffffff):
            phase('fixed_Q_getter', 0xae3a70, args=(selector,))
            q = machine.register('r0')
            assert q == (0x190ba9c if selector == 0 else 0x190c630)
            getters.append(dict(selector=selector, Q=hex(q)))
        q = 0x190c630

        owners = []
        for counter in (1, 2, 0xffff, 1):
            phase('owner_low16', 0xae2d14, args=(0x123, 0x45))
            low = machine.register('r0')
            assert low == 0x2345
            machine.put(0x11920aa, struct.pack('<H', counter))
            machine.register('r4', low)
            phase('owner_counter_window', 0x462f16, 0x462f32,
                  writes=((0x11920aa, 0x11920ac),))
            owner = machine.register('r4')
            next_counter = struct.unpack('<H', machine.read(0x11920aa, 2))[0]
            assert owner == (counter << 16 | low)
            assert next_counter == (1 if counter == 0xffff else counter + 1)
            owners.append(dict(counter=counter, owner=hex(owner), next=next_counter))
        assert owners[0]['owner'] == owners[3]['owner']

        assignments = []
        for a, owner in ((a1, 0x12345), (a2, 0x22345)):
            machine.put(a - 16, b'\xa5' * 16)
            machine.put(a + 0x7000, b'\xa5' * 16)
            machine.put(sp, bytes(0x90))
            machine.word(sp + 0x18, a)
            machine.register('r4', q)
            machine.register('sl', owner)
            phase('A_Q_success_tail', 0x46bfd0, 0x46c096,
                  writes=((a, a + 0x7000),))
            assert [machine.word(a + x) for x in (0x5a98, 0x5a9c, 0xbb0, 0xbb4)] == [
                q, owner, q + 0x140, q + 0x7b8]
            assert machine.read(a - 16, 16) == machine.read(a + 0x7000, 16) == b'\xa5' * 16
            assignments.append(dict(A=hex(a), Q=hex(q), owner=hex(owner),
                                    BB0=hex(q + 0x140), BB4=hex(q + 0x7b8)))

        node, out = WORK + 0x800, WORK + 0x900
        machine.word(q + 0x11c, node)
        machine.word(node, q + 0x11c)
        machine.word(node + 8, 0x12345)
        lookup = []
        for owner in (0x12345, 0x22345):
            machine.word(out, 0)
            machine.register('r8', q)
            machine.register('r6', owner)
            machine.register('r5', out)
            phase('Q_owner_lookup_window', 0x462036, 0x46205c,
                  writes=((out, out + 4),))
            found = machine.register('r4')
            assert found == int(owner == 0x12345)
            assert machine.word(out) == (node if found else 0)
            lookup.append(dict(owner=hex(owner), found=bool(found)))

        construct = []
        for channel in (0, 1):
            g = a1 + 0xda8
            machine.put(g, bytes(0xc0))
            machine.put(g, bytes((channel, 1, 0, 0)))
            first = phase('Gamma_constructor_input', 0x845db8,
                          args=(g,), stops=(0xaa7eea,))
            assert first['boundary']['address'] == '0xaa7eea'
            formatter = 0x1f6dfdc if channel == 0 else 0x1f6e390
            assert machine.register('r2') == formatter - 4
            assert machine.register('r0') == g + 0x78
            assert machine.register('r1') == g + 0xb4
            # 格式化helper尚未运行；以下独立窗口的formatter内容是夹具。
            machine.register('r8', 1)
            machine.register('sb', channel)
            machine.register('sl', 0x1f6de00)
            machine.register('r4', g)
            machine.register('r6', formatter - 4)
            machine.put(formatter - 4, b'\x01')
            machine.word(sp, 0x1f6de00 + channel * 0xa80 + 0x1fc8)
            packed = 0x1f6ff74 + channel * 0xa80
            result = phase('Gamma_constructor_pack', 0xaa7208,
                           stops=(0x413df0,), writes=((packed - 4, packed),))
            assert result['boundary']['address'] == '0x413df0'
            assert machine.register('r0') == 1
            assert machine.register('r1') == formatter
            assert machine.register('r2') == packed
            construct.append(dict(channel=channel, formatter=hex(formatter),
                                  output=hex(packed), constructor_mode=1,
                                  original_curve_constructor_executed=False))

        uploads = []
        for a, selector in ((a1, 0), (a1, 1), (a2, 0)):
            root = machine.word(a + 0xbb0)
            machine.put(root + 0x660, bytes((selector,)))
            descriptor = root + (16 if selector else 0) + 0x120
            machine.word(descriptor + 4, 0xdead0000)
            result = phase('A_to_first_Gamma_upload_boundary', 0xaec71a,
                           args=(a,), stops=HARDWARE)
            assert result['boundary']['address'] == '0x755b80'
            assert machine.register('r0') == descriptor
            assert machine.register('r1') == 0x1f6ff74
            # 这条准备链没有读取owner字段，不能据成功到达判成同版本。
            assert not any(at <= a + 0x5a9c < at + n for at, n in inputs)
            uploads.append(dict(A=hex(a), selector=selector, descriptor=hex(descriptor),
                                packet=hex(machine.register('r1')), owner_read=False))
        assert uploads[0]['descriptor'] == uploads[2]['descriptor']

        # 次Gamma从另一个A字段取root；来源夹具与首Q分开，不能反推同Q。
        second_root = WORK + 0x9000
        machine.word(a1 + 0xbb8, second_root)
        machine.word(second_root + 0x124, 0xbeef0000)
        result = phase('A_to_second_Gamma_upload_boundary', 0xaac94a,
                       args=(a1 + 0x20,), stops=HARDWARE)
        assert result['boundary']['address'] == '0x755b80'
        assert machine.register('r0') == second_root + 0x120
        assert machine.register('r1') == 0x1f709f4

        producers = []
        for backend, child, target in ((0, 0, 0x463bb8), (1, 0, 0x463cd4),
                                       (1, 1, 0x463db4), (1, 2, 0x463db4)):
            machine.put(sp, bytes(0xa0))
            machine.register('r8', a1)
            phase('producer_Q_source', 0x470a4a, 0x470a54)
            assert machine.word(sp + 0x48) == q
            machine.register('r7', sp + 0x100)
            machine.word(sp + 0x118, child)
            machine.word(sp + 0x114, backend)
            machine.register('sl', 0)
            machine.register('sb', 0)
            machine.register('r4', 1)
            phase('producer_metadata_window', 0x470aa8, 0x470b16,
                  writes=((0x1913090, 0x1913200), (0x1640a30, 0x1640e20)))
            # 外部45F6B4未执行，单独验证它之前的A+667C推导。
            phase('producer_auxiliary_source', 0x470be6, 0x470c00)
            assert machine.register('fp') == a1 + 0x667c
            phase('producer_child_source', 0x470c22, 0x470c2e)
            result = phase('producer_dispatch_window', 0x470c32,
                           stops=(0x463bb8, 0x463cd4, 0x463db4))
            assert result['boundary']['address'] == hex(target), (backend, child, result)
            assert machine.register('r1') == q
            assert machine.register('r2') == machine.word(a1 + 0x5a9c)
            source = a1 + 0x220 if target != 0x463db4 else machine.word(sp + 0x40)
            assert machine.register('r3') == source
            producers.append(dict(backend=backend, child=child, target=hex(target),
                                  Q=hex(q), owner=hex(machine.register('r2')),
                                  data_source=hex(source), complete_backend_executed=False))

        getter = phase('misidentified_Gamma_getter', 0x845bac, stops=(0x43be3c,))
        assert getter['boundary']['address'] == '0x43be3c'
        assert machine.register('r0') == 0x1f703f8

        # 原成功尾给次通道分配root；随后原拥有者转移会清源A，不能把Q当永久身份。
        phase('secondary_Q_getter', 0xae3a4c)
        second_q = machine.register('r0')
        assert second_q == 0x19097e0
        phase('secondary_Q_getter_result', 0x47d85c, 0x47d85e)
        machine.register('r6', 0x12345)
        phase('secondary_Q_pair_source', 0x47d8f0, 0x47d8f8)
        phase('secondary_Q_pair_reload', 0x47d9a4, 0x47d9ac)
        assert machine.register('r5') == second_q
        assert machine.register('r6') == 0x12345
        machine.register('sl', a1)
        phase('secondary_Q_assignment_tail', 0x47d9ba, 0x47d9ca,
              writes=((a1, a1 + 0x7000),))
        assert machine.word(a1 + 0xbb8) == second_q + 0x140
        assert machine.word(a1 + 0xbbc) == second_q + 0x7b8
        machine.word(a1 + 0x5a58, second_q)
        machine.word(a1 + 0x5a5c, 0x12345)
        machine.register('r4', a1)
        machine.register('fp', a2)
        phase('secondary_Q_owner_transfer', 0x47914e, 0x479184,
              writes=((a1, a1 + 0x7000), (a2, a2 + 0x7000)))
        assert [machine.word(a1 + x) for x in (0x5a58, 0x5a5c, 0xbb8, 0xbbc)] == [0] * 4
        assert [machine.word(a2 + x) for x in (0x5a58, 0x5a5c, 0xbb8, 0xbbc)] == [
            second_q, 0x12345, second_q + 0x140, second_q + 0x7b8]
        # 481042只复制资源指针、不清来源；这类copy与上面的transfer必须区分。
        machine.register('r6', a2)
        machine.register('sl', a1)
        phase('Q_root_pointer_copy', 0x481042, 0x481062,
              writes=((a1, a1 + 0x7000),))
        assert machine.read(a1 + 0xbb0, 16) == machine.read(a2 + 0xbb0, 16)
        ownership = dict(secondary_getter='0xae3a4c', secondary_assignment='0x47d9ba',
                         secondary_owner_transfer='0x47914e',
                         root_pointer_copy='0x481042',
                         pointer_copy_does_not_copy_private_Capture_version=True,
                         complete_allocation_and_semaphore_executed=False)

        # 执行原清零及memset本身，在后续原颜色构造器前停止。
        # 保留A/Q是显式反例夹具，不声称原调度允许reset后立即提交。
        for packed in (0x1f6ff74, 0x1f709f4):
            machine.put(packed, b'\xa5' * 0x466)
        before = machine.read(a1 + 0x5a98, 8) + machine.read(a1 + 0xbb0, 8)
        result = phase('original_bank_reset_prefix', 0xaa6412,
                       args=(0,), stops=(0x40fdac,),
                       writes=((0x1f69eb0, 0x1f712e0),), limit=100000)
        assert result['boundary']['address'] == '0x40fdac'
        assert all(machine.read(p, 0x466) == bytes(0x466) for p in (0x1f6ff74, 0x1f709f4))
        assert machine.read(a1 + 0x5a98, 8) + machine.read(a1 + 0xbb0, 8) == before
        # 上传准备函数仍到达寄存器helper前，不能用它授予“银行有有效版本”。
        result = phase('retained_Q_after_bank_reset_counterexample', 0xaec71a,
                       args=(a1,), stops=HARDWARE)
        assert result['boundary']['address'] == '0x755b80'
        reset = dict(original_clear_executed=True, packed_banks_zero=True,
                     retained_Q_fixture_still_reaches_register_boundary=True,
                     original_scheduler_allows_this_interleaving_verified=False,
                     complete_reset_function_executed=False)
    finally:
        machine.cpu.hook_del(handle)
        machine.cpu.hook_del(guard)
    return dict(status='PASS_ORIGINAL_A_Q_AND_GAMMA_PREPARATION_SOFTWARE_ONLY',
        CP_sha256=CP_SHA, fixed_Q_getters=getters, owner_counter=owners,
        A_Q_assignments=assignments, Q_owner_lookup=lookup,
        Gamma_constructor_banks=construct, first_Gamma_uploads=uploads,
        second_Gamma_upload=dict(root_source='A+0xBB8', packet='0x1f709f4',
                                 root_origin_verified=False),
        producer_branches=producers, getter_delegates_callback=True,
        Q_pointer_lifecycle=ownership,
        bank_reset=reset,
        windows=[dict(address=hex(a), bytes=n,
                      sha256=hashlib.sha256(raw[a-0x108000:a-0x108000+n]).hexdigest())
                 for a, n in WINDOWS], phases=phases,
        explicit_fixtures=['A/Q/storage in declared RAM', 'owner counter and Q owner-list node',
            'caller frame and backend flags', 'formatter contents after unexecuted formatter',
            'descriptor/register-base fields, never dereferenced as MMIO', 'secondary root'],
        gaps=['all global packed-bank writers/reset and serialization',
              'bank content to Capture birth/epoch/recipe-version association at submit',
              'A+BB8 original root allocation and secondary-stage reachability for 2B',
              'backend completion and final EVF/JPG pixel identity'],
        Q_address_is_frame_identity=False, owner_counter_is_unbounded_version=False,
        bank_version_association_verified=False, special_2B_Gamma_lineage_closed=False,
        production_admission_changed=False, actual_pixels_verified=False,
        semaphore_or_RTOS_executed=False, hardware_emulated=False,
        register_helper_executed=False, camera_io=False, CP_modified=False)
