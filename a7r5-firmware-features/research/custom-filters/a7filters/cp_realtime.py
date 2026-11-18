"""CP上下文消费和完成窗口证据；不把参数任务完成当作JPG帧释放。"""
import struct

from .access_evidence import CP_SHA, require_source
from .cp_machine import CpMachine, WORK, STACK, STOP
from .investigate import CP_BASE, PARAMETERS, instructions

PENDING = 0x192b030
MASTER = 0x164eef0
CONTEXTS = (0x165d758, 0x165d820)
CONSUMERS = (
    ('first_consumer', 0x887162, 0x88476a, 0x15787e4, 0x15788a8, 0x15787e0),
    ('second_consumer', 0x964af0, 0x964b20, 0x157ce28, 0x157ceec, 0x157cf00),
    ('color', 0x7195d6, 0x719604, 0x1214e98, 0x1214f5c, 0x1214f70),
    ('sharpness', 0x9071cc, 0x9071fa, 0x157c278, 0x157c33c, 0x157c350),
)


def completion_flags(cp):
    m = CpMachine(cp)
    m.map_ram(0x192b000, 0x1000)
    m.map_ram(0x164e000, 0x3000)
    results = []
    for index in range(13):
        flags = [1] * 13
        m.put(PENDING - 8, b'\xa5' * 8)
        m.put(PENDING, struct.pack('<13I', *flags))
        m.put(PENDING + 52, b'\x5a' * 8)
        result = m.run(0x4bf3e0, arguments=(index,))
        flags[index] = 0
        if result['status'] != 'RETURNED' or m.read(PENDING, 52) != struct.pack('<13I', *flags):
            raise ValueError('CP原完成回调未只清除对应标记')
        if m.read(PENDING - 8, 8) != b'\xa5' * 8 or m.read(PENDING + 52, 8) != b'\x5a' * 8:
            raise ValueError('CP原完成回调破坏边界')
        results.append(dict(index=index, only_selected_flag_cleared=True))
    before = m.read(PENDING, 52)
    bad = m.run(0x4bf3e0, arguments=(13,), stop_before=(0xb0de92,))
    if bad['status'] != 'STOPPED_BEFORE_BOUNDARY' or m.read(PENDING, 52) != before:
        raise ValueError('CP非法完成身份未在日志边界停止或修改标记')
    masks = []
    for active, mode, previous in (([],0,0), ([0],0,0), ([3,6],0,0),
                                    (list(range(13)),0,0), ([0],1,4), ([2,6],1,0)):
        flags = [int(i in active) for i in range(13)]
        m.put(PENDING, struct.pack('<13I', *flags))
        m.register('fp', MASTER)
        m.word(MASTER + 0x1ac8, previous)
        m.run(0x4bdf54, 0x4be024, arguments=(mode,), returned=False)
        expected = sum(1 << i for i in active)
        if mode == 1:
            expected = (expected & ~4) | (previous & 4)
        if m.word(MASTER + 0x1ac8) != expected:
            raise ValueError('CP原标记汇总结果不符')
        masks.append(dict(active=active, mode=mode, previous_mask=previous, mask=expected))
    return dict(callback='0x4bf3e0', barrier='dmb sy', flag_base=hex(PENDING),
                cases=results, invalid_identity=bad, aggregate_cases=masks,
                frame_release_proven=False, fixture_boundaries=['flag state', 'aggregate entry mode and old mask'])


