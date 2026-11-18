"""三种固定保留布局的严格前像、纯内存应用与逆变换；没有CP/DAT写出入口。"""
from pathlib import Path
import hashlib
import importlib.util
import json
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
sys.path.insert(0, str(ROOT/'a7r5-desktop/prepared/engine/site'))
from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB

BASE = 0x108000
CP_SHA = '18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
COLD = 0x11cf000
RX = 0x2afc000
RW = 0x2aff000
PHASE = 0x1a3ac60
TAIL = 0xbef9e8
SOLID = 0xe7d164
CAPTURE_REGIONS = (('format', 0xbef524, 26), ('rsource', 0xbef582, 6),
                   ('color', 0xbef65a, 6), ('rsource_record', 0xbef678, 8), ('pool', 0xbef69c, 20),
                   ('release', 0xbef6ec, 20), ('factor', 0xbef838, 400), ('checker', 0xbef5c0, 96))
CAPTURE_BEFORE = ('659d36ca563ba4622daabb36a71dafaf6060cdcbf89bb12e75426198496d272c',
    'b0f66adc83641586656866813fd9dd0b8ebb63796075661ba45d1aa8089e1d44',
    'b0f66adc83641586656866813fd9dd0b8ebb63796075661ba45d1aa8089e1d44',
    'af5570f5a1810b7af78caf4bc70a660f0df51e42baf91d4de5b2328de0e83dfc',
    'de47c9b27eb8d300dbb5f2c353e632c393262cf06340c4fa7f1b40c4cbd36f90',
    'de47c9b27eb8d300dbb5f2c353e632c393262cf06340c4fa7f1b40c4cbd36f90',
    'd951593a570e83c7c31b32ab893175a5f76a24c0fc61b811d5d1ae6eddd44131',
    '82025b3afa761c0a9a04fc83d64ecd8b23c965499f692d59ff9be082050836b2')
CAPTURE_CALLS = {0x45bc80: 'birth', 0x45be6c: 'birth', 0x48d700: 'rebuild', 0x48d8b4: 'rebuild',
                 0x46e65a: 'restore', 0x335e56: 'reverse', 0x872682: 'gamma', 0x45c09a: 'release',
                 0xadf96c: 'pool', 0xadfd2c: 'pool', 0xae038c: 'pool', 0xaa7f08: 'format',
                 0xadd846: 'rsource', 0x24d32a: 'color', 0x24daba: 'color', 0x73e8dc: 'color', 0x73e94e: 'color',
                 0x73e9ba: 'color', 0x73ea62: 'color', 0x73ea68: 'color', 0x73ea8c: 'color',
                 0x73f10e: 'color', 0x73f174: 'color', 0x73f1e4: 'color', 0x73f278: 'color',
                 0x73f2e6: 'color', 0x73f362: 'color', 0x73f394: 'color', 0x73f3f4: 'color',
                 0x73f494: 'color', 0x73f4c6: 'color', 0x71d6ec: 'matrix9'}
CAPTURE_TAIL_CALLS = frozenset((0x73e9ba, 0x73ea62, 0x73ea68, 0x73ea8c, 0x73f494))
CAPTURE_FALLBACK = {'birth': 0xae0317, 'restore': 0x833cb5, 'rebuild': 0xaebdc3,
                    'reverse': 0x845cf5, 'gamma': 0x845db9, 'release': 0xae0361,
                    'pool': 0xae07e1, 'format': 0xaa81cb, 'rsource': 0x4596f5, 'color': 0x719ef7, 'matrix9': 0x71eccd}
