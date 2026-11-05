"""执行原Fsys纯编码器；不初始化卷、不调用设备、不模拟CP／ISP。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as regs

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406'))
from candidate_preflight import read_cpio


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    out=parser.parse_args().output.absolute()
    assert out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists()
    source=ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    raw=read_cpio(source,{'usr/lib/libInfraFsys.so'})['usr/lib/libInfraFsys.so']
    digest=hashlib.sha256(raw).hexdigest()
    assert digest=='1986525ba65519a00ee5f41fbf40d2651bfcccb518bbb1e7e8e7fc0a58db7c5b'
    elf=ELFFile(io.BytesIO(raw));symbols=elf.get_section_by_name('.dynsym')
    exports={s.name:s for s in symbols.iter_symbols() if s.name and s['st_shndx']!='SHN_UNDEF'}
    names={'PFEX_PFCODE_UTF8_OEM2Unicode':0x9445c,'PFEX_PFCODE_UTF8_Unicode2OEM':0x945c4}
    assert all(int(exports[n]['st_value'])==a for n,a in names.items())
    base=0x40000000;stop=0x60000000;stack=0x60010000;input_at=0x60020000;output_at=0x60021000
    cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    loads=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
    for segment in loads:
        low=int(segment['p_vaddr'])&~4095;high=(int(segment['p_vaddr']+segment['p_memsz'])+4095)&~4095
        cpu.mem_map(base+low,high-low)
        cpu.mem_write(base+int(segment['p_vaddr']),segment.data())
    # 不运行构造器；仅重定位原模块内符号，未知外部符号留零，意外调用会直接失败。
    for section in elf.iter_sections():
        if section['sh_type']!='SHT_RELA':continue
        table=elf.get_section(section['sh_link'])
        for relocation in section.iter_relocations():
            kind=relocation['r_info_type'];addend=int(relocation['r_addend'])
            if kind==1027:value=base+addend
            elif kind in (257,1025,1026):
                symbol=table.get_symbol(relocation['r_info_sym'])
                value=base+int(symbol['st_value'])+addend if symbol['st_shndx']!='SHN_UNDEF' else 0
            else:raise ValueError(f'未支持的原Fsys重定位{kind}')
            cpu.mem_write(base+int(relocation['r_offset']),value.to_bytes(8,'little'))
    for segment in loads:
        low=int(segment['p_vaddr'])&~4095;high=(int(segment['p_vaddr']+segment['p_memsz'])+4095)&~4095
        flags=int(segment['p_flags']);permission=(1 if flags&4 else 0)|(2 if flags&2 else 0)|(4 if flags&1 else 0)
        cpu.mem_protect(base+low,high-low,permission)
    cpu.mem_map(stop,4096);cpu.mem_map(stack,65536);cpu.mem_map(input_at,8192)

    def call(name,source_bytes,wanted):
        cpu.mem_write(input_at,source_bytes+bytes(8))
        cpu.mem_write(output_at,b'\xa5'*32)
        for reg,value in ((regs.UC_ARM64_REG_X0,input_at),(regs.UC_ARM64_REG_X1,output_at),
                          (regs.UC_ARM64_REG_SP,stack+0x8000),(regs.UC_ARM64_REG_LR,stop)):
            cpu.reg_write(reg,value)
        cpu.emu_start(base+names[name],stop,count=10000)
        assert cpu.reg_read(regs.UC_ARM64_REG_PC)==stop
        assert cpu.reg_read(regs.UC_ARM64_REG_SP)==stack+0x8000
        actual=bytes(cpu.mem_read(output_at,32))
        assert actual==wanted+b'\xa5'*(32-len(wanted))
        return cpu.reg_read(regs.UC_ARM64_REG_X0)&0xffffffff

    cases=[]
    for text in ('暖光.cube','照片FL2_🎨.a7filter','é_e\u0301.cube'):
        for character in text:
            utf8=character.encode('utf-8');utf16=character.encode('utf-16le')
            # 原PFCODE_Combine_Width(59FBC)把OEM字节数放高半字，Unicode字节数放低半字。
            expected=(len(utf8)<<16)|len(utf16)
            a=call('PFEX_PFCODE_UTF8_OEM2Unicode',utf8,utf16)
            b=call('PFEX_PFCODE_UTF8_Unicode2OEM',utf16,utf8)
            assert a==b==expected,(character,a,b,expected)
            cases.append(dict(character=character,utf8=utf8.hex(),utf16le=utf16.hex(),packed_width=a))
    result=dict(status='PASS_ORIGINAL_FSYS_UTF8_CODEC_SOFTWARE_EXECUTION',library_sha256=digest,
                functions=names,cases=cases,original_AP_CP_modified=False,
                original_Fsys_initialization_executed=False,original_Fsys_volume_IO_executed=False,
                actual_SD_verified=False,CP_ISP_hardware_emulated=False,camera_io=False,
                source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out.mkdir(parents=True)
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','library_sha256','actual_SD_verified')},ensure_ascii=False))


if __name__=='__main__':main()