def consumer_copies(cp):
    cases = []
    for name, start, end, destination, callback, identity in CONSUMERS:
        m = CpMachine(cp)
        begin = min(destination, callback, identity) & ~4095
        m.map_ram(begin, ((max(destination + 0xc4, callback + 24) + 4095) & ~4095) - begin)
        context, completion = WORK + 0x1000, WORK + 0x2000
        parameter = WORK + 0x4000
        m.word(parameter + 0xa40, 19)
        for row, value in zip(PARAMETERS, (-3, 4, -5, 2, 6, 7, 3, 8)):
            m.put(parameter + row[7], bytes([value & 255]))
        m.run(0xafd2da, arguments=(parameter, context))
        raw = m.read(context, 0xc4)
        packet = struct.pack('<5I', 0x60daa5, 0, 0x4bf3e1, 0, 0)
        m.put(completion, packet)
        guard = min(destination, identity) - 4
        m.put(guard, b'\xa5' * 4)
        m.put(callback + 24, b'\x5a' * 4)
        result = m.run(start, end, arguments=(context, completion, 3), returned=False)
        if m.read(destination, 0xc4) != raw or m.read(callback, 20) != packet:
            raise ValueError('CP原消费者未完整复制上下文/完成包：' + name)
        if m.word(identity) != 3:
            raise ValueError('CP原消费者未保留完成身份：' + name)
        if m.read(guard, 4) != b'\xa5' * 4 or m.read(callback + 24, 4) != b'\x5a' * 4:
            raise ValueError('CP原消费者复制越界：' + name)
        cases.append(dict(name=name, entry=hex(start), end=hex(end), destination=hex(destination),
                          context_bytes=0xc4, callback_packet_preserved=True,
                          identity_location=hex(identity), native_context_constructor_executed=True,
                          source_pointer_borrowed=True, queue_or_hardware_executed=False))
    return dict(cases=cases, fixture_boundaries=['source context bytes', 'completion packet',
                                                'window ends before queue/consumer work'],
                full_consumer_completion_proven=False)


def operation_contexts(cp):
    m = CpMachine(cp)
    results = []
    for mode in (0, 1, 2):
        result = m.run(0xafc7d4, arguments=(mode,))
        expected = CONTEXTS[int(mode != 0)]
        if result['r0'] != expected:
            raise ValueError('CP操作上下文选择不符')
        results.append(dict(input=mode, context=hex(expected)))
    return dict(cases=results, names_semantically_verified=False,
                live_view_or_jpg_identity_proven=False)


def queue_rejection(cp):
    cases = []
    for name, entry, context, identity in (
            ('color', 0x7195d6, 0x1214e98, 3),
            ('sharpness', 0x9071cc, 0x157c278, 6)):
        m = CpMachine(cp)
        m.map_ram(context & ~4095, 0x1000)
        m.map_ram(0x192b000, 0x1000)
        parameter, source, completion = WORK + 0x4000, WORK + 0x1000, WORK + 0x2000
        m.run(0xafd2da, arguments=(parameter, source))
        m.put(completion, struct.pack('<5I', 0x60daa5, 0, 0x4bf3e1, 0, 0))
        m.put(PENDING, struct.pack('<13I', *([1] * 13)))
        stopped = m.run(entry, arguments=(source, completion, identity), stop_before=(0x4e8a90,))
        if stopped['status'] != 'STOPPED_BEFORE_BOUNDARY':
            raise ValueError('CP消费者未到达预期排队边界')
        task = m.register('r1')
        worker = m.word(task + 8)
        if worker not in (0x71965b, 0x907251):
            raise ValueError('原CP排队工作入口与调用者不符')
        if m.word(PENDING + 4 * identity) != 1:
            raise ValueError('队列边界前错误清除待处理标记')
        # 显式注入拒绝返回0；不执行或宣称成功排队，更不伪造硬件确认。
        after_queue = m.register('lr') & ~1
        m.run(after_queue, arguments=(0,), preserve_state=True)
        expected = [1] * 13
        expected[identity] = 0
        if m.read(PENDING, 52) != struct.pack('<13I', *expected):
            raise ValueError('CP排队拒绝的原回调/标记行为不符')
        cases.append(dict(name=name, worker=hex(worker), queue=hex(0x4e8a90),
                          callback_thunk='0x60daa4', completion='0x4bf3e0',
                          injected_queue_result=0, original_rejection_path_executed=True,
                          pending_cleared_without_worker_running=True,
                          queue_executed=False, image_processing_executed=False))
    return dict(cases=cases, pending_zero_is_success_acknowledgement=False,
                frame_release_proven=False)