NATIVE_THUMB_COPIES = (0x898568, 0x4baab6, 0x4bba78, 0x4bc002, 0x884766,
                      0x719600, 0x9071f6, 0x313c70, 0xaa6978, 0xadf128)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def capture_regions(receipt, native):
    """独立限定已批准范围，不能由构建helper扩大可写白名单。"""
    if type(receipt.get('capture_lifecycle')) is not bool or receipt['capture_lifecycle'] != native:
        raise ValueError('Capture生命周期与原生分支不配对')
    rows = receipt.get('capture_regions')
    symbols = receipt.get('capture_symbols')
    if not isinstance(rows, list) or not isinstance(symbols, dict):
        raise ValueError('Capture段或符号回执类型错误')
    if not native:
        if rows or symbols:
            raise ValueError('基础分支不接受Capture局部段或符号')
        return rows
    if len(rows) != 8 or not symbols:
        raise ValueError('Capture必须恰为八个已批准局部段')
    for row, (name, address, size), before in zip(rows, CAPTURE_REGIONS, CAPTURE_BEFORE):
        if (not isinstance(row, dict) or row.get('name') != name
                or type(row.get('address')) is not int or row['address'] != address
                or type(row.get('bytes')) is not int or row['bytes'] != size
                or row.get('before_sha256') != before):
            raise ValueError('Capture地址、顺序、长度或前像超出已批准范围')
    return rows


def arm_blx(address, target):
    if address & 3 or not target & 1:
        raise ValueError('ARM BLX地址或Thumb状态错误')
    delta = (target & ~1)-(address+8)
    if delta & 1 or not -(1 << 25) <= delta < 1 << 25:
        raise ValueError('ARM BLX距离越界')
    raw = struct.pack('<I', 0xfa000000 | ((delta >> 2) & 0xffffff) | ((delta & 2) << 23))
    decoded = list(Cs(CS_ARCH_ARM, CS_MODE_ARM).disasm(raw, address))
    if len(decoded) != 1 or decoded[0].mnemonic != 'blx' or int(decoded[0].op_str[1:], 16) != target & ~1:
        raise ValueError('ARM BLX独立解码不符')
    return raw


def jump(target, thumb=True):
    if not target & 1:
        raise ValueError('绝对跳转目标不是Thumb')
    return (bytes.fromhex('dff800f0') if thumb else bytes.fromhex('04f01fe5'))+struct.pack('<I', target)


def thumb_branch(address, target, link=False):
    if address & 1 or not target & 1:
        raise ValueError('Thumb分支地址或状态错误')
    delta = (target & ~1)-(address+4)
    if delta & 1 or not -(1 << 24) <= delta < (1 << 24):
        raise ValueError('Thumb分支超出16MiB')
    sign = (delta >> 24) & 1
    first = 0xf000 | sign << 10 | (delta >> 12) & 0x3ff
    second = (0xd000 if link else 0x9000) | ((~((delta >> 23) ^ sign) & 1) << 13) | ((~((delta >> 22) ^ sign) & 1) << 11) | (delta >> 1) & 0x7ff
    raw = struct.pack('<HH', first, second)
    decoded = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(raw, address))
    if len(decoded) != 1 or decoded[0].mnemonic != ('bl' if link else 'b.w') or int(decoded[0].op_str[1:], 16) != target & ~1:
        raise ValueError('Thumb分支独立解码不符')
    return raw


