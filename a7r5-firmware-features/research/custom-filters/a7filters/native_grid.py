"""AArch64机内转换核心与当前4.06 CP原网格打包函数联验，无硬件服务。"""
import hashlib
import io
import struct

from .access_evidence import CP_SHA,require_source,WORK,STACK,STOP
from .cp_machine import CpMachine
from .investigate import CP_BASE


class GridMachine:
    def __init__(self,raw):
        from elftools.elf.elffile import ELFFile
        from unicorn import Uc,UC_ARCH_ARM64,UC_PROT_READ,UC_PROT_WRITE,UC_PROT_EXEC,arm64_const as reg
        if len(raw)>0x20000:raise ValueError('网格模块超过128KiB文件预算')
        elf=ELFFile(io.BytesIO(raw));base=0x9060000
        if (elf['e_machine']!='EM_AARCH64' or elf['e_type']!='ET_EXEC' or not elf.little_endian or
            any(s['sh_type'] in ('SHT_REL','SHT_RELA') for s in elf.iter_sections())):
            raise ValueError('网格模块必须是无重定位的AArch64测试ELF')
        table=elf.get_section_by_name('.symtab')
        if table is None:raise ValueError('网格模块缺少符号表')
        self.symbols={s.name:int(s['st_value']) for s in table.iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
        for name in ('af_grid_pack','af_grid_target_check','af_grid_target_report','af_grid_target_metrics','af_grid_target_fit','af_grid_target_result'):
            if name not in self.symbols or not base<=self.symbols[name]<base+0x100000:raise ValueError('网格模块缺少限定入口')
        self.cpu=Uc(UC_ARCH_ARM64,0);self.reg=reg
        for segment in elf.iter_segments():
            if segment['p_type']!='PT_LOAD':continue
            start,end,flags=segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz'],segment['p_flags']
            if flags not in (5,6) or not base<=start<end<=base+0x100000:raise ValueError('网格模块映射/权限超出预算')
            self.cpu.mem_map(start&~4095,((end+4095)&~4095)-(start&~4095),
                UC_PROT_READ|(UC_PROT_WRITE if flags&2 else 0)|(UC_PROT_EXEC if flags&1 else 0))
            self.cpu.mem_write(start,segment.data())
        self.cpu.mem_map(WORK,0x10000,UC_PROT_READ|UC_PROT_WRITE)
        self.cpu.mem_map(STACK,0x10000,UC_PROT_READ|UC_PROT_WRITE)

    def call(self,name,*args,budget=30000000):
        for i,value in enumerate(args):self.cpu.reg_write(getattr(self.reg,'UC_ARM64_REG_X'+str(i)),value)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_SP,STACK+0xe000);self.cpu.reg_write(self.reg.UC_ARM64_REG_LR,STOP)
        self.cpu.emu_start(self.symbols[name],STOP,count=budget)
        if self.cpu.reg_read(self.reg.UC_ARM64_REG_PC)!=STOP or self.cpu.reg_read(self.reg.UC_ARM64_REG_SP)!=STACK+0xe000:
            raise ValueError('网格目标代码未在预算内返回或栈未恢复')
        return self.cpu.reg_read(self.reg.UC_ARM64_REG_W0)


def collect(cp,module):
    require_source(cp,CP_SHA,'CP')
    permutation=struct.unpack_from('<405H',cp,0xd841d8)
    if set(permutation)!=set(range(405)):raise ValueError('原CP网格排列不完整')
    a=GridMachine(module)
    try:
        check=a.call('af_grid_target_check')
        if check:raise ValueError('AArch64原生转换/量化/评估在C检查行失败：'+str(check))
        target=struct.unpack('<8I',a.cpu.mem_read(a.symbols['af_grid_target_report'],32))
        metrics=struct.unpack('<4I6f',a.cpu.mem_read(a.symbols['af_grid_target_metrics'],40))
        fit=struct.unpack('<4I2f',a.cpu.mem_read(a.symbols['af_grid_target_fit'],24))
        fitted=bytes(a.cpu.mem_read(a.symbols['af_grid_target_result'],1215))
        if target[0]!=0x47313831 or target[1]<2400 or target[3:]!=(8,1,499436,1,1215):
            raise ValueError('目标转换/取消/模型基底或工作区报告不符')
        cases=[]
        for name,level in [('signed-extremes',level) for level in range(1,9)]+[('actual-target-fit',8)]:
            m=CpMachine(cp)
            wrapper,params,profile,container,grid_state,stage,output_context,grid,out=[
                WORK+x for x in (0x100,0x400,0x800,0xc00,0x1000,0x1400,0x1800,0x3000,0x4000)]
            for at,value in ((wrapper,params),(wrapper+4,profile),(container+8,grid_state),
                (container+12,output_context),(container+16,stage),(output_context+0x6b0,out),(grid_state+0x184,grid)):
                m.word(at,value)
            m.put(params+0x2f,bytes([level]));m.put(grid_state+0x188,bytes([1,2]))
            raw=fitted if name=='actual-target-fit' else bytes(((i*29+17)%128-64)&255 for i in range(1215))
            m.put(grid,raw);m.put(out-16,b'\xa5'*1652)
            m.run(0x231654,arguments=(wrapper,container),limit=100000)
            packed=m.read(out,1620);values=struct.unpack('1215b',raw);expected=[0]*405
            for i,destination in enumerate(permutation):
                expected[destination]=sum((((values[c*405+i]*level)//8)&127)<<(22-10*c) for c in range(3))
            if packed!=struct.pack('<405I',*expected):raise ValueError('原CP完整网格打包与独立字节期望不符')
            if m.read(out-16,16)!=b'\xa5'*16 or m.read(out+1620,16)!=b'\xa5'*16 or m.read(grid,1215)!=raw:
                raise ValueError('原CP网格打包破坏源表或输出边界')
            a.cpu.mem_write(WORK+0x1000,raw);a.cpu.mem_write(WORK+0x2000,struct.pack('<405H',*permutation))
            a.cpu.mem_write(WORK+0x3000,b'\xa5'*1620)
            if a.call('af_grid_pack',WORK+0x1000,WORK+0x2000,level,WORK+0x3000) or bytes(a.cpu.mem_read(WORK+0x3000,1620))!=packed:
                raise ValueError('新AArch64打包与原CP打包不一致')
            cases.append(dict(name=name,level=level,bytes=1620,sha256=hashlib.sha256(packed).hexdigest(),
                native_cp_executed=True,new_ap_pack_equal=True,bounds_preserved=True))
            m.cpu=None
        from .cp_grid_route import collect as controller
        native_controller=controller(cp,fitted)
        return dict(status='OFFLINE_NATIVE_GRID_CONVERTER_VERIFIED',cp_sha256=CP_SHA,
            module=dict(bytes=len(module),sha256=hashlib.sha256(module).hexdigest()),
            actual_target_grid_sha256=hashlib.sha256(fitted).hexdigest(),
            target_checks=target,target_metrics=dict(samples=metrics[0],clipped=metrics[1],gray=metrics[2],skin=metrics[3],
                delta_e76=list(metrics[4:9]),rgb_rmse=metrics[9]),target_fit=dict(iterations=fit[0],zero_mse=fit[4],quantized_mse=fit[5]),
            cp_entry=hex(0x231654),permutation_file_offset=hex(0xd841d8),cases=cases,
            native_controller=native_controller,
            source_channels='3 planar signed7 planes, 405 nodes each; source index maps to destination word',
            native_pixel_effect_verified=False,physical_model_verified_on_this_firmware=False,
            actual_lut_installation=False,camera_io=False,firmware_modified=False)
    finally:a.cpu=None
