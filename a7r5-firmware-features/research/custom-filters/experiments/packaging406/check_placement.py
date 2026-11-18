"""同修改4.06的只读放置核查；不写CP/DAT、不链接到猜测RAM、不执行目标代码。"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import struct
import subprocess
import sys

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
HERE=Path(__file__).resolve().parent
from elftools.elf.elffile import ELFFile

CP_SHA='18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
BASE=0x108000
TAIL_START=0xbef9e8
TAIL_END=0xbefb80
CPIO_SHA='c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80'
DEFAULT_MODULE=ROOT/'.local/fixed-custom-filters/continuation33-software/cp-requests/cp-requests.elf'
DEFAULT_SOURCE=ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'

def sha(data): return hashlib.sha256(data).hexdigest()

def read_cpio(path,wanted):
    """只读固定来源归档，不依赖本地候选工具或导入模拟器。"""
    result={}
    with path.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=CPIO_SHA:raise ValueError('CPIO来源不符')
        f.seek(0)
        while True:
            header=f.read(110)
            if len(header)!=110 or header[:6]!=b'070701':raise ValueError('CPIO头不符')
            fields=[int(header[6+8*i:14+8*i],16) for i in range(13)]
            if not 1<=fields[11]<=4096:raise ValueError('CPIO名称长度不符')
            name=f.read(fields[11])
            if not name.endswith(b'\0'):raise ValueError('CPIO名称未终止')
            name=name[:-1].decode().removeprefix('./');f.read((-110-fields[11])%4)
            if name in wanted:
                if name in result or fields[1]&0xf000!=0x8000:raise ValueError('重复或非普通源成员')
                data=f.read(fields[6])
                if len(data)!=fields[6]:raise ValueError('CPIO短读')
                result[name]=data
            else:f.seek(fields[6],1)
            f.read((-fields[6])%4)
            if name=='TRAILER!!!':break
    if result.keys()!=set(wanted):raise ValueError('缺少指定源成员')
    return result

def label(path):
    try:return str(path.relative_to(ROOT))
    except ValueError:return str(path)

def checked_span(cp,start,bytes_,kind='RX'):
    if len(cp)!=17617008 or sha(cp)!=CP_SHA:raise ValueError('当前修改4.06 CP身份不符')
    if kind!='RX':raise ValueError('没有已分配给新增模块的RW所有权证明')
    if not isinstance(start,int) or not isinstance(bytes_,int) or bytes_<=0 or start&3:
        raise ValueError('范围/对齐不符')
    if not TAIL_START<=start<start+bytes_<=TAIL_END:
        raise ValueError('超出明确已搬迁曲线的空余RX范围；零padding不授予所有权')
    layout=json.loads((ROOT/'a7r5-firmware-features/materials/joint-layout.json').read_text())
    assert layout['target_sha256']==CP_SHA and layout['code_bytes']==742
    row=next(r for r in layout['patches'] if r['offset']+BASE==0xbef700 and r['bytes']==1152)
    before=bytes.fromhex(row['after'])
    if cp[0xbef700-BASE:0xbefb80-BASE]!=before:
        raise ValueError('曲线回收/现有包装器前像不符')
    return dict(address=hex(start),bytes=bytes_,file_offset=hex(start-BASE),
                preimage_sha256=sha(cp[start-BASE:start-BASE+bytes_]))

def elf_sizes(path):
    raw=path.read_bytes();e=ELFFile(io.BytesIO(raw))
    assert e['e_machine']=='EM_ARM' and e.little_endian
    rows=[dict(name=s.name,address=hex(s['sh_addr']),bytes=int(s['sh_size']),
               writable=bool(s['sh_flags']&1),type=s['sh_type'])
          for s in e.iter_sections() if s['sh_flags']&2]
    loads=[dict(address=hex(s['p_vaddr']),file_bytes=int(s['p_filesz']),
                memory_bytes=int(s['p_memsz']),flags=int(s['p_flags']))
           for s in e.iter_segments() if s['p_type']=='PT_LOAD']
    return dict(path=label(path),sha256=sha(raw),file_bytes=len(raw),
                sections=rows,initialized_readonly_bytes=sum(r['bytes'] for r in rows if not r['writable']),
                writable_bytes=sum(r['bytes'] for r in rows if r['writable']),
                loads=loads,writable_load_bytes=sum(r['memory_bytes'] for r in loads if r['flags']&2),
                original_link_is_research_only=any(int(r['address'],16)>=0x92000000 for r in rows))

def inspect(cp,modules=None):
    modules=[DEFAULT_MODULE] if modules is None else modules
    if not modules:raise ValueError('至少指定一个待核模块')
    # 固定同一源下的原image描述；source是相对image_base，不是独立虚拟地址。
    descriptors=[struct.unpack_from('<3I',cp,p) for p in (0x20124,0x20130,0x2013c,0x20148,0x20154)]
    assert descriptors==[(0,0xac8000,0x128000),(0xac8000,0x48f000,0xbf0000),
        (0xf57000,0x117f5c,0x107f000),(0x106f000,0x8a3b40,0x1197000),(0,0x4000,0x1a3c000)]
    span=checked_span(cp,TAIL_START,TAIL_END-TAIL_START)
    bss=descriptors[3];translation=0x128000
    page_root=lambda size:((bss[0]+size+0x4fff)&~0x3fff)+translation
    assert page_root(bss[1])==0x1a3c000
    maximum=0x1a3b000
    assert page_root(maximum-bss[2])==page_root(bss[1])
    assert page_root(maximum-bss[2]+1)!=page_root(bss[1])
    result=dict(status='BLOCKED_NO_COMPLETE_CP_EXECUTABLE_PLACEMENT',cp_sha256=CP_SHA,
        cp_bytes=len(cp),file_va_end=hex(BASE+len(cp)),image_base='0x128000',
        descriptors={name:dict(source_offset=hex(a),bytes=hex(n),destination=hex(d))
                     for name,(a,n,d) in zip(('text','rodata','data','bss','stack'),descriptors)},
        verified_reclaimed_tail=span,
        known_bss_expansion=dict(current_end=hex(bss[2]+bss[1]),layout_limit=hex(maximum),
             numeric_extra_bytes=maximum-bss[2]-bss[1],page_root=hex(page_root(bss[1])),
             already_assigned_to_module=False,executable_permission_proven=False),
        helpers=[dict(address=hex(a),bytes=n,sha256=sha(cp[a-BASE:a-BASE+n]))
                 for a,n in ((0xbef4c0,576),(0xbef6b0,60),(0xbef700,742),(0x108f40,124))],
        hook_preimages=[dict(address=hex(a),before=cp[a-BASE:a-BASE+8].hex(),patch_generated=False)
                        for a in (0x495fd8,0x496044,0x89856c)],
        modules=[elf_sizes(Path(p).absolute()) for p in modules],
        firmware_written=False,signature_created=False,hardware_or_emulator_run=False)
    for m in result['modules']:
        m['fits_verified_rx_tail']=m['initialized_readonly_bytes']<=span['bytes']
    return result

def bounded_link(objects,out):
    # 仅对已拥有的408B RX尾和“尚待明确保留”的BSS算术候选设置严格界限。
    # 这是拒绝性链接检查，预期失败；不是可刷写模块或新的RW分配声明。
    script=out/'insufficient-owned-tail.ld'
    script.write_text('''ENTRY(af_cp_hs_gate)
MEMORY { rx (rx) : ORIGIN = 0xbef9e8, LENGTH = 408
         pending_rw (rw) : ORIGIN = 0x1a3ab40, LENGTH = 1216 }
SECTIONS { .text : { *(.text*) *(.rodata*) } > rx
 .ARM.exidx : { *(.ARM.exidx*) } > rx
 .data : { *(.data*) } > pending_rw
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } > pending_rw
 /DISCARD/ : { *(.comment) *(.ARM.attributes*) } }
''')
    names=('af_slots.c.o','af_apply_wire.c.o','af_handshake.c.o','af_hs_cp406.c.o','af_hs_cp406.S.o',
           'af_cp406_state.c.o','af_cp406_state.S.o','af_cp_override406.c.o','af_cp_override406.S.o','native_memory.c.o')
    inputs=[objects/n for n in names]
    if not all(p.is_file() and not p.is_symlink() for p in inputs):raise ValueError('缺少固定配对对象')
    cmd=['/opt/homebrew/bin/ld.lld','--gc-sections','--build-id=none',
         '--undefined=af_cp_hs_configure','--undefined=af_cp_runtime_gate',
         '--undefined=af_cp_override406_snapshot_gate','-T',str(script),
         *map(str,inputs),'-o',str(out/'REJECTED-cp-requests.elf')]
    run=subprocess.run(cmd,capture_output=True,text=True)
    result=dict(command=cmd,exit_code=run.returncode,stderr=run.stderr,
        expected_rejection=bool(run.returncode!=0 and 'overflow' in run.stderr),
        objects_sha256={label(p):sha(p.read_bytes()) for p in inputs},rw_reserved=False,target_run=False)
    (out/'bounded-link.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if not result['expected_rejection']:raise ValueError(run.stderr or '预期范围拒绝未发生')

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module',type=Path,action='append',help='可重复；默认本批continuation33统一模块')
    parser.add_argument('--output',type=Path,required=True,help='全新结果目录，拒绝覆盖历史')
    parser.add_argument('--source-cpio',type=Path,default=DEFAULT_SOURCE)
    parser.add_argument('--objects',type=Path,help='可选；固定配对对象目录，用于真实尾部拒绝性链接')
    args=parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():raise ValueError('输出目录已存在，禁止覆盖')
    modules=args.module or [DEFAULT_MODULE]
    if not all(p.is_file() and not p.is_symlink() for p in modules):raise ValueError('模块须为普通文件')
    cp=read_cpio(args.source_cpio,{'cp/cpapp-b.bin'})['cp/cpapp-b.bin']
    result=inspect(cp,modules)
    args.output.mkdir(parents=True)
    (args.output/'placement.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if args.objects:bounded_link(args.objects.absolute(),args.output.absolute())
    print(json.dumps(dict(status=result['status'],known_rx_tail=result['verified_reclaimed_tail'],
        modules=result['modules'],bounded_link_checked=bool(args.objects)),indent=2))

if __name__=='__main__':main()