def create_plan(cp, build):
    if len(cp) != 17617008 or sha(cp) != CP_SHA:
        raise ValueError('修改版4.06 CP身份不符')
    build = Path(build).resolve()
    receipt_raw = (build/'verification.json').read_bytes()
    receipt = json.loads(receipt_raw)
    if receipt.get('status') != 'CARVE_LINK_PASS_OFFLINE_ONLY':
        raise ValueError('不是固定保留布局构建回执')
    builder = load_module(HERE/'build.py', 'af_carve_build_checked')
    native = receipt.get('native_integration')
    native_capacity = receipt.get('native_capacity')
    if type(native_capacity) is not bool or type(native) is not bool or (native and not native_capacity):
        raise ValueError('容量布局必须是固定分支布尔组合')
    # 审计独立固定地址/页数，不能信任构建器或回执自行扩大可写范围。
    rx_address, rw_address, cold_address, rx_pages, rw_pages, version, cold_before = (
        (0x2aea000, 0x2af4000, 0x11c8000, 10, 12, 'capture-color-22-v1',
         '02b1c2234680617802901a77eae606ad02e4ddb4282ccbc60061eac5b2d90bba') if native else
        (0x2aec000, 0x2af4000, 0x11ca000, 8, 12, 'native-capacity-20-v1',
         'c35020473aed1b4642cd726cad727b63fff2824ad68cedd7ffb73c7cbd890479') if native_capacity else
        (0x2afc000, 0x2aff000, 0x11cf000, 3, 1, 'legacy-4-v1',
         'f3cc103136423a57975750907ebc1d367e2985ac6338976d4d5a439f50323f4a'))
    layout = dict(rx=rx_address, rw=rw_address, cold=cold_address, rx_pages=rx_pages, rw_pages=rw_pages,
                  rx_capacity=rx_pages*4096, rw_capacity=rw_pages*4096,
                  solid_size=rx_address-0x128000, pte_bias=((rx_address & 0xfffff) >> 10)-1)
    recorded_layout = receipt.get('capacity_layout')
    if (not isinstance(recorded_layout, dict) or recorded_layout != layout
            or any(type(recorded_layout.get(k)) is not int for k in layout)
            or builder.capacity_layout(native_capacity, native) != layout
            or receipt.get('cold_source') != layout['cold']
            or receipt.get('capacity_layout_version') != version
            or type(receipt.get('reserved_bytes')) is not int
            or receipt['reserved_bytes'] != (rx_pages+rw_pages)*4096
            or type(receipt.get('cold_source_bytes')) is not int
            or receipt['cold_source_bytes'] != rx_pages*4096
            or receipt.get('cold_source_before_sha256') != cold_before):
        raise ValueError('构建容量布局与固定分支不符')
    schema = receipt.get('native_asset_schema')
    if type(schema) is not int or schema != (3 if receipt['native_capacity'] else 1):
        raise ValueError('配方schema与固定容量布局不配对')
    asset_commands = [c['argv'] for c in receipt['commands']
                      if str(ROOT/'a7r5-firmware-features/custom-filters/native/af_joint_asset.c') in c['argv']]
    legacy = ['-DAF_JOINT_ASSET_LEGACY_ONLY406=1'] if schema == 1 else []
    if (len(asset_commands) != 1 or [a for a in asset_commands[0]
            if a.startswith('-DAF_JOINT_ASSET_LEGACY_ONLY406')] != legacy):
        raise ValueError('实际配方编译flag与schema不一致')
    capture = receipt['capture_input']
    copies = receipt['capture_copies']
    if type(native) is not bool or (native and (not capture or not copies or not receipt['native_capacity'])):
        raise ValueError('原生接线必须与Capture颜色二十二页和完整copy模式配对')
    if type(capture) is not bool or type(copies) is not bool or (copies and not capture):
        raise ValueError('快照模式类型不符')
    capture_rows = capture_regions(receipt, native)
    snapshot_patchsite = 0x898568 if capture else 0x89856c
    if receipt['snapshot_patchsite'] != snapshot_patchsite:
        raise ValueError('实际快照patchsite与构建模式不一致')
    expected_copy_sites = (list(builder.THUMB_COPY_SITES+builder.ARM_COPY_SITES) if native else
                           [0x898568, 0x4baab6, 0x4bba78, 0x4bc002] if copies else [])
    if receipt['copy_sites'] != expected_copy_sites or receipt['compact_copy'] != ('af_cp_copy406_gate' if copies else None):
        raise ValueError('实际copy sites与构建模式不一致')
    snapshot_core = 'af_cp_copy406_gate' if copies else 'af_cp_override406_snapshot_copy_gate' if capture else 'af_cp_override406_snapshot_gate'
    if receipt['snapshot_core_symbol'] != snapshot_core:
        raise ValueError('实际快照core符号与模式不一致')
    # 只核接线宏，不要求统一LTO策略：native C全LTO、memory/合同非LTO均合法。
    native_flags = ['-DAF_CP_NATIVE406=1', '-DAF_CP_NATIVE_JOBS406=1',
                    '-DAF_CP_COMPONENTS406_TARGET=1', '-DAF_CP_CAPTURE406=1']
    for name in ('af_hs_cp406.c', *builder.NATIVE_SOURCES):
        compiled = [c['argv'] for c in receipt['commands'] if str(ROOT/'a7r5-firmware-features/custom-filters/native'/name) in c['argv']]
        if native and len(compiled) != 1:
            raise ValueError('原生接线缺少真实生产源码编译')
        if not native and name != 'af_hs_cp406.c' and compiled:
            raise ValueError('未启用原生接线却编入原生生产源码')
        if any(any((flag in argv) != native for flag in native_flags) for argv in compiled):
            raise ValueError('实际原生宏与接线模式不符')
    for name, digest in receipt['source_sha256'].items():
        if sha((ROOT/name).read_bytes()) != digest:
            raise ValueError('构建源码已变化: '+name)
    for name, digest in receipt['generated_sha256'].items():
        if sha(Path(name).read_bytes()) != digest:
            raise ValueError('实际编译输入已变化: '+name)
    artifact = receipt['artifact']
    module_raw = Path(artifact['path']).read_bytes()
    if len(module_raw) != artifact['bytes'] or sha(module_raw) != artifact['sha256']:
        raise ValueError('模块ELF摘要不符')
    elf, module_symbols = builder.inspect(module_raw)
    segments = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    if len(segments) != 2 or len(receipt['payloads']) != 2:
        raise ValueError('模块段数错误')
    payloads = []
    for seg, item, address, capacity, flags in zip(segments, receipt['payloads'], (layout['rx'], layout['rw']),
                                                 (layout['rx_capacity'], layout['rw_capacity']), (5, 6)):
        if seg['p_vaddr'] != address or seg['p_flags'] != flags or not 0 < seg['p_filesz'] <= seg['p_memsz'] <= capacity:
            raise ValueError('模块段布局或权限错误')
        full = seg.data()+bytes(seg['p_memsz']-seg['p_filesz'])
        if Path(item['path']).read_bytes() != full or item['bytes'] != len(full) or item['sha256'] != sha(full):
            raise ValueError('载荷与ELF不一致')
        payloads.append(full)
    rx, rw = payloads
    if (receipt.get('rw_statics_bytes') != module_symbols['__af_carve_rw_statics_end']-layout['rw']
            or receipt.get('rw_resident_bytes') != len(rw)
            or (receipt['native_capacity'] and len(rw) != layout['rw_capacity'])):
        raise ValueError('实际驻留RW或静态使用量不符')
    if rw != b'\xfe\xff\xff\xff'+bytes(len(rw)-4):
        raise ValueError('不支持的RW初始化内容')
    boot_raw = (build/'bootstrap/bootstrap.elf').read_bytes()
    boot_elf, symbols = builder.inspect(boot_raw)
    sec = boot_elf.get_section_by_name('.text')
    boot = (build/'bootstrap/bootstrap-rx.bin').read_bytes()
    if sec['sh_addr'] != TAIL or sec.data() != boot or not 0 < len(boot) <= 408 or sha(boot) != receipt['bootstrap_sha256']:
        raise ValueError('408B引导身份或容量错误')
    if receipt['snapshot_entry'] != symbols['af_carve_snapshot'] or not symbols['af_carve_snapshot'] & 1:
        raise ValueError('快照入口不配对')
    if any(symbols[k] != v for k, v in receipt['bootstrap_symbols'].items()):
        raise ValueError('引导symbol回执漂移')
    if any(module_symbols[k] != v for k, v in receipt['module_symbols'].items()):
        raise ValueError('模块symbol回执漂移')
    snapshot_offset = symbols['snapshot_target']-TAIL
    if struct.unpack_from('<I', boot, snapshot_offset)[0] != module_symbols[snapshot_core]:
        raise ValueError('快照实际tail literal未绑定所需core入口')
    desc = symbols['af_carve_descriptors']-TAIL
    expected_desc = struct.pack('<10I', 2, 15, layout['rx'], layout['rw'], layout['rx'],
                                2, 12, layout['rw'], 0x2b00000, layout['rw'])
    if boot[desc:desc+40] != expected_desc:
        raise ValueError('缺少type2物理RX/RW-XN描述符')
    factor_raw = b''
    factor_symbols = {}
    capture_symbols = {}
    capture_blob = b''
    capture_payloads = []
    native_hooks = []
    if native:
        factor_elf, factor_symbols = builder.inspect((build/'factor/factor.elf').read_bytes())
        section = factor_elf.get_section_by_name('.text')
        factor_raw = (build/'factor/factor-rx.bin').read_bytes()
        if (section['sh_addr'] != builder.FACTOR or section.data() != factor_raw
                or len(factor_raw) != 288 or sha(factor_raw) != receipt['factor_sha256']):
            raise ValueError('永久factor必须是配对真实ELF的原288B范围')
        if any(factor_symbols.get(k) != v for k, v in receipt['factor_symbols'].items()):
            raise ValueError('永久factor符号回执漂移')
        for at, name in ((0xbef74c, 'factor_matrix_original_call'), (0xbef7ac, 'factor_primary_original_call'),
                         (0xbef80c, 'factor_secondary_original_call')):
            if factor_symbols[name] != at or factor_raw[at-builder.FACTOR:at-builder.FACTOR+4] != cp[at-BASE:at-BASE+4]:
                raise ValueError('旧三个原BL位置、指令或LR被改变')
        if sha(cp[builder.FACTOR-BASE:builder.FACTOR-BASE+288]) != '62399f57d5cbfea28c86e7bfda1836b102cc19210ba99b18fc23e4f83639be10':
            raise ValueError('旧288B包装器完整前像不符')
        records = {'matrix_record': ('native_matrix_target', factor_symbols['factor_matrix']),
                   'primary_record': ('native_primary_target', factor_symbols['factor_primary']),
                   'gamma_record': ('native_gamma_target', 0xbef8e1),
                   'grid_record': ('native_grid_target', 0xbef551),
                   'source_record': ('native_gamma_source_target', 0xaacb17),
                   'reset_record': ('native_gamma_reset_target', 0xaa6413)}
        for record, (target, fallback) in records.items():
            actual = struct.unpack_from('<2I', factor_raw, factor_symbols[record]-builder.FACTOR)
            if actual != (module_symbols[builder.NATIVE_TARGETS[target]], fallback):
                raise ValueError('永久gate未绑定实际native目标和精确旧回退')
        phase_site = factor_symbols['permanent_phase'] & ~1
        first = next(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(factor_raw[phase_site-builder.FACTOR:phase_site-builder.FACTOR+2], phase_site))
        if first.mnemonic != 'ldr' or not first.op_str.startswith('r1, [pc, #'):
            raise ValueError('永久phase读取不是精确16位LDR')
        literal = ((phase_site+4) & ~3)+int(first.op_str.split('#')[1].split(']')[0], 16)
        if (literal != symbols['phase'] or receipt['factor_phase_literal'] != literal
                or struct.unpack_from('<H', factor_raw, phase_site-builder.FACTOR)[0] != receipt['factor_phase_opcode']
                or struct.unpack_from('<I', boot, literal-TAIL)[0] != PHASE):
            raise ValueError('永久phase literal未与最终bootstrap精确配对')
        if (builder.CAPTURE.REGIONS != CAPTURE_REGIONS or builder.CAPTURE.CALLS != CAPTURE_CALLS
                or builder.CAPTURE.FALLBACK != CAPTURE_FALLBACK or builder.CAPTURE.TAIL_CALLS != CAPTURE_TAIL_CALLS
                or builder.NATIVE_HOOK_COUNT != 51
                or builder.THUMB_COPY_SITES != NATIVE_THUMB_COPIES
                or builder.ARM_COPY_SITES != (0x5c36e0, 0x5c3860, 0x5c3888)
                or builder.CAPTURE_BYTES != 582 or builder.CAPTURE_STORAGE_BYTES != 584
                or builder.NATIVE_CONTRACT_BYTES != 1280):
            raise ValueError('Capture规范布局、32条原分支或1280B合同被改变')
        capture_elf, capture_symbols = builder.inspect((build/'capture/capture.elf').read_bytes())
        recorded_symbols = {k: v for k, v in capture_symbols.items() if k and not k.startswith('$')}
        if receipt['capture_symbols'] != recorded_symbols:
            raise ValueError('Capture实际ELF符号回执漂移')
        builder.CAPTURE.validate(cp, capture_elf, capture_symbols, module_symbols, factor_symbols, capture_rows)
        # 只使用已读取并校验的ELF字节；合同检查后不得重新读可能变化的.bin文件。
        capture_payloads = [capture_elf.get_section_by_name('.capture_'+row['name']).data() for row in capture_rows]
        capture_blob = b''.join(capture_payloads)
        if len(capture_blob) != 582:
            raise ValueError('Capture八段合同必须为582字节')
        native_hooks = builder.native_hotpatches(symbols['af_carve_snapshot'], factor_symbols, capture_symbols)
        if receipt['native_hooks'] != [dict(address=a, code=b.hex()) for a, b in native_hooks]:
            raise ValueError('原生挂点不匹配实际target')
        expected_contract = factor_raw+capture_blob+bytes(2)+b''.join(struct.pack('<I', a)+b for a, b in native_hooks)
        start = module_symbols['af_cp_native406_factor_expected']
        if (receipt['native_contract_bytes'] != 1280 or len(native_hooks) != 51
                or module_symbols['af_cp_native406_capture_expected'] != start+288
                or module_symbols['af_cp_native406_hooks'] != start+288+584
                or builder.module_bytes(elf, start, builder.NATIVE_CONTRACT_BYTES) != expected_contract
                or (build/'native-contract.c').read_text() != builder.contract_source(factor_raw, native_hooks, capture_blob)):
            raise ValueError('实际1280B只读合同与factor/Capture八段/2B零pad/51挂点不一致')
        iterations = receipt['native_contract_iterations']
        if (not 2 <= len(iterations) <= 3 or iterations[-1]['text_positions_changed']
                or iterations[-1]['text_positions_sha256'] != sha(json.dumps(builder.text_symbols(elf)).encode())
                or iterations[-1]['contract_source_sha256'] != sha((build/'native-contract.c').read_bytes())):
            raise ValueError('合同未通过有限实际重链的文本地址固定点')
    elif (receipt.get('native_hooks') or receipt.get('factor_symbols') or receipt.get('factor_sha256') is not None
          or receipt.get('native_contract_bytes') != 0):
        raise ValueError('基础分支不接受原生合同或永久factor')
    header = cp[0x128000-BASE:0x12817c-BASE]
    if struct.unpack_from('<3I', header, 0x148) != (0x106f000, 0x8a3b40, 0x1197000):
        raise ValueError('原BSS描述符漂移')
    root = ((0x106f000+0x8a3b40+292+0x4fff) & ~0x3fff)+0x128000
    if root != 0x1a3c000 or not 0x1a3ab40 <= PHASE < PHASE+4 <= 0x1a3ab40+292 <= 0x1a3b000:
        raise ValueError('phase保留范围或原页表根漂移')
    solid = struct.pack('<5I', 0x128000, 0x29d8000, 2, 0xfbd3bf, 0x128000)
    if (cp[SOLID-BASE:SOLID-BASE+20] != solid
            or 0x128000+layout['solid_size'] != layout['rx']
            or 0x2b00000-layout['rx'] != (layout['rx_pages']+layout['rw_pages'])*4096
            or layout['rx']-0x2560000 != 0x5a0000-(layout['rx_pages']+layout['rw_pages'])*4096
            or not 0x256068c < layout['rx'] < layout['rw'] < 0x2b00000):
        raise ValueError('SOLID完整前像或保留边界不符')
    cold = layout['cold']
    if (cp[cold-BASE:cold-BASE+layout['rx_capacity']] != bytes(layout['rx_capacity'])
            or sha(cp[cold-BASE:cold-BASE+layout['rx_capacity']]) != cold_before
            or not 0x1197418 <= cold < cold+len(rx) <= cold+layout['rx_capacity'] == 0x11d2000 < 0x11d3000):
        raise ValueError('冷源前像、原必清范围或旧源隔离失败')
    hot = {0x5e3ed4: '10402de90000a0e3', 0x5e8178: 'e92c00eb',
           0x60800c: '0020a0e3002080e5002081e51eff2fe1', 0x495fd8: 'f0b503af2de9000f',
           0x496044: '242022f192ee3078', 0x898568: '5cf528ee', 0x89856c: '4bf2d070c0f25710'}
    if copies:
        hot.update({0x4baab6: '3af182eb', 0x4bba78: '39f1a0eb', 0x4bc002: '39f1dce8'})
    if native:
        hot.update({0x884766: '70f52aed', 0x719600: 'dbf6dced', 0x9071f6: 'edf4e2ef',
                    0x313c70: 'e1f2a4ea',0xaa6978: '4ef720e4',0xadf128: '16f748e0',
                    0x845700: '67f209fa',0xaaca82: 'f9f7c6fc',
                    0x5c36e0: 'b5c600eb', 0x5c3860: '55c600eb', 0x5c3888: '4bc600eb',
                    0x71e41e: 'd1f07bb1', 0x71e670: 'd1f082b0', 0x41363c: 'dcf350b1', 0x230f0c: 'bef1209b'})
        decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        for address, kind in CAPTURE_CALLS.items():
            original = list(decoder.disasm(cp[address-BASE:address-BASE+4], address))
            if (len(original) != 1 or original[0].size != 4
                    or original[0].mnemonic != ('b.w' if address in CAPTURE_TAIL_CALLS else 'bl')
                    or int(original[0].op_str[1:], 16) != CAPTURE_FALLBACK[kind] & ~1):
                raise ValueError('Capture原分支形式、前像或委派目标漂移: '+hex(address))
    for address, raw in hot.items():
        if cp[address-BASE:address-BASE+len(bytes.fromhex(raw))] != bytes.fromhex(raw):
            raise ValueError('原挂钩前像不符: '+hex(address))
    rows = []

    def add(address, after, reason):
        offset = address-BASE
        before = cp[offset:offset+len(after)]
        if len(before) != len(after):
            raise ValueError('补丁超出原CP文件')
        rows.append(dict(address=address, offset=offset, bytes=len(after), before=before.hex(), after=after.hex(), reason=reason))

    add(0xe7d168, struct.pack('<I', layout['solid_size']), '原SOLID尾显式扣除固定整页；STACK起点不变')
    add(0x12814c, struct.pack('<I', 0x8a3b40+292), '只保留既定phase尾；原L1/L2与全部模式栈不移动')
    add(0x5e3ed8, arm_blx(0x5e3ed8, symbols['af_carve_prepare']), '原清零之前校验冷源并复制；原PUSH保持')
    add(0x5e8178, arm_blx(0x5e8178, symbols['af_carve_cache']), '原D维护仍执行，成功时另做I维护，原TLB序列保持')
    add(0x60800c, jump(symbols['af_carve_map'], False), '原extraMap返回显式type2物理映射，未知状态返回零项')
    for address, name in ((0x495fd8, 'af_carve_start'), (0x496044, 'af_carve_hs')):
        branch = thumb_branch(address, symbols[name])
        if address == 0x496044:
            branch += bytes.fromhex('00bf')
        add(address, branch, '完整原指令窗口的B.W准入；HS完整覆盖MOVS/BLX并保留原LDRB')
    for address in expected_copy_sites if copies else [snapshot_patchsite]:
        code = arm_blx(address, symbols['af_carve_snapshot']) if address in builder.ARM_COPY_SITES else thumb_branch(address, symbols['af_carve_snapshot'], link=copies)
        add(address, code,
            '四处原memcpy以BL保留真实LR，经共用phase gate安全委派' if copies else '单条快照B.W挂钩，原复制或MOVW余部按模式回放')
    if native:
        for address, name in builder.NATIVE_ENTRIES.items():
            add(address, thumb_branch(address, factor_symbols[name]), '原组件入口只转入永久phase gate，未知状态保留旧处理')
        for address, name in builder.NATIVE_CALLS.items():
            add(address, thumb_branch(address, factor_symbols[name], link=True), '构造/初始化原BL经永久phase gate；未知状态原参原调用')
        for address, name in CAPTURE_CALLS.items():
            add(address, thumb_branch(address, capture_symbols['permanent_capture_'+name], link=address not in CAPTURE_TAIL_CALLS),
                'Capture原BL/B.W保持各自LR/栈参语义，经同次常驻门原调用一次')
        add(builder.FACTOR, factor_raw, '原三包装器保持入口/BL/LR的288B等价重排及六个永久phase gate')
        for row, raw in zip(capture_rows, capture_payloads):
            add(row['address'], raw, 'Capture规范来源的精确局部段: '+row['name'])
    add(TAIL, boot, '408B原拥有RX尾内的实际配对引导')
    add(cold, rx, '仅借原必清BSS；不触碰11d2000原候选源和旧六槽源')
    rows.sort(key=lambda row: row['offset'])
    if any(a['offset']+a['bytes'] > b['offset'] for a, b in zip(rows, rows[1:])):
        raise ValueError('补丁范围交叉')
    changed = bytearray(cp)
    for row in rows:
        i, n = row['offset'], row['bytes']
        changed[i:i+n] = bytes.fromhex(row['after'])
    # 只排除288B factor及八个明确拥有的Capture段，其余旧helper/六款/声音字节全部保持。
    wrapper = ((0xbef4c0, 0xbef524), (0xbef53e, 0xbef582), (0xbef588, 0xbef5c0), (0xbef620, 0xbef65a),
               (0xbef660, 0xbef678), (0xbef680, 0xbef69c), (0xbef6b0, 0xbef6ec),
               (0xbef700, builder.FACTOR), (0xbef9c8, TAIL)) if native else ((0xbef4c0, TAIL),)
    for start, end in ((0x11d2000, 0x11d4900), (0x11952c0, 0x1196f5a), (0x48e842, 0x48e846), *wrapper):
        if changed[start-BASE:end-BASE] != cp[start-BASE:end-BASE]:
            raise ValueError('旧六槽或旧包装器保护区被改变')
    old_snapshot = cp[0x898548-BASE:0x898548-BASE+118]
    new_snapshot = changed[0x898548-BASE:0x898548-BASE+118]
    index = snapshot_patchsite-0x898548
    if old_snapshot[:index] != new_snapshot[:index] or old_snapshot[index+4:] != new_snapshot[index+4:]:
        raise ValueError('完整118B快照窗口超出实际单条挂钩')
    return dict(status='CARVE_MEMORY_ONLY_REVERSIBLE_PROPOSAL', source_sha256=CP_SHA,
                candidate_sha256=sha(changed), bytes=len(cp), patches=rows,
                build_receipt=str(build/'verification.json'), build_receipt_sha256=sha(receipt_raw),
                RX_address=hex(layout['rx']), RW_address=hex(layout['rw']), RX_source_address=hex(cold),
                native_capacity=receipt['native_capacity'], capacity_layout=layout,
                capacity_layout_version=version, reserved_bytes=(rx_pages+rw_pages)*4096,
                cold_source_bytes=rx_pages*4096, cold_source_before_sha256=cold_before,
                native_asset_schema=schema,
                native_integration=native, native_hooks=[dict(address=a, code=b.hex()) for a, b in native_hooks],
                capture_lifecycle=native, capture_regions=capture_rows,
                capture_symbols={k: v for k, v in capture_symbols.items() if k and not k.startswith('$')},
                capture_hook_count=len(CAPTURE_CALLS) if native else 0,
                native_contract_bytes=1280 if native else 0,
                rw_resident_bytes=len(rw), rw_statics_bytes=receipt['rw_statics_bytes'],
                capture_input=capture, snapshot_patchsite=snapshot_patchsite,
                capture_copies=copies, copy_sites=expected_copy_sites,
                original_page_root='0x1a3c000', phase_address=hex(PHASE),
                original_SOLID_end='0x2b00000', new_SOLID_end=hex(layout['rx']),
                native_consumer_bound=native, native_consumers_source_bound=native, full_recipe_negotiable=False,
                target_executed=False, hardware_simulation=False, camera_io=False,
                CP_written=False, DAT_written=False, installed=False, installable_firmware=False)


def transform(cp, plan, reverse=False):
    key = 'candidate_sha256' if reverse else 'source_sha256'
    if len(cp) != plan['bytes'] or sha(cp) != plan[key]:
        raise ValueError('整包前像不符')
    before, after = ('after', 'before') if reverse else ('before', 'after')
    for row in plan['patches']:
        i, n = row['offset'], row['bytes']
        if i < 0 or n <= 0 or i+n > len(cp) or cp[i:i+n] != bytes.fromhex(row[before]) or len(bytes.fromhex(row[after])) != n:
            raise ValueError('补丁前像、长度或边界不符')
    out = bytearray(cp)
    for row in plan['patches']:
        i, n = row['offset'], row['bytes']
        out[i:i+n] = bytes.fromhex(row[after])
    expected = plan['source_sha256' if reverse else 'candidate_sha256']
    if sha(out) != expected:
        raise ValueError('结果摘要不符')
    return bytes(out)