def runtime_refresh(cp):
    m = CpMachine(cp)
    m.map_ram(0x157a000, 0x2000)
    m.map_ram(0x157c000, 0x1000)
    m.map_ram(0x164e000, 0x3000)
    m.map_ram(0x1653000, 0x6000)
    m.map_ram(0x1915000, 0x1000)
    m.map_ram(0x192b000, 0x1000)
    mutex = m.model_semaphore()
    source, snapshot, context = 0x157aa10, 0x1653c68, 0x192b070
    cases = []
    old_snapshot = None
    # 原颜色参数窗口读取两处配置字节；零配置是显式夹具，不代表机身校准。
    m.map_ram(0x16af000, 0x1000)
    m.map_ram(0x16ba000, 0x1000)
    for base, values in ((3, (-3,4,-5,2,6,7,3,8)), (19, (8,-7,6,5,-4,3,1,2)),
                         (20, (-9,9,-8,7,6,5,4,3))):
        for row, value in zip(PARAMETERS, values):
            m.put(WORK + 8, bytes([value & 255]))
            m.run(row[6], arguments=(WORK,))
        m.put(WORK + 8, bytes([base]))
        m.run(0x33f5b8, arguments=(WORK,))
        before = m.read(source, 0xdbc)
        m.put(MASTER - 8, b'\xa5' * 8)
        m.put(MASTER + 0xdbc, b'\x5a' * 8)
        # 原运行路径0x4b8d88从r4取得master，0x4b8dc0调用有锁完整快照。
        m.register('r4', MASTER)
        m.run(0x4b8d88, 0x4b8dc4, returned=False)
        if m.read(MASTER, 0xdbc) != before or mutex['held']:
            raise ValueError('CP运行快照未完整复制通知状态或锁未释放')
        if m.read(MASTER - 8, 8) != b'\xa5' * 8 or m.read(MASTER + 0xdbc, 8) != b'\x5a' * 8:
            raise ValueError('CP运行快照复制越界')
        if old_snapshot is not None and m.read(snapshot, 0xdbc) != old_snapshot:
            raise ValueError('刷新master提前改变既有参数快照')
        m.run(0x4baa9e, 0x4baaba, returned=False)
        if m.read(snapshot, 0xdbc) != before:
            raise ValueError('运行快照未进入原上下文数据源')
        m.run(0xafd2da, arguments=(snapshot, context))
        completion = WORK + 0x2000
        m.put(completion, struct.pack('<5I', 0x60daa5, 0, 0x4bf3e1, 0, 0))
        m.run(0x9071cc, 0x9071fa, arguments=(context, completion, 6), returned=False)
        output = WORK + 0x5000
        m.run(0x9053f8, 0x905446, arguments=(output, 0x157c278), returned=False)
        if m.read(output + 0x20, 6) != struct.pack('<I2B', base, values[5], values[6]):
            raise ValueError('CP运行更新没有进入实际消费者派生字段')
        fields = [m.read(snapshot + row[7], 1)[0] for row in PARAMETERS]
        if fields != [v & 255 for v in values]:
            raise ValueError('CP运行更新八项字段不符')
        color, box = WORK + 0x3000, WORK + 0x6000
        m.word(STACK + 0xe024, context)
        m.word(box + 0x104, WORK + 0x500)
        m.register('fp', color)
        m.register('sl', box)
        m.run(0x240da8, 0x240df0, returned=False)
        if m.register('r8') != snapshot:
            raise ValueError('原颜色窗口未从同一上下文取得参数源')
        m.run(0x24119a, 0x241280, returned=False)
        if (m.read(color + 0x2e, 1) != bytes([base]) or
                m.read(color + 0x30, 1) != bytes([values[4] & 255]) or
                m.read(color + 0x33, 1) != bytes([values[0] & 255])):
            raise ValueError('运行参数未进入原颜色选择/饱和度/对比度字段')
        old_snapshot = m.read(snapshot, 0xdbc)
        cases.append(dict(values=list(values), source_to_master_complete=True,
                          snapshot_preserved_until_original_copy=True,
                          native_context_and_consumer_copy=True,
                          sharpness_and_fineness_derived=True,
                          color_source_pointer_from_native_context=True,
                          color_wire_selector=base, base_receiver_executed=True,
                          saturation=values[4], contrast=values[0]))
    original = m.read(MASTER, 0xdbc)
    m.put(WORK + 8, b'\x04')
    m.run(PARAMETERS[0][6], arguments=(WORK,))
    mutex['denied'] = True
    m.register('r4', MASTER)
    m.run(0x4b8d88, 0x4b8dc4, returned=False)
    if m.read(MASTER, 0xdbc) != original:
        raise ValueError('CP有锁快照在锁拒绝时修改原数据')
    denied_return = m.register('r0')
    if denied_return != 0:
        raise ValueError('锁拒绝路径的原返回语义与已核验4.06不符')
    # 保持旧消费者的0xc4字节完全不变，只沿原快照更新窗口改变其借用的数据源。
    copied_context = m.read(0x157c278, 0xc4)
    mutex['denied'] = False
    for row, value in ((PARAMETERS[5], 9), (PARAMETERS[6], 5)):
        m.put(WORK + 8, bytes([value]))
        m.run(row[6], arguments=(WORK,))
    m.register('r4', MASTER)
    m.run(0x4b8d88, 0x4b8dc4, returned=False)
    m.run(0x4baa9e, 0x4baaba, returned=False)
    m.run(0x9053f8, 0x905446, arguments=(WORK + 0x5000, 0x157c278), returned=False)
    if m.read(0x157c278, 0xc4) != copied_context or m.read(WORK + 0x5024, 2) != bytes([9, 5]):
        raise ValueError('CP浅复制消费者的数据借用反例不符')
    return dict(cases=cases, caller='0x4b8d88..0x4b8dc4', snapshot_function='0x898548',
                native_memcpy='ARM 0x5f51bc', semaphore_events=m.semaphore_events,
                denied_copy_preserves_previous=True, denied_path_return_r0=denied_return,
                borrowed_context_counterexample=dict(context_bytes_unchanged=True,
                    old_consumer_reads_new_sharpness=9, old_consumer_reads_new_fineness=5,
                    concurrent_worker_was_not_run=True, deep_snapshot_or_lifetime_required=True),
                mutex_backend='explicit ownership model for 0x24, not native RTOS',
                outer_dispatcher_scheduling_verified=False, frame_release_proven=False,
                fixture_boundaries=['caller registers/stack', 'semaphore ownership model',
                                    'notification events supplied by offline driver'])


