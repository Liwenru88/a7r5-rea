"""将原厂 C1–C6 六款移植到已接入十档纵横比的二十四槽离线组件。"""

import argparse
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1] / 'firmware-runtime'
sys.path[:0] = [str(NATIVE), str(NATIVE / 'dependencies/native12-combined')]
from legacy_six import MATERIALS, load_recipes
from patches import BASE, PatchSet, digest, require, thumb_b
from stability import replace_exact

AP_SHA = '201aa07d80cd904985fdb770e20db206179cd84b3fe2ab8b124f4f9a595c348f'
CP_SHAS = {
    '6c34a880b303fb9c9b45db4e5716e265cda91664daa71982fedf060a682876ce',
    '851d417962b9ff9cdb809b73a025a2fcd0cc950fe29738a365392ef15425be95',
}
AVCAM_SHA = '11351971e97aaf48bbd011a8a15b819392a4ec4eff07b0a1caa39d49c4257c7a'
RESOURCE_SHA = 'b3512c7464be321169254b39decaecb289fa03f050342bab1a5e0289ddc8ffec'
HISTORY = MATERIALS / 'source'
HISTORY_CODE = HISTORY / 'analysis/custom-features-20261021-03/research-materials-v3/code'
HISTORY_JOINT = HISTORY / 'a7r5-qemu/source/guest/look-joint.S'
GRID_CODE = 0x119000
JOINT_CODE = 0x119240
GRID_DATA = 0x11a000
BASIS_DATA = 0x11bd00
GAMMA_TABLE = 0x11bf90
CP_END = 0x11e000
STRING_BANK = re.compile(r'string_[a-z]+_(?:horizontal|vertical)\.uxc')
TABLE_HOOKS = (0x413656, 0x413d2e, 0x413f42, 0x413f90, 0x414066, 0xaa8aa2)
NATIVE_BOUNDS = (0xaa8442, 0xaa8466, 0xaa8488, 0xaa85f6, 0xaa8a68)


def checked(path, sha):
    raw = path.read_bytes()
    require(digest(raw) == sha, '历史来源摘要不符 ' + str(path))
    return raw


