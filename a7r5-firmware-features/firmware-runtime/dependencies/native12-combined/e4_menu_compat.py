"""独立E4菜单覆盖层：保留原dispatch，仅消费所属私有页的值刷新事件。"""
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
from elftools.elf.elffile import ELFFile

HERE=Path(__file__).resolve().parent
SOURCE_SHA='a1e6a6472e200e5554426d54b73e1b031dfb2a75251a1854b124e223a08b68c5'
START=0x8e9fb00
DISPATCH=0x8e996bc
PROLOGUE=bytes.fromhex('fd7bbca9f85f01a9fd030091f65702a9')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def build(raw,output):
    if sha(raw)!=SOURCE_SHA:raise ValueError('E4菜单补丁完整前像不符')
    output=Path(output);output.mkdir(mode=0o700)
    layout=output/'e4-menu.ld';elf=output/'e4-menu.elf'
    layout.write_text('ENTRY(native12_e4_dispatch)\nnative12_private_page_state = 0x8eba610; native12_dispatch_continue = 0x8e996cc;\n'
        'SECTIONS { . = 0x8e9fb00; .text : { *(.text.native12_e4_dispatch) *(.text*) *(.rodata*) } .data : { *(.data*) } .bss : { *(.bss*) } /DISCARD/ : { *(.comment*) *(.eh_frame*) } }\n')
    command=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-none-elf','-Oz','-ffunction-sections','-ffreestanding','-fno-builtin','-fno-stack-protector','-mgeneral-regs-only','-nostdlib',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-Wl,-T,'+str(layout),'-Wl,--build-id=none',str(HERE/'e4-menu-compat.c'),'-o',str(elf)]
    result=subprocess.run(command,capture_output=True,text=True);(output/'compiler.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('E4菜单覆盖层编译失败')
    e=ELFFile(io.BytesIO(elf.read_bytes()));section=e.get_section_by_name('.text');code=section.data()
    if section['sh_addr']!=START or e.header['e_entry']!=START or START+len(code)>0x8ea0000:raise ValueError('E4菜单代码超出原RX页')
    if any(s['sh_size'] for s in e.iter_sections() if s.name in ('.data','.bss')):raise ValueError('E4菜单覆盖层不能新增可写状态')
    source=ELFFile(io.BytesIO(raw));index,rx=next((i,s) for i,s in enumerate(source.iter_segments()) if s['p_type']=='PT_LOAD' and s['p_vaddr']==0x8e90000)
    if rx['p_flags']!=5 or rx['p_offset']!=0x5ce0000 or rx['p_filesz']!=rx['p_memsz'] or rx['p_filesz']>START-rx['p_vaddr']:raise ValueError('E4菜单RX段布局不符')
    at=rx['p_offset']+START-rx['p_vaddr'];entry=rx['p_offset']+DISPATCH-rx['p_vaddr']
    if raw[at:at+len(code)]!=bytes(len(code)) or raw[entry:entry+16]!=PROLOGUE:raise ValueError('E4菜单入口／零填充窗前像不符')
    target=bytearray(raw);patches=[]
    def put(off,data,reason):
        patches.append(dict(offset=off,before=raw[off:off+len(data)].hex(),after=data.hex(),reason=reason));target[off:off+len(data)]=data
    put(at,code,'私有页值刷新事件的所有权门禁及原dispatch跳板')
    put(entry,struct.pack('<I',0x14000000|(((START-DISPATCH)//4)&0x3ffffff)),'原私有dispatch入口跳转至独立覆盖层')
    header=source.header['e_phoff']+index*source.header['e_phentsize'];size=START-rx['p_vaddr']+len(code)
    put(header+32,struct.pack('<QQ',size,size),'扩展现有RX段长度，仍在同一映射页')
    reverse=bytearray(target)
    for row in patches:reverse[row['offset']:row['offset']+len(bytes.fromhex(row['before']))]=bytes.fromhex(row['before'])
    if reverse!=raw:raise ValueError('E4菜单补丁不能精确逆还原')
    path=output/'appFw.so';path.write_bytes(target)
    receipt=dict(source_sha256=SOURCE_SHA,target_sha256=sha(target),entry=START,code_bytes=len(code),patches=patches,inverse_exact=True,
        source_C_sha256=sha((HERE/'e4-menu-compat.c').read_bytes()),command=command,upstream_modified=False,old_DAT_modified=False,camera_io=False)
    (output/'e4-menu-patch.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return path,receipt
