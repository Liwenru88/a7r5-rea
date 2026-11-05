"""固定四/二十/二十二页构建及原CP内存往返；从不执行ARM或接触设备。"""
import ctypes as C
import importlib.util
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess

import pytest

HOME = Path(__file__).resolve().parents[1]
ROOT = HOME.parents[1]
HERE = HOME/'experiments/packaging406/cp_carve406'


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.fixture(scope='module', params=[(mode, native) for native in (False, True)
                                      for mode in ('postcopy', 'capture-input', 'capture-copies')]
                                     + [('native-integration', False)])
def product(request, tmp_path_factory):
    builder = module(HERE/'build.py', 'carve406_test_build')
    output = tmp_path_factory.mktemp('cp-carve406')/'build'
    mode, native = request.param
    result = builder.build(output, capture_input=mode == 'capture-input',
                           capture_copies=mode == 'capture-copies', native_capacity=native,
                           native_integration=mode == 'native-integration')
    return builder, output, result


def expected_layout(result):
    # 独立固定三个已授权布局，不由生产生成器推导测试期望。
    return ((0x2aea000, 0x2af4000, 0x11c8000, 10, 12, 0x29c2000, 0x3a7)
            if result['native_integration'] else
            (0x2aec000, 0x2af4000, 0x11ca000, 8, 12, 0x29c4000, 0x3af)
            if result['native_capacity'] else
            (0x2afc000, 0x2aff000, 0x11cf000, 3, 1, 0x29d4000, 0x3ef))


@pytest.fixture(scope='module')
def original_cp():
    reader = module(HOME/'experiments/packaging406/candidate_preflight.py', 'carve406_test_reader')
    return reader.read_cpio(ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio',
                            {'cp/cpapp-b.bin'})['cp/cpapp-b.bin']


def test_complete_bridge_link_and_physical_mapping_descriptors(product):
    builder, output, result = product
    assert result['status'] == 'CARVE_LINK_PASS_OFFLINE_ONLY'
    assert str((HERE/'memory_plan.py').relative_to(ROOT)) in result['source_sha256']
    assert 0 < result['bootstrap_bytes'] <= 408
    rx_address, rw_address, _, rx_pages, rw_pages, _, _ = expected_layout(result)
    assert result['capacity_layout_version'] == ('capture-color-22-v1' if result['native_integration'] else
                                                'native-capacity-20-v1' if result['native_capacity'] else 'legacy-4-v1')
    assert result['reserved_bytes'] == (rx_pages+rw_pages)*4096
    assert result['cold_source_bytes'] == rx_pages*4096
    assert result['cold_source_before_sha256'] == (
        '02b1c2234680617802901a77eae606ad02e4ddb4282ccbc60061eac5b2d90bba' if result['native_integration'] else
        'c35020473aed1b4642cd726cad727b63fff2824ad68cedd7ffb73c7cbd890479' if result['native_capacity'] else
        'f3cc103136423a57975750907ebc1d367e2985ac6338976d4d5a439f50323f4a')
    rx, rw = result['payloads']
    assert (rx['address'], rw['address']) == (rx_address, rw_address)
    assert rx['bytes'] <= rx_pages*4096 and rw['bytes'] <= rw_pages*4096
    if result['native_capacity']:
        assert rw['bytes'] == result['rw_resident_bytes'] == 49152
        assert 0 < result['rw_statics_bytes'] < result['rw_resident_bytes']
    assert (rx['flags'], rw['flags']) == (5, 6)
    assert all(name in result['module_symbols'] for name in builder.EXPORTS)
    assert result['native_consumer_bound'] == result['native_consumers_source_bound'] == result['native_integration']
    assert not result['full_recipe_negotiable']
    _, symbols = builder.inspect((output/'bootstrap/bootstrap.elf').read_bytes())
    blob = (output/'bootstrap/bootstrap-rx.bin').read_bytes()
    at = symbols['af_carve_descriptors']-builder.TAIL
    # 独立断言type2物理映射，而非重用曾经无法建立fault页的type1。
    assert struct.unpack_from('<10I', blob, at) == (
        2, 15, rx_address, rw_address, rx_address, 2, 12, rw_address, 0x2b00000, rw_address)
    assert result['snapshot_entry'] == symbols['af_carve_snapshot']
    core_commands = [c['argv'] for c in result['commands'] if str(HOME/'native/af_hs_cp406.c') in c['argv']]
    assert len(core_commands) == 1 and '-DAF_RECIPE_BRIDGE406=1' in core_commands[0]
    assert '-DAF_CP_SNAPSHOT_ENTRY406='+hex(result['snapshot_entry'])+'u' in core_commands[0]
    assert '-DAF_CP_CARVE_BRANCH406=1' in core_commands[0]
    assert ('-DAF_CP_CAPTURE_INPUT406=1' in core_commands[0]) == result['capture_input']
    assert ('-DAF_CP_CAPTURE_COPIES406=1' in core_commands[0]) == result['capture_copies']
    assert ('-DAF_CP_NATIVE_CAPACITY406=1' in core_commands[0]) == result['native_capacity']
    assert ('-DAF_JOINT_ASSET_LEGACY_ONLY406=1' in core_commands[0]) != result['native_capacity']
    assert result['native_asset_schema'] == (3 if result['native_capacity'] else 1)
    for flag in ('-DAF_CP_NATIVE406=1', '-DAF_CP_NATIVE_JOBS406=1', '-DAF_CP_COMPONENTS406_TARGET=1', '-DAF_CP_CAPTURE406=1'):
        assert (flag in core_commands[0]) == result['native_integration']
    assert result['capture_lifecycle'] == result['native_integration']
    assert result['read_input_exported'] == result['capture_input']
    if result['capture_input']:
        assert 'af_cp_override406_read_input' in result['module_symbols']
    assert result['native_input_consumers_bound'] == result['native_integration']
    if result['capture_copies']:
        assert result['snapshot_core_symbol'] == result['compact_copy'] == 'af_cp_copy406_gate'
        assert result['copy_sites'] == ([0x898568, 0x4baab6, 0x4bba78, 0x4bc002,
                                        0x884766, 0x719600, 0x9071f6, 0x313c70, 0xaa6978, 0xadf128,
                                        0x5c36e0, 0x5c3860, 0x5c3888]
                                       if result['native_integration'] else [0x898568, 0x4baab6, 0x4bba78, 0x4bc002])
    elif result['capture_input']:
        assert result['snapshot_core_symbol'] == 'af_cp_override406_snapshot_copy_gate'
        assert result['snapshot_core_symbol'] in result['module_symbols']
        assert result['snapshot_patchsite'] == 0x898568
    else:
        assert result['snapshot_patchsite'] == 0x89856c


