"""原网格控制器的选择、缓存和发布证据；只运行锁定CP的匿名副本。"""
import hashlib
import struct

from .access_evidence import CP_SHA, require_source
from .cp_machine import CpMachine, WORK
from .investigate import CP_BASE

ENTRY, PREFIX, TABLE = 0x230da8, 0x11952c0, 0x11952e0
FACTORY = (0, 3, 2, 1, 16, 15, 17, 18, 5, 13, 19, 20)


def setup(cp, marker, bank=0, profile=0, level=8):
    m = CpMachine(cp)
    for at, size in ((0x16af000, 0x1000), (0x16b0000, 0x2000),
                     (0x16ba000, 0x1000), (0x198c000, 0x2000)):
        m.map_ram(at, size)
    p = {name: WORK + off for name, off in dict(wrapper=0x100, params=0x400,
        profile=0x800, container=0xc00, grid_state=0x1000, stage=0x1400,
        output_context=0x1800, flags=0x2800, out=0x4000).items()}
    for at, value in ((p['wrapper'], p['params']), (p['wrapper']+4, p['profile']),
        (p['container']+8, p['grid_state']), (p['container']+12, p['output_context']),
        (p['container']+16, p['stage']), (p['container']+20, p['flags']),
        (p['output_context']+0x6b0, p['out'])):
        m.word(at, value)
    m.put(p['params']+1, bytes([int(bank != 0)]))
    m.put(p['profile']+12, bytes([0 if bank == 0 else 11 if bank == 1 else 8]))
    m.put(p['profile']+6, bytes([profile]))
    m.put(p['params']+0x2e, bytes([marker, level]))
    # 无原厂网格来源/硬件句柄；保留6款已存在的原选择助手。
    m.put(p['grid_state']+4, b'\xff')
    m.put(p['out']-16, b'\xa5'*(3*1620+32))
    return m, p


