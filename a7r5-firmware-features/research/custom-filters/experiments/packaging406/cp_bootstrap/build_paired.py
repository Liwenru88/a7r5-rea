"""交叉链接原RX尾准入与永久回退；不执行目标、不写CP镜像。"""
from pathlib import Path
import argparse, hashlib, io, json, subprocess, sys

D=Path(__file__).resolve().parent
R=next(p for p in D.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
SOURCE=D/'bootstrap'
sys.path.insert(0,str(R/'a7r5-desktop/prepared/engine/site'))
from elftools.elf.elffile import ELFFile

def sha(data): return hashlib.sha256(data).hexdigest()

def crc(raw):
    value=0
    for byte in raw:
        value^=byte<<24
        for _ in range(8):
            value=((value<<1)^(0x04c11db7 if value&0x80000000 else 0))&0xffffffff
    return value

def checked_module(receipt_path):
    raw=receipt_path.read_bytes(); receipt=json.loads(raw)
    for name,digest in receipt['source_sha256'].items():
        if sha((R/name).read_bytes())!=digest: raise ValueError('模块源已改变: '+name)
    a=receipt['artifact']; data=(R/a['path']).read_bytes()
    if len(data)!=a['bytes'] or sha(data)!=a['sha256']: raise ValueError('模块ELF身份不符')
    elf=ELFFile(io.BytesIO(data))
    if elf['e_machine']!='EM_ARM' or not elf.little_endian: raise ValueError('模块ABI不符')
    loads=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
    if [(s['p_vaddr'],s['p_filesz'],s['p_memsz'],s['p_flags']) for s in loads]!=[
        (0x1a3b000,3352,3352,5),(0x1a3ab40,4,288,6)]: raise ValueError('模块布局漂移')
    payloads=[]
    for item,seg in zip(receipt['payloads'],loads):
        raw_payload=(R/item['path']).read_bytes()
        full=seg.data()+bytes(seg['p_memsz']-seg['p_filesz'])
        if raw_payload!=full or len(full)!=item['bytes'] or sha(full)!=item['sha256']:
            raise ValueError('模块载荷与ELF不一致')
        payloads.append(full)
    rx,rw=payloads
    if rw!=bytes.fromhex('feffffff')+bytes(284): raise ValueError('RW出现未支持的初始化值')
    if receipt['expected_snapshot_entry']!=0xbefb35: raise ValueError('外层快照入口未配对')
    if any(s['sh_type'] in ('SHT_REL','SHT_RELA') and s['sh_size'] for s in elf.iter_sections()):
        raise ValueError('模块仍有重定位')
    symbols={v.name:int(v['st_value']) for v in elf.get_section_by_name('.symtab').iter_symbols()}
    return receipt,raw,rx,rw,symbols

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module-receipt',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    a.output=a.output.resolve();a.module_receipt=a.module_receipt.resolve()
    if not a.output.is_relative_to(R/'.local/fixed-custom-filters'):
        raise ValueError('输出只允许本任务隔离目录')
    if a.output.exists() or a.output.is_symlink(): raise ValueError('输出已存在，禁止覆盖回执')
    receipt,receipt_raw,rx,rw,s=checked_module(a.module_receipt)
    watched=[SOURCE/'guard.c',SOURCE/'gates.S',Path(__file__),a.module_receipt]
    before={str(path):sha(path.read_bytes()) for path in watched}
    B=a.output; B.mkdir(parents=True)
    header=(
        '#define AF_RX_BYTES 3352u\n#define AF_RW_BYTES 288u\n'
        '#define AF_PHASE_ADDRESS 0x1a3ac60\n'
        '#define AF_PAYLOAD_BYTES AF_RX_BYTES\n'
        f'#define AF_RX_CRC 0x{crc(rx):x}u\n#define AF_PAYLOAD_CRC AF_RX_CRC\n')
    (B/'image_constants.h').write_text(header)
    ld='''ENTRY(af_boot34_prepare)
SECTIONS { . = 0xbef9e8; .text : { *(.text*) *(.rodata*) }
 /DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) } }
ASSERT(SIZEOF(.text) <= 408, "owned RX tail exceeded");
ASSERT(af_boot34_descriptor >= 0x800000 && af_boot34_descriptor < 0x1000000, "descriptor count interval");
ASSERT(af_boot34_snapshot == 0xbefb35, "paired snapshot entry drift");
'''
    for name,value in dict(stock_copy=0x5f51bc,stock_zero=0x5f58b0,
        stock_dcache=0x5f3524,stock_icache=0x5f2cf0,stock_lock_fn=0x5b8d6c,
        compact_start=s['af_cp_runtime_gate'],compact_hs=s['af_cp_hs_gate'],
        compact_snapshot=s['af_cp_override406_snapshot_gate']).items():
        ld+=f'{name} = 0x{value:x};\n'
    (B/'bootstrap.ld').write_text(ld)
    commands=[];compiled_sources={}
    for name in ('guard.c','gates.S'):
        # 引号头文件先搜索源文件目录；在新构建目录编译精确副本，避免旧邻接头遮蔽。
        local_source=B/name;local_source.write_bytes((SOURCE/name).read_bytes())
        compiled_sources[str(local_source)]=sha(local_source.read_bytes())
        cmd=['clang','--target=armv7a-none-eabi','-mthumb','-march=armv7-a','-mfpu=none',
            '-mfloat-abi=soft','-fno-vectorize','-fno-slp-vectorize','-Wall','-Wextra','-Werror','-Oz','-ffreestanding',
            '-fno-builtin','-fno-stack-protector','-fno-unwind-tables',
            '-fno-asynchronous-unwind-tables','-I'+str(B),'-c',str(local_source),
            '-o',str(B/(name+'.o'))]
        r=subprocess.run(cmd,capture_output=True,text=True)
        commands.append(dict(argv=cmd,exit_code=r.returncode,stderr=r.stderr))
        if r.returncode: raise ValueError(r.stderr)
    cmd=['/opt/homebrew/bin/ld.lld','--no-undefined','--build-id=none','-T',str(B/'bootstrap.ld'),str(B/'guard.c.o'),
        str(B/'gates.S.o'),'-o',str(B/'bootstrap.elf')]
    r=subprocess.run(cmd,capture_output=True,text=True)
    commands.append(dict(argv=cmd,exit_code=r.returncode,stderr=r.stderr))
    if r.returncode: raise ValueError(r.stderr)
    data=(B/'bootstrap.elf').read_bytes(); e=ELFFile(io.BytesIO(data)); sec=e.get_section_by_name('.text')
    names={v.name:dict(address=int(v['st_value']),bytes=int(v['st_size']))
           for v in e.get_section_by_name('.symtab').iter_symbols()
           if v.name.startswith('af_boot34') or v.name in ('crc','page','map')}
    if sec['sh_addr']!=0xbef9e8 or sec['sh_size']!=408: raise ValueError('引导范围漂移')
    # 固定408B布局中此字是prepare使用的CRC literal，必须核实际目标码而非只读元数据。
    actual_crc=int.from_bytes(sec.data()[168:172],'little')
    if actual_crc!=crc(rx):raise ValueError('实际目标CRC常量与当前RX不匹配')
    all_symbols={v.name:int(v['st_value']) for v in e.get_section_by_name('.symtab').iter_symbols()}
    phase_at=all_symbols['phase'];phase_offset=phase_at-int(sec['sh_addr'])
    phase_value=int.from_bytes(sec.data()[phase_offset:phase_offset+4],'little')
    if phase_value!=0x1a3ab40+len(rw) or phase_value+4>0x1a3b000:
        raise ValueError('实际phase字与RW尾不匹配或越界')
    if any(s['sh_type'] in ('SHT_REL','SHT_RELA') and s['sh_size'] for s in e.iter_sections()):
        raise ValueError('引导仍有重定位')
    (B/'bootstrap-rx.bin').write_bytes(sec.data())
    if before!={str(path):sha(path.read_bytes()) for path in watched}:
        raise ValueError('构建期间源或输入回执变化')
    if compiled_sources!={name:sha(Path(name).read_bytes()) for name in compiled_sources} or (B/'image_constants.h').read_text()!=header:
        raise ValueError('实际编译副本或生成头变化')
    result=dict(status='PAIRED_LINK_PASS_STATIC_ONLY',bytes=sec['sh_size'],fits_408=True,
        module_receipt=str(a.module_receipt),module_receipt_sha256=sha(receipt_raw),
        module_artifact=receipt['artifact'],module_source_sha256=receipt['source_sha256'],
        RX_source_address='0x11d2000',RX_bytes=len(rx),RX_sha256=sha(rx),RX_crc_msb_init0=hex(crc(rx)),
        RW_bytes=len(rw),RW_sha256=sha(rw),RW_initialization='zero288_then_store_u32_fffffffe',
        phase_address='0x1a3ac60',
        functions=names,source_sha256=before,
        bootstrap_elf_sha256=sha(data),bootstrap_raw_sha256=sha(sec.data()),commands=commands,
        compiled_source_sha256=compiled_sources,actual_crc_literal_offset=168,
        actual_crc_literal=hex(actual_crc),actual_crc_literal_matches=True,
        actual_phase_literal_address=hex(phase_at),actual_phase_literal=hex(phase_value),
        actual_phase_after_RW_verified=True,
        target_executed=False,CP_written=False,installed=False,installable_firmware=False)
    (B/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','bytes','fits_408','functions','RX_crc_msb_init0')},indent=2))

if __name__=='__main__': main()