def test_original_cp_roundtrip_and_protected_oldsix(product, original_cp):
    _, output, result = product
    plan_api = module(HERE/'memory_plan.py', 'carve406_test_memory')
    plan = plan_api.create_plan(original_cp, output)
    rx_address, _, cold, rx_pages, rw_pages, solid_size, _ = expected_layout(result)
    changed = plan_api.transform(original_cp, plan)
    assert plan_api.transform(changed, plan, reverse=True) == original_cp
    assert plan['native_asset_schema'] == result['native_asset_schema']
    assert struct.unpack_from('<I', changed, 0xe7d168-plan_api.BASE)[0] == solid_size
    assert 0x128000+solid_size == rx_address
    assert 0x2b00000-rx_address == (rx_pages+rw_pages)*4096
    assert int(plan['new_SOLID_end'], 16)-0x2560000 == (
        0x58a000 if result['native_integration'] else 0x58c000 if result['native_capacity'] else 0x59c000)
    wrapper = ((0xbef4c0, 0xbef524), (0xbef53e, 0xbef582), (0xbef588, 0xbef5c0), (0xbef620, 0xbef65a),
               (0xbef660, 0xbef678), (0xbef680, 0xbef69c), (0xbef6b0, 0xbef6ec),
               (0xbef700, 0xbef718), (0xbef9c8, 0xbef9e8)) if result['native_integration'] else ((0xbef4c0, 0xbef9e8),)
    for begin, end in ((0x11d2000, 0x11d4900), (0x11952c0, 0x1196f5a), *wrapper):
        assert changed[begin-plan_api.BASE:end-plan_api.BASE] == original_cp[begin-plan_api.BASE:end-plan_api.BASE]
    assert changed[cold-plan_api.BASE:cold-plan_api.BASE+len((output/'module-rx.bin').read_bytes())] == (output/'module-rx.bin').read_bytes()
    for address, length in ((0x495fd8, 4), (0x496044, 6), (result['snapshot_patchsite'], 4)):
        row = next(row for row in plan['patches'] if row['address'] == address)
        assert row['bytes'] == length
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
        instructions = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(bytes.fromhex(row['after']), address))
        assert instructions[0].mnemonic == ('bl' if result['capture_copies'] and address == result['snapshot_patchsite'] else 'b.w')
        if length == 6:
            assert instructions[1].mnemonic == 'nop'
    before = original_cp[0x898548-plan_api.BASE:0x898548-plan_api.BASE+118]
    after = changed[0x898548-plan_api.BASE:0x898548-plan_api.BASE+118]
    index = result['snapshot_patchsite']-0x898548
    assert before[:index] == after[:index] and before[index+4:] == after[index+4:]
    assert plan['snapshot_patchsite'] == result['snapshot_patchsite']
    copy_returns = {0x898568: 0x89856d, 0x4baab6: 0x4baabb, 0x4bba78: 0x4bba7d, 0x4bc002: 0x4bc007}
    for address in copy_returns:
        if result['capture_copies']:
            from capstone.arm import ARM_REG_LR
            decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
            decoder.detail = True
            row = next(row for row in plan['patches'] if row['address'] == address)
            branch = list(decoder.disasm(bytes.fromhex(row['after']), address))
            assert len(branch) == 1 and branch[0].mnemonic == 'bl' and branch[0].size == 4
            assert ARM_REG_LR in branch[0].regs_access()[1]
            assert (branch[0].address+branch[0].size)|1 == copy_returns[address]
            assert int(branch[0].op_str[1:], 16) == result['snapshot_entry'] & ~1
        elif address != 0x898568:
            assert changed[address-plan_api.BASE:address-plan_api.BASE+4] == original_cp[address-plan_api.BASE:address-plan_api.BASE+4]
    if result['native_integration']:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
        for address, returned in ((0x884766, 0x88476b), (0x719600, 0x719605), (0x9071f6, 0x9071fb), (0x313c70, 0x313c75), (0xaa6978, 0xaa697d),
                                  (0xadf128, 0xadf12d),
                                  (0x5c36e0, 0x5c36e4), (0x5c3860, 0x5c3864), (0x5c3888, 0x5c388c)):
            arm = not returned & 1
            row = next(r for r in plan['patches'] if r['address'] == address)
            code = list(Cs(CS_ARCH_ARM, CS_MODE_ARM if arm else CS_MODE_THUMB).disasm(bytes.fromhex(row['after']), address))
            assert len(code) == 1 and code[0].size == 4 and code[0].mnemonic == ('blx' if arm else 'bl')
            assert int(code[0].op_str[1:], 16) == result['snapshot_entry'] & ~1
            assert (address+4 if arm else (address+4)|1) == returned
    # 实际补丁前像、整包摘要均不可绕过，输入保持不变。
    wrong = bytearray(original_cp)
    wrong[0xe7d168-plan_api.BASE] ^= 1
    with pytest.raises(ValueError, match='身份'):
        plan_api.create_plan(wrong, output)
    corrupt = json.loads(json.dumps(plan))
    corrupt['patches'][0]['before'] = '00'*corrupt['patches'][0]['bytes']
    with pytest.raises(ValueError, match='前像'):
        plan_api.transform(original_cp, corrupt)
    assert plan_api.sha(original_cp) == plan_api.CP_SHA


def test_mixed_snapshot_metadata_is_rejected_before_patch_plan(product, original_cp, tmp_path):
    _, _, result = product
    plan_api = module(HERE/'memory_plan.py', 'carve406_mixed_mode_memory')
    wrong = json.loads(json.dumps(result))
    wrong['snapshot_patchsite'] = 0x89856c if result['capture_input'] else 0x898568
    (tmp_path/'verification.json').write_text(json.dumps(wrong))
    with pytest.raises(ValueError, match='patchsite'):
        plan_api.create_plan(original_cp, tmp_path)
    assert plan_api.sha(original_cp) == plan_api.CP_SHA