def worker_completion_tails(cp):
    cases = []
    for name, consumer, prefix_end, destination, callback, tail, selector, identity in (
            ('color', 0x7195d6, 0x719604, 0x1214e98, 0x1214f5c, 0x71968a, 0x198d5ca, 3),
            ('sharpness', 0x9071cc, 0x9071fa, 0x157c278, 0x157c33c, 0x907280, 0x19c98b2, 6)):
        for selected in (0, 1):
            m = CpMachine(cp)
            m.map_ram(destination & ~4095, 0x1000)
            m.map_ram(selector & ~4095, 0x1000)
            m.map_ram(PENDING & ~4095, 0x1000)
            source, packet = WORK + 0x1000, WORK + 0x2000
            m.run(0xafd2da, arguments=(WORK + 0x4000, source))
            m.put(packet, struct.pack('<5I', 0x60daa5, 0, 0x4bf3e1, 0, 0))
            m.run(consumer, prefix_end, arguments=(source, packet, identity), returned=False)
            m.put(PENDING, struct.pack('<13I', *([1] * 13)))
            m.put(selector, bytes([selected]))
            m.register('r4', destination)
            m.register('r5', selector)
            m.put(STACK + 0xe000, struct.pack('<4I', 0, 0, 0, STOP | 1))
            m.run(tail, returned=False)
            expected = [1] * 13
            expected[identity] = 0
            if m.read(PENDING, 52) != struct.pack('<13I', *expected) or m.read(selector, 1) != bytes([selected ^ 1]):
                raise ValueError('CP任务尾部原切换/回调链不符')
            if m.register('sp') != STACK + 0xe010:
                raise ValueError('CP任务尾部栈夹具未正确消费')
            cases.append(dict(name=name, selected_before=selected, selected_after=selected ^ 1,
                              callback_packet=hex(callback), identity=identity,
                              callback_thunk_and_common_callback_executed=True,
                              worker_body_executed=False, fixture='tail entry registers and saved stack'))
    return dict(cases=cases, frame_release_proven=False,
                interpretation='parameter buffer switch and callback tail only, not JPG release')


