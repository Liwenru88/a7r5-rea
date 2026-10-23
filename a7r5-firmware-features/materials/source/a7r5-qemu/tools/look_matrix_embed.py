"""构建仅供隔离 QEMU 的内嵌矩阵 CP；不生成 DAT，不提供设备入口。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

BASE = 0x108000
CP_SHA = '903bb046b4525a55198c1312999857ee01f89859ba3de6f18ee107c46d63039a'
DELTA_SHA = '71aa15a9dfe051e2a260cc1d9cf55d8cf985e787b5884c136516a2f73950f8ac'
HELPER_SHA = '2861c4d849524c399170ca4c1ce7f402582a7abd379e76589452135284585775'
HELPER_VA, TABLE_VA = 0xbef6b0, 0x1a3a000
HELPER_BYTES = bytes.fromhex('362b19d3392b17d80f2988bf0021a3f1360340f2402202fb03f34af2000ac0f2a31a9a44242201fb02aa20254ff0000b002601952ef7d0b6fff764be')
PROFILES = (54, 55, 56, 57)
BANKS = (22, 24, 23, 25)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def branch(at, target):
    """Thumb-2 B.W，超出编码范围必须失败。"""
    displacement = target-at-4
    if displacement % 2 or not -(1 << 24) <= displacement < (1 << 24):
        raise ValueError('矩阵跳转超出 Thumb 范围')
    n = displacement & ((1 << 25)-1)
    s, i1, i2 = (n >> 24) & 1, (n >> 23) & 1, (n >> 22) & 1
    return struct.pack('<HH', 0xf000 | s << 10 | (n >> 12) & 0x3ff,
        0x9000 | (1 ^ i1 ^ s) << 13 | (1 ^ i2 ^ s) << 11 | (n >> 1) & 0x7ff)


def payload(delta):
    if len(delta) != 3076 or sha(delta) != DELTA_SHA or tuple(delta[:4]) != BANKS:
        raise ValueError('矩阵增量身份不符')
    # 设置以端点为主序；原函数连续读取路径以子槽为主序。只重排，不改变系数。
    return b''.join(delta[4+(bank-22)*768+endpoint*192+slot*12:
                         4+(bank-22)*768+endpoint*192+slot*12+12]
        for bank in BANKS for slot in range(16) for endpoint in range(3))


def build(original, delta, helper=HELPER_BYTES, *, initialized_bss=False):
    if type(initialized_bss) is not bool:raise ValueError('初始化布局选择必须为布尔值')
    if len(original) != 17617008 or sha(original) != CP_SHA:
        raise ValueError('内嵌候选 CP 前像不符')
    if helper != HELPER_BYTES or sha(helper) != HELPER_SHA:
        raise ValueError('矩阵辅助指令身份不符')
    table = payload(delta)
    text, ro, data, bss = (struct.unpack_from('<3I', original, at)
        for at in (0x20124, 0x20130, 0x2013c, 0x20148))
    if (text, ro, data, bss) != ((0,0xac8000,0x128000),(0xac8000,0x48f000,0xbf0000),
            (0xf57000,0x117f5c,0x107f000),(0x106f000,0x8a2448,0x1197000)):
        raise ValueError('CP 加载布局不符')
    stack = struct.unpack_from('<3I', original, 0x20154)
    clear_end = bss[2]+bss[1]
    if stack != (0,0x4000,0x1a3c000) or TABLE_VA != (clear_end+4095)&~4095:
        raise ValueError('BSS 与栈间隙边界不符')
    # data 与 BSS 的虚拟/文件偏移相同，重叠部分保持相同物理映射和原0xc权限。
    # 这是实验布局扩展，尚未完成完整 CP 引导/外部加载器验证，不可据此刷机。
    if data[2]-data[0] != bss[2]-bss[0] or TABLE_VA+len(table) > stack[2]:
        raise ValueError('矩阵数据会碰到栈或改变原 BSS 映射')
    table_file = TABLE_VA-BASE
    new_end = table_file+len(table)
    at = HELPER_VA-BASE
    hook = 0x71e43e-BASE
    if original[hook:hook+4] != branch(0x71e43e,0xbef3b4) or any(original[at:at+80]):
        raise ValueError('矩阵入口或已预留 RX 尾部前像不符')
    if any(original[0x20000+data[0]+data[1]:]):
        raise ValueError('初始化数据后存在未知非零尾部')
    output = bytearray(original)
    output.extend(bytes(new_end-len(output)))
    rows = []
    for offset, raw, reason in (
        (hook,branch(0x71e43e,HELPER_VA),'仅54～57改用内嵌数据；其他档位回原入口'),
        (at,helper,'在已有 RX 补丁的未使用尾部放置60字节辅助代码'),
        (0x20140,struct.pack('<I',TABLE_VA+len(table)-data[2]),'扩展实验初始化数据跨度；BSS与栈不移动'),
        (table_file,table,'四档16子槽三端点，子槽主序2304字节')):
        before = bytes(output[offset:offset+len(raw)])
        output[offset:offset+len(raw)] = raw
        rows.append(dict(offset=offset,bytes=len(raw),before=before.hex(),after=raw.hex(),reason=reason))
    report = dict(schema=1,source_sha256=sha(original),target_sha256=sha(output),
        source_bytes=len(original),target_bytes=len(output),patches=rows,
        helper_VA=HELPER_VA,helper_sha256=HELPER_SHA,table_VA=TABLE_VA,
        table_file=table_file,table_bytes=len(table),profiles=list(PROFILES),banks=list(BANKS),
        BSS_clear_end=clear_end,stack_begin=stack[2],BSS_descriptor_unchanged=True,
        mapping_attributes_unchanged=True,data_BSS_mapping_same_translation=True,
        initialized_data_span_overlaps_existing_BSS=True,
        requires_complete_loader_and_boot_validation=True,device_deployment_ready=False,
        camera_io=False,ISP_pixels_verified=False,settings_writes=False)
    if initialized_bss:
        # 把原 BSS 全局变量范围转为文件零初始化数据；不移动任何变量地址。
        # 零长BSS须放在新data末页之后：RTOS二次映射会按两者之间的差值取消映射，
        # 放在旧BSS终点会产生负长度，反而取消仍在使用的全局变量映射。
        zero_start,zero_end=bss[2]-BASE,clear_end-BASE
        new_bss=(TABLE_VA+len(table)+4095)&~4095
        physical=new_bss-(data[2]-data[0])
        old_root=((bss[0]+bss[1]+0x4fff)&~0x3fff)+(data[2]-data[0])
        new_root=((physical+0x4fff)&~0x3fff)+(data[2]-data[0])
        if any(output[zero_start:zero_end]) or old_root!=new_root or new_bss+0x418>old_root:
            raise ValueError('BSS零初始化、页表保留位置或启动清理边界不符')
        before=bytes(output[0x20148:0x20154])
        replacement=struct.pack('<3I',physical,0,new_bss)
        output[0x20148:0x20154]=replacement
        rows.append(dict(offset=0x20148,bytes=12,before=before.hex(),after=replacement.hex(),
            reason='原BSS改为零初始化data；零长BSS在新data之后，原页表保留位置不变'))
        report.update(target_sha256=sha(output),BSS_descriptor_unchanged=False,
            initialized_data_span_overlaps_existing_BSS=False,layout='initialized-zero-BSS',
            BSS_globals_VA_unchanged=True,BSS_reservation_end_unchanged=False,
            page_table_root_unchanged=True,page_table_root=old_root,
            zero_length_BSS_mapping=True,startup_metadata_clear=[new_bss,new_bss+0x418],
            full_CP_boot_verified=False)
    return bytes(output),report


def compile_helper(out):
    from runtime_manifest import LAB
    layout=out/'matrix-helper.ld'
    layout.write_text('ENTRY(matrix_inline)\nnative_matrix_expand = 0x71e488; native_matrix_legacy = 0xbef3b4;\n'
        'SECTIONS { . = 0xbef6b0; .text : { *(.text*) } /DISCARD/ : { *(.ARM.attributes*) } }\n')
    command=['/opt/homebrew/opt/llvm/bin/clang','--target=armv7a-none-eabi','-mthumb','-nostdlib',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-Wl,-T,'+str(layout),'-Wl,--build-id=none',
        str(LAB/'source/guest/look-matrix-inline.S'),'-o',str(out/'matrix-helper.elf')]
    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    (out/'matrix-helper-compiler.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('内嵌辅助代码构建失败')
    subprocess.run(['/opt/homebrew/opt/llvm/bin/llvm-objcopy','-O','binary',
        str(out/'matrix-helper.elf'),str(out/'matrix-helper.bin')],check=True,timeout=30)
    if (out/'matrix-helper.bin').read_bytes()!=HELPER_BYTES:
        raise ValueError('辅助代码重建结果与已核对指令不符')
    (out/'matrix-helper-build.json').write_text(json.dumps(dict(command=command,
        source_sha256=sha((LAB/'source/guest/look-matrix-inline.S').read_bytes()),
        helper_sha256=HELPER_SHA),indent=2)+'\n')


def prepare(folder, *, initialized_bss=False):
    from look_materials import load
    from runtime_manifest import LAB
    files,record=load(folder)
    if record['schema']!=2:raise ValueError('只接受第二版原始参数材料')
    target=Path(tempfile.mkdtemp(prefix='look-materials-inline-',dir=LAB/'build'))
    compile_helper(target)
    cp,report=build(files['cpapp-b.bin'],files['matrix-delta.bin'],initialized_bss=initialized_bss)
    files['cp-matrix-source.bin']=files['cpapp-b.bin'];files['cpapp-b.bin']=cp
    files['matrix-inline.json']=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()
    for name,raw in files.items():(target/name).write_bytes(raw)
    record.update(schema=4 if initialized_bss else 3,files={name:dict(bytes=len(raw),sha256=sha(raw)) for name,raw in files.items()},
        matrix_source='CP-embedded for profiles54..57; settings for other profiles',
        CP_scope='isolated embedded matrix candidate; loader and boot acceptance required',
        device_deployment_ready=False)
    (target/'receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    load(target)
    return target


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--materials',required=True,type=Path)
    p.add_argument('--initialized-bss',action='store_true',help='显式零初始化原BSS范围，消除数据/BSS映射重叠；仍需引导验证')
    args=p.parse_args();print(prepare(args.materials,initialized_bss=args.initialized_bss))