def test_only_three_fixed_capacity_layouts_are_accepted(product, original_cp, tmp_path):
    builder, _, result = product
    with pytest.raises(ValueError, match='布局'):
        builder.build(tmp_path/'invalid', native_capacity=20)
    assert not (tmp_path/'invalid').exists()
    plan_api = module(HERE/'memory_plan.py', 'carve406_fixed_capacity_memory')
    for bad in (20, None, '8rx-12rw'):
        wrong = json.loads(json.dumps(result))
        wrong['native_capacity'] = bad
        (tmp_path/'verification.json').write_text(json.dumps(wrong))
        with pytest.raises(ValueError, match='布局'):
            plan_api.create_plan(original_cp, tmp_path)
    for field, value in (('capacity_layout_version', 'capture-color-24-v1'),
                         ('reserved_bytes', result['reserved_bytes']+4096),
                         ('cold_source_bytes', result['cold_source_bytes']+4096),
                         ('cold_source_before_sha256', '00'*32)):
        wrong = json.loads(json.dumps(result))
        wrong[field] = value
        (tmp_path/'verification.json').write_text(json.dumps(wrong))
        with pytest.raises(ValueError, match='布局'):
            plan_api.create_plan(original_cp, tmp_path)
    wrong = json.loads(json.dumps(result))
    wrong['native_asset_schema'] = 1 if result['native_capacity'] else 2
    (tmp_path/'verification.json').write_text(json.dumps(wrong))
    with pytest.raises(ValueError, match='schema'):
        plan_api.create_plan(original_cp, tmp_path)
    wrong = json.loads(json.dumps(result))
    flag = '-DAF_JOINT_ASSET_LEGACY_ONLY406=1'
    command = next(c['argv'] for c in wrong['commands'] if str(HOME/'native/af_joint_asset.c') in c['argv'])
    if flag in command:
        command.remove(flag)
    else:
        command.append(flag)
    (tmp_path/'verification.json').write_text(json.dumps(wrong))
    with pytest.raises(ValueError, match='flag'):
        plan_api.create_plan(original_cp, tmp_path)


