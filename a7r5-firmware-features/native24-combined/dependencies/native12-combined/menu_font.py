"""4.10 私有菜单字体的独立派生补丁；旧升级包和上游快照保持。"""
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
from elftools.elf.elffile import ELFFile

HERE=Path(__file__).resolve().parent
SOURCE_SHA='25d79cffe07c44b094020d162e07ea2ac995cf929f1886dc5dbac6be78ba6520'
LIBOBJ_SHA='0d0be8f1e48b3c74330f9afab698ac352b3c2a922f7231ffc836591529a9fdf9'
START=0x8e9f740
CALL=0x8e98468


def sha(raw):return hashlib.sha256(raw).hexdigest()


def build(raw,output):
    if sha(raw)!=SOURCE_SHA:raise ValueError('字体补丁 AP 完整前像不符')
    output.mkdir(mode=0o700)
    layout=output/'font.ld';elf=output/'font.elf'
    layout.write_text('ENTRY(native12_menu_font)\nfont_dlsym = 0x16dac90; original_string = 0x16d9370;\nSECTIONS { . = 0x8e9f740; .text : { *(.text*) *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) } /DISCARD/ : { *(.comment*) *(.eh_frame*) } }\n')
    cmd=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-none-elf','-Oz','-ffreestanding','-fno-builtin','-fno-stack-protector','-mgeneral-regs-only','-nostdlib',
         '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-Wl,-T,'+str(layout),'-Wl,--build-id=none',str(HERE/'menu-font.c'),'-o',str(elf)]
    c=subprocess.run(cmd,capture_output=True,text=True);(output/'compiler.log').write_text(c.stdout+c.stderr)
    if c.returncode:raise RuntimeError('字体覆盖层编译失败')
    e=ELFFile(io.BytesIO(elf.read_bytes()));section=e.get_section_by_name('.text');code=section.data()
    if section['sh_addr']!=START or len(code)>0x10000-(START-0x8e90000):raise ValueError('字体代码超出预留页')
    if any(s['sh_size'] for s in e.iter_sections() if s.name in ('.data','.bss')):raise ValueError('字体覆盖层不能新增可写状态')
    source=ELFFile(io.BytesIO(raw));segs=list(source.iter_segments())
    index,rx=next((i,s) for i,s in enumerate(segs) if s['p_type']=='PT_LOAD' and s['p_vaddr']==0x8e90000)
    if (rx['p_flags'],rx['p_offset'],rx['p_filesz'],rx['p_memsz'],rx['p_align'])!=(5,0x5ce0000,63288,63288,65536):raise ValueError('AP 覆盖层布局不符')
    at=rx['p_offset']+START-rx['p_vaddr'];call=rx['p_offset']+CALL-rx['p_vaddr']
    target=bytearray(raw)
    if target[at:at+len(code)]!=bytes(len(code)):raise ValueError('字体窗口不是零填充')
    def branch(dest):return struct.pack('<I',0x14000000|(((dest-CALL)//4)&0x3ffffff))
    if raw[call:call+4]!=branch(0x16d9370):raise ValueError('私有字符串分支不符')
    patches=[]
    def put(off,after,reason):
        before=raw[off:off+len(after)];target[off:off+len(after)]=after
        patches.append(dict(offset=off,before=before.hex(),after=after.hex(),reason=reason))
    put(at,code,'原生字体属性克隆和 FONT_S_CHINESE')
    put(call,branch(START),'仅重定向私有菜单动态字符串')
    header=source.header['e_phoff']+index*source.header['e_phentsize'];size=START-rx['p_vaddr']+len(code)
    put(header+32,struct.pack('<QQ',size,size),'扩展现有 RX 段文件／内存长度，不增加映射页')
    reverse=bytearray(target)
    for p in patches:reverse[p['offset']:p['offset']+len(bytes.fromhex(p['before']))]=bytes.fromhex(p['before'])
    if reverse!=raw:raise ValueError('不能精确逆还原')
    (output/'appFw.so').write_bytes(target)
    receipt=dict(source_sha256=SOURCE_SHA,target_sha256=sha(target),code_bytes=len(code),entry=START,patches=patches,inverse_exact=True,
                 source_C_sha256=sha((HERE/'menu-font.c').read_bytes()),command=cmd,upstream_modified=False,old_DAT_modified=False,camera_io=False)
    (output/'font-patch.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return output/'appFw.so',receipt