def packed(cp, raw, level=8):
    permutation = struct.unpack_from('<405H', cp, 0xd841d8)
    coefficients = struct.unpack('1215b', raw)
    out = [0]*405
    for source, destination in enumerate(permutation):
        out[destination] = sum((((coefficients[c*405+source]*level)//8) & 127)
                               << (22-10*c) for c in range(3))
    return struct.pack('<405I', *out)


def execute(m, p):
    m.run(ENTRY, arguments=(p['wrapper'], p['container']), limit=200000)
    return sum(p['out'] <= int(w['address'], 0) < p['out']+3*1620 for w in m.writes)


def fnv(raw):
    value = 2166136261
    for byte in raw:
        value = ((value ^ byte)*16777619) & 0xffffffff
    return value


def collect(cp, candidate):
    require_source(cp, CP_SHA, 'CP')
    if len(candidate) != 1215 or any(not -64 <= x <= 63 for x in struct.unpack('1215b', candidate)):
        raise ValueError('原控制器候选必须是1215字节七位网格')
    if struct.unpack_from('<2I', cp, PREFIX-CP_BASE) != (0x364c3741, 0x10006):
        raise ValueError('当前六款原生网格头不符')
    original = [cp[TABLE-CP_BASE+i*1215:TABLE-CP_BASE+(i+1)*1215] for i in range(6)]
    if candidate == original[0]:
        raise ValueError('缓存替换证据需要可区分的新候选')
    selected, blocked = [], []
    for slot in range(6):
        expected = packed(cp, original[slot])
        for bank in range(3):
            m, p = setup(cp, 249+slot, bank)
            try:
                writes = execute(m, p)
                if bank != 0:
                    # 原查询句柄为空时返回4；现有桥只允许参数模式0绕过此门控。
                    if (writes or m.word(p['grid_state']+0x20) or
                            m.read(p['out'], 3*1620) != b'\xa5'*(3*1620)):
                        raise ValueError('原查询缺失时模式1的控制器意外发布网格')
                    blocked.append(dict(marker=249+slot, native_index=bank, query_result=4,
                                        packed_words=0, pointer_published=False))
                    continue
                if writes != 405:
                    raise ValueError('原控制器未首次生成405个网格字')
                destination = p['out']+bank*1620
                if (m.word(p['grid_state']+0x184) != TABLE+slot*1215 or
                    m.read(p['grid_state']+0x188, 2) != b'\x01\x02' or
                    m.word(p['grid_state']+0x20) != destination or
                    m.read(p['grid_state']+0x24, 1) != b'\x01' or
                    m.read(destination, 1620) != expected or
                    m.read(p['out']-16, 16) != b'\xa5'*16 or
                    m.read(p['out']+3*1620, 16) != b'\xa5'*16):
                    raise ValueError('原控制器网格选择/原段发布/边界不符')
                for other in range(3):
                    if other != bank and m.read(p['out']+other*1620, 1620) != b'\xa5'*1620:
                        raise ValueError('原控制器覆盖了非目标缓冲段')
                if execute(m, p) != 0 or m.read(destination, 1620) != expected:
                    raise ValueError('同参数第二次原控制器没有复用缓存')
                selected.append(dict(marker=249+slot, native_index=bank, words=405,
                    pointer_published=True, second_call_packed_words=0, other_segments_preserved=True))
            finally:
                m.cpu = None
    delegated = []
    for marker in (*FACTORY, 248, 255):
        m, p = setup(cp, marker)
        try:
            if execute(m, p) or m.word(p['grid_state']+0x184) or m.word(p['grid_state']+0x20):
                raise ValueError('原厂/未知身份意外应用六款网格')
            delegated.append(marker)
        finally:
            m.cpu = None
    rejected = []
    for name, address in (('magic', PREFIX), ('version', PREFIX+4), ('slot_fnv', PREFIX+8)):
        m, p = setup(cp, 249)
        try:
            m.enable_initialized_data(0x1195000, 0x1000)
            m.word(address, m.word(address) ^ 1)
            if execute(m, p) or m.word(p['grid_state']+0x184):
                raise ValueError('原控制器应用了损坏网格头/摘要')
            rejected.append(name)
        finally:
            m.cpu = None
    m, p = setup(cp, 249)
    try:
        if execute(m, p) != 405:
            raise ValueError('替换前原网格没有生成')
        previous = m.read(p['out'], 1620)
        m.enable_initialized_data(0x1195000, 0x1000)
        # 仅改匿名副本中的首表及其摘要，模拟同槽内容更换；不修改输入映像。
        m.put(TABLE, candidate)
        m.word(PREFIX+8, fnv(candidate))
        stale = execute(m, p)
        if stale or m.read(p['out'], 1620) != previous:
            raise ValueError('未复现同槽内容更新但原参数缓存不失效')
        # 原判定比较output_context+0x54+index；研究夹具仅失效当前原段。
        m.put(p['output_context']+0x54, b'\xff')
        if execute(m, p) != 405 or m.read(p['out'], 1620) != packed(cp, candidate):
            raise ValueError('原缓存单段失效后没有重新打包新候选')
        refreshed = m.read(p['out'], 1620)
        if refreshed == previous or execute(m, p) != 0:
            raise ValueError('重新打包后未恢复原缓存复用')
        m.put(p['params']+0x2f, b'\x07')
        level_without_source = execute(m, p)
        if level_without_source or m.read(p['out'], 1620) != refreshed:
            raise ValueError('无原来源0xff夹具的强度缓存抑制行为改变')
        m.put(p['output_context']+0x54, b'\xff')
        if execute(m, p) != 405 or m.read(p['out'], 1620) != packed(cp, candidate, 7):
            raise ValueError('原段失效后没有按新强度打包候选')
        replacement = dict(same_slot_new_table_without_invalidation_words=stale,
            stale_bytes_preserved=True, per_segment_cache_byte='output_context+0x54+native_index',
            invalidated_index=0, refreshed_words=405, second_call_words=0,
            null_source_level_change_words=level_without_source,
            level_after_explicit_invalidation_words=405, native_level=7,
            candidate_sha256=hashlib.sha256(candidate).hexdigest(),
            packed_sha256=hashlib.sha256(refreshed).hexdigest())
    finally:
        m.cpu = None
    m, p = setup(cp, 249)
    try:
        # 原来源分类0具备不同的强度失效规则；不用0xff夹具推广到全部机身状态。
        m.put(p['grid_state']+4, b'\0')
        if execute(m, p) != 405:
            raise ValueError('原来源0没有生成首张自定义网格')
        m.put(p['params']+0x2f, b'\x07')
        if execute(m, p) != 405 or m.read(p['out'], 1620) != packed(cp, original[0], 7):
            raise ValueError('原来源0没有沿用原强度自动更新')
        level_update = dict(source_class=0, new_level=7, packed_words=405,
                            explicit_invalidation=False)
    finally:
        m.cpu = None
    m, p = setup(cp, 249, profile=1)
    try:
        execute(m, p)
        if (m.read(p['output_context']+0x5c, 1620) != packed(cp, original[0]) or
                m.word(p['grid_state']+0x20) != p['output_context']+0x5c):
            raise ValueError('原profile字节1的内嵌输出通路不符')
    finally:
        m.cpu = None
    return dict(status='OFFLINE_NATIVE_GRID_CONTROLLER_VERIFIED', entry=hex(ENTRY),
        cp_sha256=CP_SHA, existing_custom_markers=selected, missing_query_modes_blocked=blocked,
        factory_and_unknown_delegated=delegated,
        invalid_headers_rejected=rejected, replacement=replacement, native_level_update=level_update,
        profile_one_inline_buffer='output_context+0x5c', original_calls_executed=True,
        hardware_query_handles=0, service_callbacks_intercepted=0,
        cache_invalidation_installed=False, new_slot_selector_installed=False,
        actual_isp_upload_verified=False, evf_jpg_identity_verified=False, frame_release_verified=False,
        fixture_boundaries=['wrapper/parameters/profile/container shapes', 'zero feature/debug globals',
            'no original LUT source: grid_state+4=255', 'null original hardware query handles',
            'three anonymous output segments', 'one anonymous first-table/checksum replacement'],
        camera_io=False, input_modified=False)