@pytest.fixture(scope='module')
def guard_host(product, original_cp):
    builder, output, result = product
    rx_address, rw_address, _, rx_pages, rw_pages, _, _ = expected_layout(result)
    rx = (output/'module-rx.bin').read_bytes()
    rw = (output/'module-rw-initialized.bin').read_bytes()
    source = (HERE/'bootstrap/guard.c').read_text()
    replacements = {
        '#define PHASE (*(volatile uint32_t *)0x1a3ac60u)': '#define PHASE h_phase',
        '(const uint32_t *)0xce0354u': 'h_table',
        '__asm__ volatile("mrc p15,0,%0,c1,c0,0":"=r"(control));': 'control=h_control;',
        '__asm__ volatile("mrc p15,0,%0,c2,c0,0":"=r"(root));': 'root=h_root;',
        '__asm__ volatile("mrc p15,0,%0,c2,c0,2":"=r"(split));': 'split=h_split;',
        '*(volatile uint32_t *)0x1a3c0a8u': 'h_l1',
        '(const volatile uint32_t *)(table+AF_CARVE_PTE_BIAS)': 'h_ptes',
        '(const void *)AF_CARVE_COLD': '(const void *)h_source',
        '(const void *)AF_CARVE_RX': '(const void *)h_rx',
        '(void *)AF_CARVE_RX': '(void *)h_rx',
        '(void *)AF_CARVE_RW': '(void *)h_rw',
        '*(volatile uint32_t *)AF_CARVE_RW': 'h_rw[0]',
    }
    for old, new in replacements.items():
        assert old in source, old
        source = source.replace(old, new)
    prefix = f'''#include <stdint.h>
#include <string.h>
uint32_t h_phase,h_control,h_root,h_split,h_l1,h_table[256],h_ptes[{rx_pages+rw_pages}],h_rw[{len(rw)//4}];
uint8_t h_rx[{len(rx)}],h_source[{len(rx)}];
unsigned h_copy,h_zero,h_d,h_i,h_corrupt_copy;
'''
    suffix = '''
void stock_copy(void *d,const void *s,uint32_t n){++h_copy;memcpy(d,s,n);if(h_corrupt_copy)((uint8_t *)d)[0]^=1;}
void stock_zero(void *d,uint32_t n){++h_zero;memset(d,0,n);}
void stock_dcache(void *c){(void)c;++h_d;}
void stock_icache(void *c){(void)c;++h_i;}
'''
    host = output/'guard-host.c'
    host.write_text(prefix+source+suffix)
    library = output/'guard-host.dylib'
    run = subprocess.run(['clang', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror',
                          '-DAF_CP_CARVE_BRANCH406=1', '-I'+str(HOME/'native'),
                          *(['-DAF_CP_CAPTURE_INPUT406=1'] if result['capture_input'] else []),
                          *(['-DAF_CP_CAPTURE_COPIES406=1'] if result['capture_copies'] else []),
                          '-I'+str(output/'bootstrap'), str(host), str(HOME/'native/af_cp_override406.c'),
                          *([str(HOME/'native/af_cp_input406.c')] if result['capture_input'] else []),
                          *([str(HOME/'native/af_cp_copy406.c')] if result['capture_copies'] else []),
                          str(HOME/'native/af_slots.c'), '-o', str(library)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    lib = C.CDLL(str(library))
    table = (C.c_uint32*256).in_dll(lib, 'h_table')
    raw_table = original_cp[0xce0354-0x108000:0xce0354-0x108000+1024]
    actual_table = struct.unpack('<256I', raw_table)
    independent = []
    for k in range(256):
        value = k << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04c11db7 if value & 0x80000000 else 0)) & 0xffffffff
        independent.append(value)
    assert tuple(independent) == actual_table
    table[:] = actual_table
    assert builder.crc(rx) == result['RX_crc']

    def word(name):
        return C.c_uint32.in_dll(lib, 'h_'+name)

    host_rx = (C.c_uint8*len(rx)).in_dll(lib, 'h_rx')
    host_source = (C.c_uint8*len(rx)).in_dll(lib, 'h_source')
    host_rw = (C.c_uint32*(len(rw)//4)).in_dll(lib, 'h_rw')
    ptes = (C.c_uint32*(rx_pages+rw_pages)).in_dll(lib, 'h_ptes')

    def reset():
        for name, value in dict(phase=2, control=1, root=0x1a3c000, split=0, l1=0x2a10c12,
                                copy=0, zero=0, d=0, i=0, corrupt_copy=0).items():
            word(name).value = value
        host_source[:] = rx
        host_rx[:] = bytes([0x55])*len(rx)
        host_rw[:] = [0xabababab]*len(host_rw)
        ptes[:] = ([rx_address+0x63e+i*4096 for i in range(rx_pages)]
                   + [rw_address+0x41f+i*4096 for i in range(rw_pages)])

    return lib, word, reset, host_rx, host_source, host_rw, rx, rw, ptes


def test_guard_crc_copy_and_cache_publication(guard_host):
    lib, word, reset, dst, src, rw, expected, expected_rw, _ = guard_host
    reset()
    assert lib.af_carve_prepare() == 0 and word('phase').value == 1
    assert bytes(dst) == expected and bytes(rw) == expected_rw
    assert word('copy').value == word('zero').value == 1
    word('l1').value = 0x1a40001
    lib.af_carve_cache(None)
    assert word('phase').value == 2 and word('d').value == word('i').value == 1
    lib.af_carve_cache(None)
    assert word('d').value == 2 and word('i').value == 1
    # phase1仅为映射准备；坏源和复制损坏均在最终整载荷CRC处拒绝执行。
    for corrupt_copy in (False, True):
        reset()
        if corrupt_copy:
            word('corrupt_copy').value = 1
        else:
            src[0] ^= 1
        assert lib.af_carve_prepare() == 0 and word('phase').value == 1
        assert bytes(rw) == expected_rw and word('zero').value == 1
        assert word('copy').value == 1
        word('l1').value = 0x1a40001
        lib.af_carve_cache(None)
        assert word('i').value == 0 and word('phase').value == 0


def test_guard_rejects_unknown_mapping_before_payload_access(guard_host):
    lib, word, reset, dst, _, rw, _, _, _ = guard_host
    for field, value in (('control', 0), ('root', 0x1a40000), ('root', 0x1a3c001),
                         ('split', 1), ('split', 0x80000000), ('split', 16),
                         ('l1', 0), ('l1', 0x2a10c02), ('l1', 0x2b10c12), ('l1', 0x1a41011)):
        reset()
        word(field).value = value
        before_rx, before_rw = bytes(dst), bytes(rw)
        assert lib.af_carve_prepare() == 0 and word('phase').value == 0
        assert bytes(dst) == before_rx and bytes(rw) == before_rw
        assert word('copy').value == word('zero').value == 0


def test_guard_requires_final_physical_pages_and_wx(guard_host, product):
    lib, word, reset, _, _, _, _, _, ptes = guard_host
    rx_address, rw_address, _, rx_pages, rw_pages, _, _ = expected_layout(product[2])
    # 未消费descriptor、错coarse池、错域、错PA或权限均不得执行Icache/phase2。
    cases = [('l1', 0x2a10c12), ('l1', 0x1a48001), ('l1', 0x1a40011),
             ('root', 0x1a40000), ('control', 0), ('split', 0x80000000)]
    for name, value in cases:
        reset()
        assert lib.af_carve_prepare() == 0 and word('phase').value == 1
        word('l1').value = 0x1a40001
        word(name).value = value
        lib.af_carve_cache(None)
        assert word('phase').value == 0 and word('i').value == 0
    # 每页分别破坏XN低位及PA；最后一页RW同样必须被检查，不能在首RW提前退出。
    expected = ([rx_address+0x63e+i*4096 for i in range(rx_pages)]
                + [rw_address+0x41f+i*4096 for i in range(rw_pages)])
    for index, value in [(i, pte ^ mask) for i, pte in enumerate(expected) for mask in (1, 0x1000)]:
        reset()
        assert lib.af_carve_prepare() == 0
        word('l1').value = 0x1a47c01
        ptes[index] = value
        lib.af_carve_cache(None)
        assert word('phase').value == 0 and word('i').value == 0
    reset()
    assert lib.af_carve_prepare() == 0
    word('l1').value = 0x1a47c01
    lib.af_carve_cache(None)
    assert word('phase').value == 2 and word('i').value == 1


def test_actual_snapshot_branch_matches_complete_stock_window(product, original_cp, guard_host):
    _, output, result = product
    lib = guard_host[0]
    plan_api = module(HERE/'memory_plan.py', 'carve406_snapshot_test_memory')
    plan = plan_api.create_plan(original_cp, output)
    changed = plan_api.transform(original_cp, plan)
    full = bytearray(changed[0x898548-plan_api.BASE:0x898548-plan_api.BASE+118])
    lib.af_cp_override406_hook_matches.argtypes = [C.c_void_p, C.c_size_t, C.c_uint32]
    for corrupt, expected in ((False, 1), (True, 0)):
        if corrupt:
            full[40] ^= 1  # 原MOVT也必须完整保留。
        raw = (C.c_uint8*len(full)).from_buffer_copy(full)
        assert lib.af_cp_override406_hook_matches(raw, len(full), result['snapshot_entry']) == expected


def test_static_thumb_guard_final_admission_order(product):
    """独立核实际目标指令及literal；静态解码不执行任何目标指令。"""
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    builder, output, result = product
    rx_address, rw_address, cold, rx_pages, rw_pages, _, pte_bias = expected_layout(result)
    elf, symbols = builder.inspect((output/'bootstrap/bootstrap.elf').read_bytes())
    text = elf.get_section_by_name('.text')
    data, start = text.data(), int(text['sh_addr'])
    table = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}

    def instructions(name):
        sym = table[name]
        address = int(sym['st_value']) & ~1
        raw = data[address-start:address-start+int(sym['st_size'])]
        ins = list(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(raw, address))
        assert sum(i.size for i in ins) == len(raw)
        return ins

    expected_literals = dict(phase=0x1a3ac60, carve_root=0x1a3c000,
                             carve_coarse=0x1a40001, carve_cold_section=0x2a10c12,
                             carve_rx=rx_address, carve_rw=rw_address, carve_source=cold,
                             carve_crc_table=0xce0354, carve_crc=result['RX_crc'])
    for name, value in expected_literals.items():
        assert struct.unpack_from('<I', data, symbols[name]-start)[0] == value
    root = instructions('carve_root_bad')
    assert [(i.mnemonic, i.op_str) for i in root if i.mnemonic == 'mrc'] == [
        ('mrc', 'p15, #0, r0, c1, c0, #0'),
        ('mrc', 'p15, #0, r1, c2, c0, #2'),
        ('mrc', 'p15, #0, r0, c2, c0, #0')]
    assert [(i.mnemonic, i.op_str) for i in root if i.mnemonic in ('lsrs', 'eors', 'orrs')] == [
        ('lsrs', 'r0, r0, #1'), ('eors', 'r0, r2'), ('orrs', 'r0, r1')]
    cache = instructions('af_carve_cache')
    assert ('ldr.w', 'r0, [r2, #0xa8]') in [(i.mnemonic, i.op_str) for i in instructions('af_carve_prepare')]
    calls = [(index, int(i.op_str[1:], 16)) for index, i in enumerate(cache) if i.mnemonic in ('bl', 'blx')]
    assert [address for _, address in calls] == [0x5f3524, symbols['carve_root_bad'] & ~1, 0x5f2cf0]
    instruction_pairs = [(i.mnemonic, i.op_str) for i in cache]
    assert ('ldr.w', 'r0, [r2, #0xa8]') in instruction_pairs
    assert ('bic', 'r1, r0, #0x7c00') in instruction_pairs
    assert ('addw', 'r0, r0, #'+hex(pte_bias)) in instruction_pairs
    assert ('addw', 'r1, r1, #0x63e') in instruction_pairs
    assert ('addw', 'r1, r1, #0x41f') in instruction_pairs
    rx_count = hex(rx_pages) if rx_pages > 9 else str(rx_pages)
    assert ('movs', 'r2, #'+rx_count) in instruction_pairs
    rw_count = hex(rw_pages) if rw_pages > 9 else str(rw_pages)
    assert ('movs', 'r2, #'+rw_count) in instruction_pairs
    loop = next(index for index, i in enumerate(cache) if i.address == symbols['pte_loop'])
    assert [i.mnemonic for i in cache[loop:loop+6]] == ['ldr', 'cmp', 'bne', 'add.w', 'subs', 'bne']
    assert int(cache[loop+5].op_str[1:], 16) == symbols['pte_loop']
    # 区间结束只看expected r1的bit0；不得用受输入PTE控制的r3决定提前退出。
    assert (cache[loop+6].mnemonic, cache[loop+6].op_str) == ('lsls', 'r3, r1, #0x1f')
    assert cache[loop+7].mnemonic == 'bmi' and int(cache[loop+7].op_str[1:], 16) == symbols['pages_done']
    assert (cache[loop+10].mnemonic, cache[loop+10].op_str) == ('movs', 'r2, #'+rw_count)
    assert cache[loop+11].mnemonic == 'b' and int(cache[loop+11].op_str[1:], 16) == symbols['pte_loop']
    assert cache[loop+12].address == symbols['pages_done']
    assert (rx_address+rx_pages*4096+0x63e) & 1 == 0
    assert (rw_address+rw_pages*4096+0x41f) & 1 == 1
    # 完整CRC和两个逐页区间均有回边，且CRC之后才允许I维护/phase2。
    crc = next(index for index, i in enumerate(cache) if i.address == symbols['crc_loop'])
    assert [i.mnemonic for i in cache[crc:crc+6]] == ['ldrb', 'eor.w', 'ldr.w', 'eor.w', 'subs', 'bne']
    assert int(cache[crc+5].op_str[1:], 16) == symbols['crc_loop']
    assert ('movw', 'r2, #'+hex(result['payloads'][0]['bytes'])) in instruction_pairs
    last_call = calls[-1][0]
    assert last_call > crc+5
    assert instruction_pairs[last_call+1:last_call+3] == [('movs', 'r0, #2'), ('str', 'r0, [r5]')]


def test_snapshot_tail_uses_copy_arguments_only_in_capture_mode(product):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    from capstone.arm import ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_IP, ARM_REG_LR, ARM_REG_SP, ARM_REG_PC
    builder, output, result = product
    elf, symbols = builder.inspect((output/'bootstrap/bootstrap.elf').read_bytes())
    text = elf.get_section_by_name('.text')
    address = symbols['af_carve_snapshot'] & ~1
    code = text.data()[address-builder.TAIL:symbols['snapshot_target']-builder.TAIL]
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    decoder.detail = True
    ins = list(decoder.disasm(code, address))
    pairs = [(i.mnemonic, i.op_str) for i in ins]
    assert struct.unpack_from('<I', text.data(), symbols['snapshot_target']-builder.TAIL)[0] == result['module_symbols'][result['snapshot_core_symbol']]
    if result['capture_copies']:
        # 无效CRC/暖启动phase0不进入新RX：直接以原LR尾调原stock_copy。
        assert not any(i.mnemonic in ('bl', 'blx') for i in ins)
        for i in ins:
            _, writes = i.regs_access()
            assert not set(writes) & {ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_LR, ARM_REG_SP}
        assert struct.unpack_from('<I', text.data(), symbols['stock_copy_target']-builder.TAIL)[0] == 0x5f51bc
        core, core_symbols = builder.inspect(Path(result['artifact']['path']).read_bytes())
        core_start = core_symbols['af_cp_copy406_gate'] & ~1

        def code_bytes(at, count):
            segment = next(s for s in core.iter_segments() if s['p_type'] == 'PT_LOAD' and
                           s['p_vaddr'] <= at and at+count <= s['p_vaddr']+s['p_filesz'])
            return segment.data()[at-segment['p_vaddr']:at-segment['p_vaddr']+count]

        core_ins = list(decoder.disasm(code_bytes(core_start, core_symbols['snapshot_return']-core_start), core_start))
        nonpad = [i for i in core_ins if i.mnemonic != 'nop']
        saved = {ARM_REG_R0, ARM_REG_R1, ARM_REG_R2, ARM_REG_R3, ARM_REG_IP, ARM_REG_LR}
        assert nonpad[0].mnemonic == 'push.w' and {o.reg for o in nonpad[0].operands} == saved
        assert nonpad[-2].mnemonic == 'pop.w' and {o.reg for o in nonpad[-2].operands} == saved
        assert len(saved)*4 == 24 and (nonpad[-1].mnemonic, nonpad[-1].op_str) == ('bx', 'lr')
        by_address = {i.address: i for i in core_ins}
        routes = {}
        for n, instruction in enumerate(core_ins):
            if instruction.mnemonic != 'ldr' or instruction.operands[0].reg != ARM_REG_R3:
                continue
            mem = instruction.operands[1].mem
            if mem.base != ARM_REG_PC:
                continue
            literal = ((instruction.address+4)&~3)+mem.disp
            value = struct.unpack('<I', code_bytes(literal, 4))[0]
            assert (core_ins[n+1].mnemonic, core_ins[n+1].op_str) == ('cmp', 'lr, r3')
            assert core_ins[n+2].mnemonic == 'beq'
            routes[value] = int(core_ins[n+2].op_str[1:], 16)
        extra = {0x88476b, 0x719605, 0x9071fb, 0x313c75, 0xaa697d, 0xadf12d,
                 0x5c36e4, 0x5c3864, 0x5c388c} if result['native_integration'] else set()
        assert set(routes) == {0x89856d, 0x4baabb, 0x4bba7d, 0x4bc007} | extra
        assert (by_address[routes[0x89856d]].mnemonic, by_address[routes[0x89856d]].op_str) == (
            'bl', '#'+hex(core_symbols['af_cp_override406_snapshot_copy_target'] & ~1))
        primary = by_address[routes[0x4baabb]]
        assert (primary.mnemonic, primary.op_str) == ('ldr', 'r3, [sp, #0xc8]')
        jump = by_address[primary.address+primary.size]
        assert jump.mnemonic == 'b'
        image = by_address[int(jump.op_str[1:], 16)]
        assert (image.mnemonic, image.op_str) == ('bl', '#'+hex(core_symbols['af_cp_override406_image_copy_target'] & ~1))
        assert routes[0x4bba7d] == routes[0x4bc007]
        secondary = by_address[routes[0x4bba7d]]
        assert (secondary.mnemonic, secondary.op_str) == ('ldr', 'r3, [sp, #0x2c]')
        assert by_address[secondary.address+secondary.size].address == image.address
        assert 0xb0+24 == 0xc8 and 0x14+24 == 0x2c
        assert any(i.mnemonic == 'bl' and int(i.op_str[1:], 16) == core_symbols['af_cp_override406_untracked_copy_target'] & ~1 for i in core_ins)
        if result['native_integration']:
            request_call = by_address[routes[0xadf12d]]
            assert request_call.mnemonic == 'bl' and int(request_call.op_str[1:], 16) == core_symbols['af_cp_override406_request_copy_target'] & ~1
            shadow_route = routes[0xaa697d]
            assert (by_address[shadow_route].mnemonic, by_address[shadow_route].op_str) == ('mov', 'r3, lr')
            shadow_call = by_address[shadow_route+by_address[shadow_route].size]
            assert shadow_call.mnemonic == 'bl' and int(shadow_call.op_str[1:],16) == core_symbols['af_cp_components406_gamma_copy_target'] & ~1
            shot_route = routes[0x313c75]
            assert (by_address[shot_route].mnemonic, by_address[shot_route].op_str) == ('mov', 'r3, lr')
            shot_call = by_address[shot_route+by_address[shot_route].size]
            assert shot_call.mnemonic == 'bl' and int(shot_call.op_str[1:], 16) == core_symbols['af_cp_native406_shot_copy_target'] & ~1
            c4_route = routes[0x88476b]
            assert routes[0x719605] == routes[0x9071fb] == c4_route
            assert (by_address[c4_route].mnemonic, by_address[c4_route].op_str) == ('mov', 'r3, lr')
            call = by_address[c4_route+by_address[c4_route].size]
            assert call.mnemonic == 'bl' and int(call.op_str[1:], 16) == core_symbols['af_cp_native406_c4_target'] & ~1
            queue_route = routes[0x5c36e4]
            assert routes[0x5c3864] == routes[0x5c388c] == queue_route
            begin = next(n for n, i in enumerate(core_ins) if i.address == queue_route)
            queue = core_ins[begin:begin+6]
            assert [(i.mnemonic, i.op_str) for i in queue[:4]] == [
                ('mov', 'r3, lr'), ('add.w', 'ip, sp, #0x18'), ('sub', 'sp, #8'), ('str.w', 'ip, [sp]')]
            assert queue[4].mnemonic == 'bl' and int(queue[4].op_str[1:], 16) == core_symbols['af_cp_native406_queue_target'] & ~1
            assert (queue[5].mnemonic, queue[5].op_str) == ('add', 'sp, #8')
    elif result['capture_input']:
        copy = next(n for n, i in enumerate(ins) if i.mnemonic == 'blx' and i.op_str == '#0x5f51bc')
        # 原三参在第一次真实copy前无写入，phase只能使用原scratch r3。
        for i in ins[:copy]:
            _, writes = i.regs_access()
            assert not set(writes) & {ARM_REG_R0, ARM_REG_R1, ARM_REG_R2}
        assert pairs[0][0] == 'ldr' and pairs[0][1].startswith('r3,')
        assert pairs[copy+1] == ('b.w', '#0x89856c')
        core, core_symbols = builder.inspect(Path(result['artifact']['path']).read_bytes())
        core_start = core_symbols[result['snapshot_core_symbol']] & ~1
        core_return = core_symbols['copy_return']

        def code_bytes(at, count):
            segment = next(s for s in core.iter_segments() if s['p_type'] == 'PT_LOAD' and
                           s['p_vaddr'] <= at and at+count <= s['p_vaddr']+s['p_filesz'])
            return segment.data()[at-segment['p_vaddr']:at-segment['p_vaddr']+count]

        core_ins = list(decoder.disasm(code_bytes(core_start, core_return-core_start), core_start))
        calls = [i for i in core_ins if i.mnemonic in ('bl', 'blx')]
        assert len(calls) == 1
        assert int(calls[0].op_str[1:], 16) == core_symbols['af_cp_override406_snapshot_copy_target'] & ~1
        assert core_ins[0].mnemonic == 'push.w' and core_ins[2].mnemonic == 'pop.w'
        assert struct.unpack('<I', code_bytes(core_return, 4))[0] == 0x89856d
    else:
        assert not any(i.mnemonic == 'blx' for i in ins)
        assert ('movw', 'r0, #0xb7d0') in pairs
        assert ('b.w', '#0x898570') in pairs


def test_native_permanent_factor_preserves_legacy_and_binds_actual_contract(product, original_cp, tmp_path):
    if not product[2]['native_integration']:
        pytest.skip('仅新原生分支替换原288B范围')
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    builder, output, result = product
    plan_api = module(HERE/'memory_plan.py', 'native406_permanent_memory')
    plan = plan_api.create_plan(original_cp, output)
    patched = plan_api.transform(original_cp, plan)
    factor, sy = builder.inspect((output/'factor/factor.elf').read_bytes())
    section = factor.get_section_by_name('.text')
    data, begin = section.data(), section['sh_addr']
    decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    assert begin == 0xbef718 and len(data) == 288
    assert (sy['factor_matrix'], sy['factor_primary'], sy['factor_secondary']) == (0xbef719, 0xbef779, 0xbef7d9)
    for at, target in ((0xbef74c, 0xbef700), (0xbef7ac, 0xbef708), (0xbef80c, 0xbef710)):
        raw = data[at-begin:at-begin+4]
        assert raw == original_cp[at-plan_api.BASE:at-plan_api.BASE+4]
        ins = list(decoder.disasm(raw, at))
        assert len(ins) == 1 and ins[0].mnemonic == 'bl' and int(ins[0].op_str[1:], 16) == target
    entries = {0x71e41e: 'permanent_matrix', 0x71e670: 'permanent_primary',
               0x41363c: 'permanent_gamma', 0x230f0c: 'permanent_grid',
               0x845700: 'permanent_gamma_source', 0xaaca82: 'permanent_gamma_reset'}
    for address, name in entries.items():
        hot = list(decoder.disasm(patched[address-plan_api.BASE:address-plan_api.BASE+4], address))
        assert len(hot) == 1 and hot[0].mnemonic == ('bl' if address in (0x845700,0xaaca82) else 'b.w') and int(hot[0].op_str[1:], 16) == sy[name] & ~1
        at = sy[name] & ~1
        gate = list(decoder.disasm(data[at-begin:at-begin+6], at))
        assert [i.mnemonic for i in gate] == ['push', 'adr', 'b']
        assert gate[0].op_str == '{r0, r1, r2, lr}' and gate[1].op_str.startswith('r0, #')
        assert int(gate[2].op_str[1:], 16) == sy['permanent_phase'] & ~1
    at = sy['permanent_phase'] & ~1
    phase = list(decoder.disasm(data[at-begin:at-begin+16], at))
    assert [i.mnemonic for i in phase] == ['ldr', 'ldr', 'cmp', 'ite', 'ldreq', 'ldrne', 'str', 'pop']
    assert [(i.mnemonic, i.op_str) for i in phase[1:]] == [
        ('ldr', 'r1, [r1]'), ('cmp', 'r1, #2'), ('ite', 'eq'), ('ldreq', 'r1, [r0]'),
        ('ldrne', 'r1, [r0, #4]'), ('str', 'r1, [sp, #0xc]'), ('pop', '{r0, r1, r2, pc}')]
    # LR寄存器保持原caller；只改本gate保存LR槽，再POP PC尾调，原16B帧恢复。
    assert all('lr' not in i.op_str for i in phase)
    literal = ((phase[0].address+4)&~3)+int(phase[0].op_str.split('#')[1].split(']')[0], 16)
    _, boot = builder.inspect((output/'bootstrap/bootstrap.elf').read_bytes())
    assert literal == boot['phase'] == result['factor_phase_literal']
    assert struct.unpack_from('<I', data, sy['grid_record']-begin+4)[0] == 0xbef551
    assert 'permanent_grid_fallback' not in sy
    assert struct.unpack_from('<I', data, sy['gamma_record']-begin+4)[0] == 0xbef8e1
    assert struct.unpack_from('<I', data, sy['source_record']-begin+4)[0] == 0xaacb17
    assert struct.unpack_from('<I', data, sy['reset_record']-begin+4)[0] == 0xaa6413
    assert struct.unpack_from('<I', data, sy['payload_base']-begin)[0] == 0x1a39450
    assert struct.unpack_from('<I', data, sy['call_base']-begin)[0] == 0xbef74d
    # 新gate只占静态重排腾出的间隔；旧路径必须先跳开，不能跌入新构造入口。
    for end,target in (('factor_validate_end','eligible'),('factor_parameters_end','add_loop'),
                       ('factor_secondary_entry_end','validate')):
        at=sy[end]-2
        ins=list(decoder.disasm(data[at-begin:at-begin+2],at))
        assert len(ins)==1 and ins[0].mnemonic=='b' and int(ins[0].op_str[1:],16)==sy[target]
    # 原旧六款的profile/flag/marker族及半字低16位加法独立整数对照，不执行目标。
    for profile in (0, 1, 51, 52, 53, 54, 55, 56, 57, 255):
        for flag in (0, 1, 2, 255):
            for marker in range(256):
                assert (profile == 0 and flag <= 1 and 249 <= marker <= 254) == (
                    profile == 0 and flag <= 1 and ((marker-249)&0xffffffff) <= 5)
    rng = random.Random(0x406)
    for count in (27, 24, 8):
        values = [rng.randrange(65536) for _ in range(count)]
        delta = [rng.randrange(-32768, 32768) for _ in range(count)]
        before = b''.join(struct.pack('<H', (a+b)&65535) for a, b in zip(values, delta))
        after = b''.join(struct.pack('<H', (a+(b&65535))&65535) for a, b in zip(values, delta))
        assert before == after
    # 八个来源明确的局部段之外，所有旧helper/包装器/声音字节保持。
    core, core_symbols = builder.inspect(Path(result['artifact']['path']).read_bytes())
    capture, capture_sy = builder.inspect((output/'capture/capture.elf').read_bytes())
    regions = (('format', 0xbef524, 26), ('rsource', 0xbef582, 6), ('color', 0xbef65a, 6),
               ('rsource_record', 0xbef678, 8), ('pool', 0xbef69c, 20),
               ('release', 0xbef6ec, 20), ('factor', 0xbef838, 400), ('checker', 0xbef5c0, 96))
    capture_blob = b''
    for name, address, size in regions:
        section = capture.get_section_by_name('.capture_'+name)
        assert (section['sh_addr'], section['sh_size']) == (address, size)
        row = next(r for r in plan['patches'] if r['address'] == address)
        assert row['bytes'] == size and bytes.fromhex(row['after']) == section.data()
        assert bytes.fromhex(row['before']) == original_cp[address-plan_api.BASE:address-plan_api.BASE+size]
        capture_blob += section.data()
    assert len(capture_blob) == 582 and plan['capture_hook_count'] == 32
    capture_calls = ((0x45bc80, 'birth'), (0x45be6c, 'birth'), (0x48d700, 'rebuild'),
        (0x48d8b4, 'rebuild'), (0x46e65a, 'restore'), (0x335e56, 'reverse'),
        (0x872682, 'gamma'), (0x45c09a, 'release'), (0xadf96c, 'pool'),
        (0xadfd2c, 'pool'), (0xae038c, 'pool'), (0xaa7f08, 'format'),
        (0xadd846, 'rsource'), (0x71d6ec, 'matrix9'),
        *((address, 'color') for address in (0x24d32a, 0x24daba, 0x73e8dc, 0x73e94e,
          0x73e9ba, 0x73ea62, 0x73ea68, 0x73ea8c, 0x73f10e, 0x73f174, 0x73f1e4,
          0x73f278, 0x73f2e6, 0x73f362, 0x73f394, 0x73f3f4, 0x73f494, 0x73f4c6)))
    tails = {0x73e9ba, 0x73ea62, 0x73ea68, 0x73ea8c, 0x73f494}
    for address, kind in capture_calls:
        code = list(decoder.disasm(patched[address-plan_api.BASE:address-plan_api.BASE+4], address))
        assert len(code) == 1 and code[0].mnemonic == ('b.w' if address in tails else 'bl') and code[0].size == 4
        assert int(code[0].op_str[1:], 16) == capture_sy['permanent_capture_'+kind] & ~1
        from capstone.arm import ARM_REG_LR
        decoder.detail = True
        original = list(decoder.disasm(original_cp[address-plan_api.BASE:address-plan_api.BASE+4], address))[0]
        after = list(decoder.disasm(patched[address-plan_api.BASE:address-plan_api.BASE+4], address))[0]
        assert original.mnemonic == after.mnemonic
        assert (ARM_REG_LR in original.regs_access()[1]) == (ARM_REG_LR in after.regs_access()[1]) == (address not in tails)
        if address not in tails:
            assert (code[0].address+code[0].size)|1 == address+5
    assert len(plan['patches']) == 69
    assert patched[0x48e842-plan_api.BASE:0x48e846-plan_api.BASE] == original_cp[0x48e842-plan_api.BASE:0x48e846-plan_api.BASE]
    # 独立核16位间接字面量和跨段ADR；不能只信生产helper的region元数据。
    color = capture.get_section_by_name('.capture_color').data()
    color_code = list(decoder.disasm(color, 0xbef65a))
    assert [(i.mnemonic, i.op_str) for i in color_code] == [
        ('push', '{r0, r1, r2, lr}'), ('ldr', 'r0, [pc, #0x4c]'), ('b', '#0xbef818')]
    pointer = struct.unpack_from('<I', capture.get_section_by_name('.capture_pool').data(), 16)[0]
    assert ((color_code[1].address+4)&~3)+0x4c == 0xbef6ac
    assert pointer == 0xbef534
    assert struct.unpack_from('<2I', capture.get_section_by_name('.capture_format').data(), 16) == (
        core_symbols['af_cp_capture406_color_target'], 0x719ef7)
    rsource = list(decoder.disasm(capture.get_section_by_name('.capture_rsource').data(), 0xbef582))
    assert [(i.mnemonic, i.op_str) for i in rsource] == [
        ('push', '{r0, r1, r2, lr}'), ('adr', 'r0, #0xf0'), ('b', '#0xbef818')]
    assert ((rsource[1].address+4)&~3)+0xf0 == 0xbef678
    assert struct.unpack('<2I', capture.get_section_by_name('.capture_rsource_record').data()) == (
        core_symbols['af_cp_capture406_rsource_target'], 0x4596f5)
    checker = capture.get_section_by_name('.capture_checker').data()
    builder.CAPTURE.validate_checker(original_cp[0xbef5c0-plan_api.BASE:0xbef620-plan_api.BASE], checker)
    matrix9 = list(decoder.disasm(checker[80:86], 0xbef610))
    assert [(i.mnemonic, i.op_str) for i in matrix9] == [
        ('push', '{r0, r1, r2, lr}'), ('adr', 'r0, #4'), ('b', '#0xbef818')]
    assert capture_sy['permanent_capture_matrix9'] == 0xbef611
    assert struct.unpack_from('<2I', checker, 88) == (core_symbols['af_cp_components406_matrix9_shim'], 0x71eccd)
    shim_at = core_symbols['af_cp_components406_matrix9_shim'] & ~1
    shim = list(decoder.disasm(builder.module_bytes(core, shim_at, 8), shim_at))
    assert [(i.mnemonic, i.op_str) for i in shim[:2]] == [('mov', 'r2, r6'), ('mov', 'r3, r5')]
    assert len(shim) == 3 and shim[-1].mnemonic == 'b.w'
    assert int(shim[-1].op_str[1:], 16) == core_symbols['af_cp_components406_matrix9_target'] & ~1
    raw = capture.get_section_by_name('.capture_factor').data()
    for address in (0xbef856, 0xbef866, 0xbef9b6):
        assert raw[address-0xbef838:address-0xbef838+4] == original_cp[address-plan_api.BASE:address-plan_api.BASE+4]
    assert raw[0x176:0x18c] == original_cp[0xbef9ae-plan_api.BASE:0xbef9c4-plan_api.BASE]
    # 1280B合同必须等于288B factor、582B Capture、2B零pad及51条真实patch。
    expected = data+capture_blob+bytes(2)+b''.join(struct.pack('<I', row['address'])+bytes.fromhex(row['code']) for row in result['native_hooks'])
    start = core_symbols['af_cp_native406_factor_expected']
    assert len(result['native_hooks']) == 51 and result['native_contract_bytes'] == plan['native_contract_bytes'] == 1280
    assert len(expected) == 1280 and builder.module_bytes(core, start, 1280) == expected
    assert core_symbols['af_cp_native406_capture_expected'] == start+288
    assert builder.module_bytes(core, start+288+582, 2) == bytes(2)
    assert core_symbols['af_cp_native406_hooks'] == start+288+584
    assert len(result['native_contract_iterations']) >= 2 and not result['native_contract_iterations'][-1]['text_positions_changed']
    draft = tmp_path/'draft'
    draft.mkdir()
    shutil.copytree(output/'factor', draft/'factor')
    shutil.copytree(output/'bootstrap', draft/'bootstrap')
    shutil.copytree(output/'capture', draft/'capture')
    shutil.copyfile(output/'native-contract.c', draft/'native-contract.c')
    for field in ('native_hooks', 'factor_phase_literal', 'capture_symbols', 'capture_regions'):
        wrong = json.loads(json.dumps(result))
        if field == 'native_hooks':
            wrong[field][-1]['code'] = '00000000'
        elif field == 'capture_symbols':
            wrong[field]['permanent_capture_format'] ^= 2
        elif field == 'capture_regions':
            wrong[field][0]['address'] += 4
        else:
            wrong[field] ^= 4
        (draft/'verification.json').write_text(json.dumps(wrong))
        with pytest.raises(ValueError, match='挂点|phase|Capture'):
            plan_api.create_plan(original_cp, draft)


def test_native_capture_uses_verified_elf_bytes_after_contract_check(product, original_cp, tmp_path, monkeypatch):
    if not product[2]['native_integration']:
        pytest.skip('仅原生Capture有局部段合同')
    builder, output, result = product
    api = module(HERE/'memory_plan.py', 'capture406_immutable_artifacts')
    draft = tmp_path/'draft'
    draft.mkdir()
    for directory in ('factor', 'bootstrap', 'capture'):
        shutil.copytree(output/directory, draft/directory)
    shutil.copyfile(output/'native-contract.c', draft/'native-contract.c')
    copied = json.loads(json.dumps(result))
    for row in copied['capture_regions']:
        path = draft/('capture-'+row['name']+'.bin')
        path.write_bytes(Path(row['path']).read_bytes())
        row['path'] = str(path)
    (draft/'verification.json').write_text(json.dumps(copied))
    target = copied['capture_regions'][0]
    verified = Path(target['path']).read_bytes()
    original_contract = builder.contract_source

    def contract_then_change_file(*args):
        text = original_contract(*args)
        changed = bytearray(verified)
        changed[0] ^= 1
        Path(target['path']).write_bytes(changed)
        return text

    original_load = api.load_module
    monkeypatch.setattr(builder, 'contract_source', contract_then_change_file)
    monkeypatch.setattr(api, 'load_module', lambda path, name: builder if path == HERE/'build.py' else original_load(path, name))
    plan = api.create_plan(original_cp, draft)
    row = next(r for r in plan['patches'] if r['address'] == target['address'])
    assert bytes.fromhex(row['after']) == verified
    assert api.transform(api.transform(original_cp, plan), plan, reverse=True) == original_cp
