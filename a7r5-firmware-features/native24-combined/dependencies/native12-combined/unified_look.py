"""原生创意外观覆盖层：固定前像、独立段、完整逆还原。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE_SHA = '65e33ba2075bb59f65a97e6cec550bd8b1d54bac040fe28427cd3922924ffde0'
AUDIT_SHA = '91fc50f73bef7fcb6862a16e890fde765f8055d146d7756b05f072825a1ae569'
RX, RW, ANCHOR = 0x8f00000, 0x8f10000, 0x8f00400
DESC, GROUP = 0x5858b08, 0x5053628
HOOKS = [
    (0x1bd8eb8, 'alias'), (0x1bd1ef8, 'alias_object'), (0x1bd1b88, 'name'),
    (0x1bd18e8, 'icon'), (0x1bd19e8, 'icon_alt'), (0x1bdb0b0, 'parent'),
    (0x1bcfffc, 'visible'), (0x2209580, 'inhibited'), (0x220933c, 'direct'),
    (0x1c6f208, 'select'), (0x25966cc, 'preview'), (0x1c956c8, 'preview_menu'),
    (0x23fcd48, 'display'), (0x220a7ac, 'parameter_init'), (0x220ac74, 'base_cycle'),
    (0x220b620, 'parameter_value'), (0x220b51c, 'parameter_disabled'),
    (0x220b708, 'parameter_default'), (0x2209464, 'base_available'),
    (0x8e983a4,'text'),
    (0x1e97a24,'refresh'), (0x2208e34,'labels'),
    (0x1a6d8cc,'dispatch'),
] + [(0x2209918+i*0x154, 'step_'+str(i)) for i in range(8)]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def branch(source, target, link=False):
    delta = target-source
    if delta & 3 or not -(1 << 27) <= delta < (1 << 27):
        raise ValueError('分支对齐／范围不符')
    return struct.pack('<I', (0x94000000 if link else 0x14000000) | ((delta//4) & 0x3ffffff))


def build(raw, output, audit_path=None):
    if sha(raw) != SOURCE_SHA:
        raise ValueError('统一入口 AP 完整前像不符')
    output = Path(output)
    output.mkdir(mode=0o700)
    audit_path = Path(audit_path or ROOT/'.local/native12-combined-baseline-01/work/import/module_audit.json')
    audit_raw = audit_path.read_bytes()
    if sha(audit_raw) != AUDIT_SHA:
        raise ValueError('上游符号审计身份不符')
    original_symbols = json.loads(audit_raw)['symbols']
    original = ELFFile(io.BytesIO(raw))

    def file_at(va, size=1):
        for s in original.iter_segments():
            if s['p_type'] == 'PT_LOAD' and s['p_vaddr'] <= va and va+size <= s['p_vaddr']+s['p_filesz']:
                return s['p_offset']+va-s['p_vaddr']
        raise ValueError('文件范围不在原加载段：'+hex(va))

    # 首指令仅允许已知位置无关形式，禁止把 ADRP／分支复制到新 PC。
    tramp = ['.section .text.anchor,"ax",@progbits', '.global n12_anchor', '.hidden n12_anchor',
             'n12_anchor:', 'nop', '.text']
    for address, name in HOOKS:
        word = struct.unpack_from('<I', raw, file_at(address, 4))[0]
        if word not in (0xa9be7bfd, 0xa9bc7bfd, 0xa9bb7bfd, 0xa9bd7bfd,
                        0xa9b97bfd, 0xa9b87bfd, 0xa9b67bfd, 0x5282bb03,
                        0x528566c2, 0xb9402060):
            raise ValueError('未知跳板首指令：'+name+' '+hex(word))
        tramp += [f'.global n12_stock_{name}', f'n12_stock_{name}:', f'.inst {word}', f'b n12_ret_{name}']
    # 原上游 availability 包装器的底层入口也须保留原生规则。
    native_available = original_symbols['r5_native_row_available_direct']
    tramp += ['.global n12_stock_available', 'n12_stock_available:', 'b n12_available_original']
    (output/'trampolines.S').write_text('\n'.join(tramp)+'\n')
    definitions = '\n'.join(f'n12_ret_{n} = {hex(a+4)};' for a,n in HOOKS)
    definitions += f'\nn12_available_original = {hex(native_available)};\n'
    definitions += '\n'.join(f'{n} = {hex(original_symbols[n])};' for n in (
        'r5_filter_selected', 'r5_filter_available_mask', 'r5_filter_pending',
        'r5_filter_command_state', 'r5_filter_command_sequence', 'r5_filter_request',
        'usleep', 'r5_native_menu_insert', 'r5_native_row_insert','r5_native_menu_normalize',
        'r5_filter_full_name'))
    layout = f'''ENTRY(n12_register)
{definitions}
PHDRS {{ code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }}
SECTIONS {{
 . = {hex(ANCHOR)};
 .text : {{ *(.text.anchor) *(.text*) *(.rodata*) }} :code
 . = {hex(RW)};
 .data : {{ *(.data*) }} :data
 .bss (NOLOAD) : {{ *(.bss*) *(COMMON) }} :data
 /DISCARD/ : {{ *(.comment*) *(.eh_frame*) *(.note*) }}
}}
'''
    (output/'unified-look.ld').write_text(layout)
    (output/'unified-look.c').write_bytes((HERE/'unified-look.c').read_bytes())
    command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-none-elf', '-Oz', '-fpie',
               '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-mgeneral-regs-only',
               '-fvisibility=hidden', '-Wall', '-Wextra', '-Werror', '-nostdlib',
               '-mllvm', '-enable-machine-outliner=never',
               '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-Wl,-T,'+str(output/'unified-look.ld'),
               '-Wl,--build-id=none', str(output/'unified-look.c'), str(output/'trampolines.S'),
               '-o', str(output/'unified-look.elf')]
    compiled = subprocess.run(command, capture_output=True, text=True)
    (output/'compiler.log').write_text(compiled.stdout+compiled.stderr)
    if compiled.returncode:
        raise RuntimeError('统一入口编译失败：'+compiled.stderr)
    module = ELFFile(io.BytesIO((output/'unified-look.elf').read_bytes()))
    symtab = module.get_section_by_name('.symtab')
    if any(s.name and s['st_shndx'] == 'SHN_UNDEF' for s in symtab.iter_symbols()):
        raise ValueError('统一模块含未解析符号')
    symbols = {s.name: int(s['st_value']) for s in symtab.iter_symbols() if s.name}
    segments = [s for s in module.iter_segments() if s['p_type'] == 'PT_LOAD']
    if any(s['sh_size'] for s in module.iter_sections() if s.name in ('.got','.got.plt','.rela.dyn','.rela.plt')):
        raise ValueError('统一模块含未重定位的 GOT 或动态重定位')
    if len(segments) != 2 or [s['p_flags'] for s in segments] != [5, 6]:
        raise ValueError('新增段权限不符')
    if not (ANCHOR <= segments[0]['p_vaddr'] < segments[0]['p_vaddr']+segments[0]['p_memsz'] < RW
            <= segments[1]['p_vaddr'] < segments[1]['p_vaddr']+segments[1]['p_memsz'] <= RW+0x10000):
        raise ValueError('新增段越界')

    target = bytearray(raw)
    patches = []

    def put(at, data, reason):
        before = bytes(target[at:at+len(data)])
        if len(before) != len(data):
            raise ValueError('原文件补丁越界')
        if before != data:
            patches.append(dict(offset=at, before=before.hex(), after=data.hex(), reason=reason))
            target[at:at+len(data)] = data

    # 恢复原七项主菜单及原 PLT，不删除原模块中已无引用的 PLT 副本。
    group_at = file_at(GROUP, 16+8*24)
    records = [raw[group_at+16+i*24:group_at+16+(i+1)*24] for i in range(8)]
    if [struct.unpack_from('<Q',r)[0] for r in records] != [0x1f1,0x1f2,0x635,0x1f3,0x1f4,0x1f5,0x1f6,0x1f9]:
        raise ValueError('主菜单前像不符')
    put(group_at+8, struct.pack('<I',7), '主菜单恢复七项')
    put(group_at+16, b''.join(records[:2]+records[3:])+bytes(24), '移除独立滤镜条目')
    rela, plt = original.get_section_by_name('.rela.dyn'), original.get_section_by_name('.rela.plt')
    old_plt = plt.data()
    if sha(old_plt) != '861474b66563e3f75564641970bbf55d1ed702b3e775405d895828521d148bb2':
        raise ValueError('PLT 副本不符')
    relas = list(struct.iter_unpack('<QQq',rela.data()))
    if relas[-1] != (0x5053670,1027,0x8eb9df0):
        raise ValueError('独立菜单重定位前像不符')
    moved = {0x5053688,0x50536a0,0x50536b8,0x50536d8,0x50536e8}
    replaced = {DESC+0x58:(0x3f4a280,symbols['n12_rows']), DESC+0x78:(0x1c05f18,symbols['n12_current'])}
    found = set()
    for i,(at,info,addend) in enumerate(relas[:-1]):
        if at in moved:
            if info != 1027: raise ValueError('父项重定位类型不符')
            put(rela['sh_offset']+i*24,struct.pack('<Q',at-24),'恢复父项重定位目标')
        if at in replaced:
            before,after = replaced[at]
            if info != 1027 or addend != before:raise ValueError('创意外观重定位不符')
            put(rela['sh_offset']+i*24+16,struct.pack('<q',after),'统一列表描述符重定位')
            put(file_at(at,8),struct.pack('<Q',after),'统一列表描述符静态值')
            found.add(at)
    if found != set(replaced):raise ValueError('未找到创意外观重定位')
    put(0x16d3b58,old_plt,'恢复原 PLT 字节')
    dynamic=original.get_section_by_name('.dynamic')
    for i,(tag,value) in enumerate(struct.iter_unpack('<qQ',dynamic.data())):
        if tag in (8,23):
            expected = rela['sh_size'] if tag==8 else plt['sh_addr']
            if value != expected:raise ValueError('动态表前像不符')
            put(dynamic['sh_offset']+16*i+8,struct.pack('<Q',rela['sh_size']-24 if tag==8 else 0x16d3b58),'恢复原动态表')
    for i,s in enumerate(original.iter_sections()):
        at=original['e_shoff']+i*original['e_shentsize']
        if s.name=='.rela.dyn':put(at+32,struct.pack('<Q',rela['sh_size']-24),'恢复原 RELA 长度')
        if s.name=='.rela.plt':put(at+16,struct.pack('<QQ',0x16d3b58,0x16d3b58),'恢复原 PLT 段表')
    if struct.unpack_from('<I',raw,0x3e6f220)[0]!=7 or struct.unpack_from('<I',raw,0x3e6f3a4)[0]!=0x635:
        raise ValueError('Fn 前像不符')
    put(0x3e6f220,struct.pack('<I',6),'Fn 恢复原六候选')
    put(0x3e6f3a4,bytes(64),'撤回独立 Fn 候选')
    put(file_at(DESC+0x54,4),struct.pack('<I',31),'保留原十九项并追加十二项')
    for address,name in HOOKS:
        put(file_at(address,4),branch(address,symbols['n12_'+name]),'原生隔离入口 '+name)
    for name,replacement in [('r5_filter_menu_register','n12_menus'),('r5_filter_rows_register','n12_register'),
                              ('r5_filter_menu_normalize','n12_menu_alias'),('r5_filter_row_available_direct','n12_available')]:
        at=original_symbols[name];put(file_at(at,4),branch(at,symbols[replacement]),'取消独立菜单注册 '+name)
    for at,name,callee in [(0x220a898,'n12_init_index',0x2dc6160),(0x220a8c4,'n12_init_bases',0x28c54cc),
                           (0x2208e8c,'n12_title_name',0x1bd5508)]:
        if raw[file_at(at,4):file_at(at,4)+4] != branch(at,callee,True):raise ValueError('初始化调用前像不符')
        put(file_at(at,4),branch(at,symbols[name],True),'隔离初始化有限数组')
    # 完整 PHT 另存；保留原八条，新增两条，没有 W+X。
    if original['e_phnum']!=8 or original['e_phentsize']!=56:raise ValueError('程序头前像不符')
    ph=raw[original['e_phoff']:original['e_phoff']+8*56]
    appended_at=(len(raw)+0xffff)&~0xffff
    rx_size=segments[0]['p_vaddr']-RX+segments[0]['p_filesz']
    rw_at=appended_at+0x10000
    extra_ph=struct.pack('<II6Q',1,5,appended_at,RX,RX,rx_size,rx_size,0x10000)
    extra_ph+=struct.pack('<II6Q',1,6,rw_at,RW,RW,segments[1]['p_filesz'],segments[1]['p_memsz'],0x10000)
    target.extend(bytes(rw_at+segments[1]['p_filesz']-len(target)))
    target[appended_at:appended_at+560]=ph+extra_ph
    target[appended_at+ANCHOR-RX:appended_at+rx_size]=segments[0].data()
    target[rw_at:rw_at+segments[1]['p_filesz']]=segments[1].data()
    put(32,struct.pack('<Q',appended_at),'程序头改用完整新表')
    put(56,struct.pack('<H',10),'程序头包含新增 RX／RW')
    reversed_image=bytearray(target[:len(raw)])
    for p in reversed(patches):
        before=bytes.fromhex(p['before']);reversed_image[p['offset']:p['offset']+len(before)]=before
    if reversed_image!=raw:raise ValueError('覆盖层不能精确逆还原')
    final=ELFFile(io.BytesIO(target))
    loads=[s for s in final.iter_segments() if s['p_type']=='PT_LOAD']
    for i,s in enumerate(loads):
        if s['p_flags'] not in (4,5,6) or s['p_filesz']>s['p_memsz']:raise ValueError('最终 ELF 权限／长度不符')
        if any(max(s['p_vaddr'],p['p_vaddr'])<min(s['p_vaddr']+s['p_memsz'],p['p_vaddr']+p['p_memsz']) for p in loads[:i]):raise ValueError('最终 ELF 加载段重叠')
    path=output/'appFw.so';path.write_bytes(target)
    receipt=dict(schema='native12-unified-look/1',source_sha256=SOURCE_SHA,target_sha256=sha(target),
                 source_bytes=len(raw),target_bytes=len(target),patches=patches,inverse_exact=True,
                 symbols=symbols,source_C_sha256=sha((HERE/'unified-look.c').read_bytes()),command=command,
                 factory_count=19,custom_count=12,creative_mid=0x1f2,private_registered=False,
                 added_segments=[dict(va=RX,flags=5,bytes=rx_size),dict(va=RW,flags=6,bytes=segments[1]['p_memsz'])],
                 camera_io=False,old_DAT_modified=False,upstream_modified=False)
    (output/'unified-look-patch.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
    return path,receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();path,record=build(args.source.read_bytes(),args.output)
    print(json.dumps(dict(path=str(path),sha256=record['target_sha256'])))