def load_grid_builder():
    for name, sha in (
        ('assembler.py', 'f65920a49f8313abf1ea2305f75df8f5e4e45c665f883b522fabe45c76a49f7e'),
        ('cp_runtime.py', 'ac95bdc40c0665da6a35ac7c7692586ced06883e53693619daf41d83052d5725'),
    ):
        checked(HISTORY_CODE / name, sha)
    sys.path.insert(0, str(HISTORY_CODE))
    try:
        spec = importlib.util.spec_from_file_location('legacy_six_grid', HISTORY_CODE / 'cp_runtime.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def apply_ap(raw, grid_builder, *, runtime_sha=None, fl23=True):
    require(digest(raw) == (runtime_sha or AP_SHA), 'AP 完整前像不符')
    patches = PatchSet(raw)
    fl_checks = ['cmp w0,#17', 'b.eq fl2', 'cmp w0,#18', 'b.eq fl3'] if fl23 else []
    fl_routes = ['fl2:', 'mov w0,#19', 'b store', 'fl3:', 'mov w0,#20', 'b store'] if fl23 else []
    converter = grid_builder.assemble([
        'sub w3,w0,#10', 'cmp w3,#5', 'b.ls custom',
        'cmp w0,#16', 'b.eq special', *fl_checks,
        f'cmp w1,#{11 if fl23 else 9}', 'b.hi 0x35503d8', 'adr x0,table', 'ldrb w0,[x0,w1,uxtw]',
        'store:', 'strb w0,[x2]', 'ret',
        'custom:', 'add w0,w3,#249', 'b store',
        'special:', 'mov w0,#-1', 'b store', *fl_routes, 'table:',
        '.byte 0,3,2,1,16,15,17,18,5,13' + (',19,20' if fl23 else ',0,0'),
    ], 0x3550354, 'aarch64')
    require(len(converter) <= 132 and len(converter) % 4 == 0, 'AP 选择函数超出原窗口')
    converter += bytes.fromhex('1f2003d5') * ((132 - len(converter)) // 4)
    patches.put(0x3550354, raw[0x3550354:0x35503d8], converter, '六个原厂用户槽发送 249～254')
    old_ap, _ = json.loads(checked(MATERIALS / 'recipes.json',
        'f29fcdf0e005cf87cc821a45014ee295310cced806fd92123d68af38ec2c6fac'))['integrated']
    history = {row['offset']: row for row in old_ap['patches']}
    for at in (0x1bc78a8, 0x500fbc0, *(0x3f4a888 + i * 128 for i in range(6))):
        row = history[at]
        patches.put(at, bytes.fromhex(row['before']), bytes.fromhex(row['after']), '六个原厂用户槽名称')
    if runtime_sha is not None:
        elf = ELFFile(io.BytesIO(raw))
        rx = elf.get_segment(0)
        require((rx['p_type'], rx['p_flags'], rx['p_offset'], rx['p_vaddr'], rx['p_filesz'], rx['p_memsz'])
                == ('PT_LOAD', 5, 0, 0, 0x500fbb7, 0x500fbb7)
                and all(s['p_type'] != 'PT_LOAD' or min(s['p_offset'], s['p_vaddr']) >= 0x500fc10
                        for s in list(elf.iter_segments())[1:]), '六款名称代码的 AP 映射前像不符')
        for field in (32, 40):
            patches.put(elf['e_phoff'] + field, struct.pack('<Q', 0x500fbb7), struct.pack('<Q', 0x500fc10),
                        '映射六款名称代码')
    for group in range(3):
        for slot in range(10, 16):
            at = 0x4a422f8 + (group * 18 + slot) * 8
            prop, default = struct.unpack_from('<II', raw, at)
            require(prop == 0x163a + group * 18 + slot, '六款默认属性前像不符')
            if default:
                patches.put(at + 4, struct.pack('<I', default), bytes(4), '历史六款 ST 默认')
    return patches.finish()


def append_strings(raw, names):
    count, remainder = divmod(struct.unpack_from('<I', raw, 12)[0], 0x1001)
    require(raw[:4] == b'uxc\x07' and struct.unpack_from('<H', raw, 10)[0] == 5
            and count == 3032 and not remainder and len(raw) % 4 == 0, '六款名称银行前像不符')
    base = 16 + count * 2
    output = bytearray(raw[:base] + bytes(2 * len(names)) + raw[base:])
    start = base + 2 * len(names)
    struct.pack_into('<I', output, 12, (count + len(names)) * 0x1001)
    for index, name in enumerate(names):
        pointer = (len(output) - start) // 4
        require(pointer < 0xffff, '六款名称索引越界')
        struct.pack_into('<H', output, base + 2 * index, pointer)
        output.extend(struct.pack('<I', 0x1e00abd8 + index))
        output.extend(name.encode('ascii') + b'\0')
        output.extend(bytes(-len(output) % 4))
    return bytes(output)


def thumb_destination(raw, at, mnemonic):
    data = raw[at - BASE:at - BASE + 4]
    decoded = next(Cs(CS_ARCH_ARM, CS_MODE_THUMB).disasm(data, at))
    require(decoded.mnemonic == mnemonic and decoded.size == 4, f'CP 分支前像不符 {at:#x}')
    return int(decoded.op_str.removeprefix('#'), 16)


def compile_joint(raw, folder, route=0x107eefc):
    source = checked(HISTORY_JOINT, 'acc2d15a0fee28cfdfecb01c970a69eafbec2554225b381656cb028e85f1a68d').decode()
    source = source.split('/* R5与A7C II不同', 1)[0]
    source = replace_exact(source, 'adds r6, #51', 'adds r6, #75')
    source = replace_exact(source, 'sub.w ip, ip, #51', 'sub.w ip, ip, #75')
    source = replace_exact(source, '''    ldr.w ip, [sp, #140]
    addr r6, gamma_after_call + 1
    cmp ip, r6
    bne 1f
    ldr r1, [sp, #108]
    bx lr
1:  ldr.w r1, [r1, r2, lsl #2]
    bx lr''', '''    push.w {r3,r6,r12,lr}
    mrs r3, apsr
    ldr.w ip, [sp, #156]
    addr r6, gamma_after_call + 1
    cmp ip, r6
    ite eq
    ldreq r1, [sp, #124]
    ldrne.w r1, [r1, r2, lsl #2]
    msr apsr_nzcvq, r3
    pop.w {r3,r6,r12,pc}''')
    # 旧代码通过原始列加载曲线；保护非照片配置中没有曲线的列。
    source = replace_exact(source, 'ldr.w r1, [r1, r2, lsl #2]\n    mov r0, sp',
        'cmp r2, #6\n    bhi gamma_no_curve\n    ldr.w r1, [r1, r2, lsl #2]\n'
        '    cmp r1, #0\n    beq gamma_no_curve\n    mov r0, sp')
    source = replace_exact(source, '9:  b.w gamma_native',
        'gamma_no_curve:\n    mov r0, r4\n    mov r1, r5\n    mov r2, r6\n'
        '    add.w sp, sp, #0x240\n    add sp, #4\n    pop.w {r4-r11,lr}\n9:  b.w gamma_native')
    # 旧照片在切入 SD 组的过渡帧可能先读到动态 ST 别名 51／52。
    source = replace_exact(source, 'cmp r0, #0\n    beq 1f\n    cmp r0, #10\n    bne 2f',
        'cmp r0, #0\n    beq 1f\n    cmp r0, #51\n    beq 1f\n    cmp r0, #10\n    beq 4f\n'
        '    cmp r0, #52\n    bne 2f\n4:')
    for name, native in (('full', 'gamma_full_native'), ('partial', 'gamma_partial_native')):
        source = replace_exact(source, f'entry joint_gamma_{name}\n    push',
            f'entry joint_gamma_{name}\n    cbz r0, 8f\n    cbnz r1, 7f\n8:  b.w {native}\n7:  push')
    converted = folder / 'joint.S'
    converted.write_text(source)
    symbols = dict(native_matrix_continue=0x71e422, native_primary_continue=0x71e674,
        native_secondary_continue=0x71e9cc, native_gamma_full_continue=0xaa81ce,
        native_gamma_partial_continue=0xaa868c, native_gamma_partial_invalid=0xaa86b8,
        native_gamma_continue=0x413640, native_full_resume=0xaa8214, native_grid_controller=0x230da8,
        native_grid_build=0x230f10, native_grid_skip=0x230f3e,
        native_grid_upload=0x230f66, native_grid_consume=0x2315c0,
        historical_grid_helper=GRID_CODE | 1, historical_grid_build=GRID_CODE + 0x90,
        historical_grid_upload=GRID_CODE + 0x7e, historical_grid_consume=GRID_CODE + 0x160,
        current_grid_controller=thumb_destination(raw, 0x719f16, 'bl') | 1,
        native_partial_getter=thumb_destination(raw, 0xaa86ac, 'b.w') | 1,
        legacy_gamma_table=GAMMA_TABLE)
    symbols.update({f'prior_table_{i}': thumb_destination(raw, at, 'b.w') | 1 for i, at in enumerate(TABLE_HOOKS)})
    symbols.update({f'resume_table_{i}': at + 4 for i, at in enumerate(TABLE_HOOKS)})
    linker = folder / 'joint.ld'
    linker.write_text(''.join(f'{name} = {va:#x};\n' for name, va in symbols.items())
        + f'SECTIONS {{ .text {JOINT_CODE:#x} : {{ *(.text*) }} /DISCARD/ : {{ *(.ARM.attributes*) *(.comment*) }} }}\n')
    elf = folder / 'joint.elf'
    subprocess.run(['/opt/homebrew/opt/llvm/bin/clang', '--target=armv7a-none-eabi', '-mthumb',
        '-nostdlib', '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-Wl,-T,' + str(linker),
        '-Wl,--build-id=none', '-Wl,--entry=joint_matrix', '-DPARAMS_VA=' + hex(BASIS_DATA),
        '-DNATIVE_ROUTE_LO=' + hex(route & 0xffff),
        '-DGAMMA_VA=' + hex(GAMMA_TABLE - 75 * 28), str(converted), str(HERE / 'legacy_six_cp.S'),
        '-o', str(elf)], check=True)
    with elf.open('rb') as stream:
        image = ELFFile(stream)
        code = image.get_section_by_name('.text')
        require(code['sh_addr'] == JOINT_CODE and code['sh_size'] <= GRID_DATA - JOINT_CODE, '六款 CP 代码越界')
        return code.data(), {sym.name: sym['st_value'] for sym in image.get_section_by_name('.symtab').iter_symbols()
                             if sym.name.startswith(('legacy_', 'joint_'))}


def apply_cp(raw, folder, recipes, grid, *, runtime_sha=None, fl23=True, prior_mapper=0x108f40):
    require(digest(raw) in (CP_SHAS if runtime_sha is None else {runtime_sha}), 'CP 完整前像不符')
    text, prefix, data = struct.unpack_from('<3I', raw, 0x20128)
    require(prefix == 0x128000 and data == 0xac8000 and text == (0xac8000 if fl23 else 0xac7218)
            and 0x118000 < GRID_CODE < CP_END < 0x128000, 'CP 早期空白映射边界不符')
    route = 0x107eefc if fl23 else 0xdcc67c
    code, symbols = compile_joint(raw, folder, route)
    grid.HELPER, grid.CHECKER = GRID_CODE, GRID_CODE + 0x100
    grid.PREFIX_VA, grid.TABLE_VA = GRID_DATA, GRID_DATA + 32
    patches = PatchSet(raw)

    def put(va, before, after, reason):
        patches.put(va - BASE, before, after, reason)

    def put_space(va, data, end, reason):
        require(va + len(data) <= end, '六款 CP 保留区越界 ' + reason)
        put(va, bytes(len(data)), data, reason)

    def jump(va, target, reason, *, link=False, before=None):
        first, second = struct.unpack('<HH', thumb_b(va, target & ~1))
        put(va, before if before is not None else raw[va - BASE:va - BASE + 4],
            struct.pack('<HH', first, second | (0x4000 if link else 0)), reason)

    if runtime_sha is None:
        put(0xbef7dc, bytes.fromhex('011aa0e3'), bytes.fromhex('061aa0e3'), '映射纵横比与六款共用的连续页')
    else:
        # 原厂开启 MMU 前，从第一个已加载的物理区域进入。先沿用 24 槽的 mapper，再映射五个低地址页。
        mapper = 0x109000
        size = CP_END - GRID_CODE
        def arm_bl(at, target):
            delta = target - at - 8
            require(not delta % 4 and -(1 << 25) <= delta < 1 << 25, 'ARM mapper 分支越界')
            return 0xeb000000 | ((delta // 4) & 0xffffff)
        mapping = struct.pack('<13I',
            0xe92d4010, arm_bl(mapper + 4, prior_mapper), 0xe92d500f, 0xe10f4000,
            0xe3090000, 0xe3400011, 0xe1a02000, 0xe3a01a05, 0xe3a0300e,
            arm_bl(mapper + 36, 0x108768), 0xe128f004, 0xe8bd500f, 0xe8bd8010)
        require(GRID_CODE == 0x119000 and size == 0x5000, '六款独立映射范围不符')
        put_space(mapper, mapping, mapper + 0x100, '六款独立页映射器')
        put(0x1086d0, struct.pack('<I', arm_bl(0x1086d0, prior_mapper)),
            struct.pack('<I', arm_bl(0x1086d0, mapper)), '冷启动接入独立映射器')
    put_space(GRID_CODE, grid.helper_blob(), JOINT_CODE, '4.06 六款色表控制器')
    put_space(JOINT_CODE, code, GRID_DATA, '六款联合参数和访问门槛')
    put_space(GRID_DATA, grid.prefix([recipe[1] for recipe in recipes]), BASIS_DATA, '六款有符号原生色表')
    put_space(BASIS_DATA, b''.join(recipe[2] for recipe in recipes), GAMMA_TABLE, '六款原始联合增量')
    table = (0x107e968 if fl23 else 0x110cfa8) - BASE
    rows = raw[table:table + 28] + raw[table + 280:table + 308]
    put_space(GAMMA_TABLE, rows * len(recipes), CP_END, '保留 ST 两个域及原始列指针')

    for at, name, before in ((0x230ee0, 'legacy_grid_window', '002ac5f8'),
                             (0x230f62, 'legacy_grid_upload', '4ff61450'),
                             (0x2312f0, 'legacy_grid_consume', '002565e1')):
        jump(at, symbols[name], '按历史标记选择旧色表路径或重放原窗口', before=bytes.fromhex(before))
    jump(0x719f16, symbols['legacy_grid_dispatch'], '按历史标记隔离 SD 色表控制器', link=True)
    for at, name in ((0x71e41e, 'joint_matrix'), (0x71e670, 'joint_primary'), (0x71e9c8, 'joint_secondary'),
                     (0xaa81ca, 'joint_gamma_full'), (0xaa8688, 'joint_gamma_partial'),
                     (0x41363c, 'joint_gamma')):
        jump(at, symbols[name], name, before=bytes.fromhex('b0b1a9b1' if at == 0xaa8688 else 'f0b503af'))
    jump(0x413666, symbols['joint_record_primary'], '仅联合参数调用读取临时曲线', link=True,
         before=bytes.fromhex('51f82210'))
    put(0xaa820e, bytes.fromhex('55f8103fe360'),
        thumb_b(0xaa820e, symbols['legacy_full_normalize'] & ~1) + bytes.fromhex('00bf'), '完整 Gamma 归一化')
    for at in (0xaa8320, 0xaa832e):
        put(at, bytes.fromhex('2868'), bytes.fromhex('e068'), '完整 Gamma 下游读取 ST 副本')
    put(0xaa86a6, bytes.fromhex('4ef6fc624068' if fl23 else '4cf27c624068'),
        thumb_b(0xaa86a6, symbols['legacy_partial_normalize'] & ~1) + bytes.fromhex('00bf'), '局部 Gamma 归一化')
    for i, at in enumerate(TABLE_HOOKS):
        jump(at, symbols[f'legacy_table_{i}'], '仅私有 Gamma 行走固定表')
    for at in NATIVE_BOUNDS:
        put(at, bytes.fromhex('4b28'), bytes.fromhex('5728'), '允许私有 Gamma 75～86')
    output, receipt = patches.finish()
    receipt.update(symbols=symbols, grid_tables=GRID_DATA, gamma_rows=list(range(75, 87)),
                   grid_bytes=len(recipes) * 1215, basis_bytes=len(recipes) * 108)
    return output, receipt


def build(ap_path, cp_path, avcam_path, resources, output):
    ap, cp = ap_path.read_bytes(), cp_path.read_bytes()
    require(digest(ap) == AP_SHA and digest(cp) in CP_SHAS, '请使用已验证的十档纵横比 AP／CP 组件')
    assets = load_recipes()
    names = [name for name, _, _ in assets]
    avcam = checked(avcam_path, AVCAM_SHA)
    receipt = json.loads(checked(resources / 'build.json', RESOURCE_SHA))
    files = sorted(p for p in resources.iterdir() if STRING_BANK.fullmatch(p.name))
    require(len(files) == 68, '缺少横竖语言资源')
    strings = {}
    for path in files:
        raw = path.read_bytes()
        require(digest(raw) == receipt[path.name], '比例名称资源摘要不符 ' + path.name)
        strings[path.name] = append_strings(raw, names)
    images = {name: checked(resources / name, receipt[name])
              for name in ('image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc')}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    grid = load_grid_builder()
    final_ap, ap_proof = apply_ap(ap, grid)
    final_cp, cp_proof = apply_cp(cp, output, assets, grid)
    components = {'appFw.so': final_ap, 'cpapp-b.bin': final_cp, 'AV-CAM.BIN': avcam, **strings, **images}
    for name, raw in components.items():
        (output / name).write_bytes(raw)
    result = dict(schema='a7r5-native24-legacy-six/1', AP=ap_proof, CP=cp_proof,
                  names=names, components={name: sha256(raw).hexdigest() for name, raw in components.items()},
                  installable=False, camera_io=False)
    (output / 'build.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('ap', 'cp', 'avcam', 'resources', 'output'):
        parser.add_argument('--' + option, type=Path, required=True)
    args = parser.parse_args()
    result = build(args.ap, args.cp, args.avcam, args.resources, args.output)
    print(json.dumps({key: result[key]['target_sha256'] for key in ('AP', 'CP')}))