def jpeg_callback(cp):
    label = b'EncCallbackEnd_JPG\0'
    if cp[0x4831f4-CP_BASE:0x4831f4-CP_BASE+len(label)] != label:
        raise ValueError('JPEG回调来源文字前像不符')
    cases = []
    for first, second in ((0, 123), (0x80000001, 0)):
        m = CpMachine(cp)
        record, mask = WORK + 0x1000, 0x10
        m.word(record, mask)
        m.put(record - 4, b'\xa5' * 4)
        m.put(record + 12, b'\x5a' * 4)
        first_window = m.run(0x4831b4, arguments=(first, second, record), stop_before=(0xb0d154,))
        if first_window['status'] != 'STOPPED_BEFORE_BOUNDARY' or m.read(record, 12) != struct.pack('<3I', mask, first, second):
            raise ValueError('JPEG原回调未保存输入状态字')
        # 第二独立窗口从日志调用后开始；r4来自前一原窗口，不运行日志或事件服务。
        second_window = m.run(0x4831cc, stop_before=(0x5c01ec,), returned=False)
        if second_window['status'] != 'STOPPED_BEFORE_BOUNDARY' or m.register('r0') != 0x2f or m.register('r1') != mask:
            raise ValueError('JPEG原回调未准备正确事件身份/掩码')
        if m.read(record - 4, 4) != b'\xa5' * 4 or m.read(record + 12, 4) != b'\x5a' * 4:
            raise ValueError('JPEG原回调状态保存越界')
        cases.append(dict(input_words=[first, second], stored_offsets=[4, 8],
                          event_id='0x2f', event_mask=mask, event_service_executed=False,
                          diagnostic_executed=False))
    return dict(entry='0x4831b4', source_label='EncCallbackEnd_JPG', source_label_address='0x4831f4',
                cases=cases, hardware_callback_observed=False, status_word_semantics_fully_proven=False,
                frame_release_proven=False, fixture_boundaries=['callback input words',
                    'user record', 'independent windows around diagnostic call'])


def jpeg_retirement(cp):
    m = CpMachine(cp)
    output, holder, node, resource = WORK + 0x1000, WORK + 0x2000, WORK + 0x3000, WORK + 0x4000
    m.word(holder, node)
    m.word(resource + 0x28, 2)
    m.word(resource + 0x24, 17)
    m.put(node + 0xc, b'\x01\x01')
    m.run(0xae2afa, arguments=(output, resource, holder))
    if m.read(output, 1) != b'\x01' or m.word(resource + 0x28) != 1 or m.read(node + 0xc, 2) != b'\x00\x01':
        raise ValueError('JPEG资源计数/记录退役分支不符')
    if m.word(resource + 0x24) != 17:
        raise ValueError('未到最后请求时错误移除JPEG资源身份')
    pool, item, old = WORK + 0x5000, WORK + 0x6000, WORK + 0x7000
    m.word(pool, old)
    m.word(pool + 8, 2)
    m.register('r4', pool)
    m.register('r5', item)
    m.run(0xae3fd4, 0xae3fe0, returned=False)
    if m.word(item) != old or m.word(pool) != item or m.word(pool + 8) != 3:
        raise ValueError('JPEG原资源池归还窗口不符')
    return dict(retirement_entry='0xae2afa', outstanding_before=2, outstanding_after=1,
                output_ready_byte=1, resource_identity_kept=True,
                virtual_wait_not_called=True, resource_pool_return_window='0xae3fd4..0xae3fe0',
                original_linked_list_update_executed=True, frame_release_proven=False,
                fixture_boundaries=['resource/node shape and count', 'node retained flag',
                                    'pool lock precondition; lock service not executed'],
                outer_jpg_calls=['0x472f22 -> 0x466174', '0x472f68 -> 0x466174',
                                 '0x473048 -> 0x462110', '0x473062 -> 0xae3f6a',
                                 '0x473072 -> 0x462110', '0x473092 -> 0xae3f6a'])


def collect(cp):
    require_source(cp, CP_SHA, 'CP')
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
    return dict(schema='a7r5-cp-realtime-evidence/1', cp_sha256=CP_SHA,
                completion_flags=completion_flags(cp), consumer_copies=consumer_copies(cp),
                operation_contexts=operation_contexts(cp),
                queue_rejection=queue_rejection(cp),
                runtime_refresh=runtime_refresh(cp),
                worker_completion_tails=worker_completion_tails(cp), jpeg_callback=jpeg_callback(cp),
                jpeg_retirement=jpeg_retirement(cp),
                windows={hex(a): instructions(md, cp[a-CP_BASE:a-CP_BASE+n], a)
                         for a, n in ((0x4bf3e0, 34), (0x4bdf54, 48), (0xafc7d4, 26),
                                      (0x71965a, 86), (0x23091c, 160), (0xb054f6, 60),
                                      (0x4b8d88, 60), (0x898548, 118),
                                      (0x4831b4, 64), (0x472f08, 98), (0x473040, 86),
                                      (0xae2afa, 122), (0xae3f6a, 68), (0xae3fd4, 12))},
                gates=dict(realtime_update=False, live_view=False, jpg=False, frame_release=False),
                camera_io=False, hardware_acknowledgement_synthesized=False,
                firmware_modified=False)
