"""AArch64联合搜索与当前CP组件整数窗口；不提供机身颜色预测。"""
import hashlib
import io
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK,STACK,STOP


class JointMachine:
    def __init__(self,raw):
        from elftools.elf.elffile import ELFFile
        from unicorn import Uc,UC_ARCH_ARM64,UC_PROT_READ,UC_PROT_WRITE,UC_PROT_EXEC,arm64_const as reg
        if len(raw)>0x20000:raise ValueError('联合模块超过128KiB文件预算')
        elf=ELFFile(io.BytesIO(raw));base=0x9080000
        if (elf['e_machine']!='EM_AARCH64' or elf['e_type']!='ET_EXEC' or not elf.little_endian or
            any(s['sh_type'] in ('SHT_REL','SHT_RELA') for s in elf.iter_sections())):
            raise ValueError('联合模块必须是无重定位AArch64研究ELF')
        table=elf.get_section_by_name('.symtab')
        if table is None:raise ValueError('联合模块缺少符号表')
        self.symbols={s.name:int(s['st_value']) for s in table.iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
        gamma_names=('af_gamma406_axis','af_gamma406_locate','af_gamma406_replace')
        import_names=('af_import_target_check','af_import_target_report','af_import_target_metrics')
        color_names=('af_color406_matrix','af_color406_primary','af_color406_secondary','af_color406_add','af_color406_blend',
                     'af_color406_target_check','af_color406_target_report')
        consume_names=('af_color406_adjust','af_color406_matrix_blend')
        if any(n in self.symbols for n in gamma_names) and not all(n in self.symbols for n in gamma_names):
            raise ValueError('Gamma扩展入口必须完整提供')
        if any(n in self.symbols for n in import_names) and not all(n in self.symbols for n in import_names):
            raise ValueError('导入扩展入口必须完整提供')
        if any(n in self.symbols for n in color_names) and not all(n in self.symbols for n in color_names):
            raise ValueError('颜色扩展入口必须完整提供')
        if any(n in self.symbols for n in consume_names) and not all(n in self.symbols for n in color_names+consume_names):
            raise ValueError('颜色消费扩展入口必须完整提供')
        required=('af_joint_gamma_record','af_joint_expand_matrix','af_joint_target_check',
                  'af_joint_target_report','af_joint_target_metrics')
        if all(n in self.symbols for n in gamma_names):required+=gamma_names
        if all(n in self.symbols for n in import_names):required+=import_names
        if all(n in self.symbols for n in color_names):required+=color_names
        if all(n in self.symbols for n in consume_names):required+=consume_names
        for name in required:
            if name not in self.symbols or not base<=self.symbols[name]<base+0x100000:
                raise ValueError('联合模块缺少限定入口')
        self.cpu=Uc(UC_ARCH_ARM64,0);self.reg=reg
        for segment in elf.iter_segments():
            if segment['p_type']!='PT_LOAD':continue
            start,end,flags=segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz'],segment['p_flags']
            if flags not in (5,6) or not base<=start<end<=base+0x100000:
                raise ValueError('联合模块映射/权限超出预算')
            self.cpu.mem_map(start&~4095,((end+4095)&~4095)-(start&~4095),
                UC_PROT_READ|(UC_PROT_WRITE if flags&2 else 0)|(UC_PROT_EXEC if flags&1 else 0))
            self.cpu.mem_write(start,segment.data())
        for at in (WORK,STACK):self.cpu.mem_map(at,0x10000,UC_PROT_READ|UC_PROT_WRITE)

    def call(self,name,*args,budget=10000000):
        for i,value in enumerate(args):self.cpu.reg_write(getattr(self.reg,'UC_ARM64_REG_X'+str(i)),value)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_SP,STACK+0xe000)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_LR,STOP)
        self.cpu.emu_start(self.symbols[name],STOP,count=budget)
        if (self.cpu.reg_read(self.reg.UC_ARM64_REG_PC)!=STOP or
            self.cpu.reg_read(self.reg.UC_ARM64_REG_SP)!=STACK+0xe000):
            raise ValueError('联合目标代码未在预算内返回或栈未恢复')
        return self.cpu.reg_read(self.reg.UC_ARM64_REG_W0)


def collect(cp,module):
    require_source(cp,CP_SHA,'CP')
    a=JointMachine(module)
    try:
        failure=a.call('af_joint_target_check')
        if failure:raise ValueError('AArch64联合契约在C检查行失败：'+str(failure))
        report=struct.unpack('<8I',a.cpu.mem_read(a.symbols['af_joint_target_report'],32))
        metrics=struct.unpack('<2f',a.cpu.mem_read(a.symbols['af_joint_target_metrics'],8))
        if report[0]!=0x4a323031 or report[1]<1800 or report[2]!=65 or report[4:6]!=(15,1) or report[6]<4:
            raise ValueError('联合组件/预算/取消报告不符')
        if not 0<=metrics[1]<metrics[0]*.1:raise ValueError('合成后端完整组合选优未改善')
        gamma=[]
        stock=cp[0xcc4a0c:0xcc4a0c+576]
        for name,raw,tone in [('current-ST',stock,tone) for tone in
                ((0,0,0),(37,-41,57),(-128,70,-11),(1024,0,0))]+[
                ('upper-domain',struct.pack('<129I',*[(i*i*262143)//16384 for i in range(129)])+b'\x6a'*60,(1024,0,0))]:
            m=CpMachine(cp)
            try:
                sp=STACK+0x8000;m.put(sp-16,b'\xa5'*608);m.put(sp,raw)
                m.register('sp',sp)
                for reg,value in zip(('r9','r10','r11'),tone):m.register(reg,value&0xffffffff)
                m.run(0xbef948,0xbef9ae,returned=False,preserve_state=True)
                result=m.read(sp,576)
                a.cpu.mem_write(WORK+0x1000,raw);a.cpu.mem_write(WORK+0x2000,struct.pack('<3h',*tone))
                a.cpu.mem_write(WORK+0x3000,b'\xa5'*576)
                if a.call('af_joint_gamma_record',WORK+0x1000,WORK+0x2000,WORK+0x3000):
                    raise ValueError('新联合Gamma拒绝原有效记录')
                if bytes(a.cpu.mem_read(WORK+0x3000,576))!=result:
                    raise ValueError('新Gamma与当前CP整数窗口不一致')
                if m.read(sp-16,16)!=b'\xa5'*16 or m.read(sp+576,16)!=b'\xa5'*16 or m.register('sp')!=sp:
                    raise ValueError('CP Gamma窗口破坏曲线边界/栈')
                gamma.append(dict(source=name,tone=tone,bytes=576,sha256=hashlib.sha256(result).hexdigest(),
                                  cp_window='0xbef948..0xbef9ae',aarch64_equal=True,bounds_preserved=True))
            finally:m.cpu=None
        matrix=[i*31-256 for i in range(18)]
        a.cpu.mem_write(WORK+0x1000,struct.pack('<18h',*matrix))
        if a.call('af_joint_expand_matrix',WORK+0x1000,WORK+0x2000):raise ValueError('新矩阵展开失败')
        expanded=struct.unpack('<27h',a.cpu.mem_read(WORK+0x2000,54));expected=[]
        for offset in range(0,18,6):
            x,y,z,u,v,w=matrix[offset:offset+6];expected.extend((x+y,-x,-y,-z,z+u,-u,-v,-w,v+w))
        if tuple(expected)!=expanded:raise ValueError('新矩阵六项展开排列不符')
        additions=[]
        for name,delta,start,end in (('matrix',expanded,0xbef762,0xbef772),
                                    ('cc1',tuple(i*37-400 for i in range(24)),0xbef7c2,0xbef7d2)):
            m=CpMachine(cp)
            try:
                count=len(delta);destination=WORK+0x1000;source=WORK+0x2000
                baseline=[(0x7f00+i*129)&65535 for i in range(count)]
                m.put(destination-16,b'\xa5'*(count*2+32));m.put(destination,struct.pack('<'+'H'*count,*baseline))
                m.put(source,struct.pack('<'+'h'*count,*delta));m.register('r4',destination);m.register('r6',source);m.register('r3',count)
                m.run(start,end,returned=False)
                actual=m.read(destination,count*2)
                if actual!=struct.pack('<'+'H'*count,*[(b+d)&65535 for b,d in zip(baseline,delta)]):
                    raise ValueError('原矩阵/CC1半字增量次序不符')
                if m.read(destination-16,16)!=b'\xa5'*16 or m.read(destination+count*2,16)!=b'\xa5'*16:
                    raise ValueError('原矩阵/CC1增量窗口破坏边界')
                additions.append(dict(component=name,shorts=count,cp_window=hex(start)+'..'+hex(end),
                    sha256=hashlib.sha256(actual).hexdigest(),signed_delta_low16_store_equal=True,bounds_preserved=True))
            finally:m.cpu=None
        result=dict(status='OFFLINE_JOINT_CORE_VERIFIED',cp_sha256=CP_SHA,
            module=dict(bytes=len(module),sha256=hashlib.sha256(module).hexdigest()),target_checks=report,
            synthetic_training_mse=dict(initial=metrics[0],final=metrics[1]),gamma_cases=gamma,endpoint_additions=additions,
            original_st_gamma_file_offset=hex(0xcc4a0c),original_st_gamma_sha256=hashlib.sha256(stock).hexdigest(),
            actual_full_color_backend=False,whole_joint_lut_conversion_complete=False,hardware_apply_verified=False,
            heldout_joint_delta_e_verified=False,original_functions_complete=False,camera_io=False,input_modified=False,
            fixture_boundaries=['synthetic coupled predictor, not a CP pixel model',
                'Gamma arithmetic window with declared registers/stack record',
                'post-native endpoint addition windows with synthetic baseline words'])
        if 'af_gamma406_axis' in a.symbols:
            from .cp_gamma406 import collect as collect_gamma
            result['native_gamma_context']=collect_gamma(cp,a)
        if 'af_import_target_check' in a.symbols:
            failure=a.call('af_import_target_check',budget=100000000)
            if failure:raise ValueError('AArch64导入事务在C检查行失败：'+str(failure))
            check=struct.unpack('<8I',a.cpu.mem_read(a.symbols['af_import_target_report'],32))
            metric=struct.unpack('<7f',a.cpu.mem_read(a.symbols['af_import_target_metrics'],28))
            if (check[0]!=0x49323231 or check[1]<2200 or not 0<check[2]<0x30000 or
                not 0<check[3]<4096 or check[4:]!=(1943,5,71,1) or
                not 0<=metric[1]<metric[0] or not all(0<=v<.3 for v in metric[2:])):
                raise ValueError('AArch64导入事务报告/预算不符')
            result['offline_import_transaction']=dict(status='OFFLINE_IMPORT_TRANSACTION_VERIFIED',
                target_checks=check,synthetic_training_mse=dict(initial=metric[0],final=metric[1]),
                synthetic_heldout_delta_e76=list(metric[2:]),
                wire_bytes=1943,final_gamma_semantics=True,storage='explicit in-memory test backend',
                actual_color_model=False,actual_ap_import_task=False,hardware_apply_verified=False,
                sd_io=False,camera_io=False)
        if 'af_color406_matrix' in a.symbols:
            from .cp_color406 import collect as collect_color
            result['native_color_context']=collect_color(cp,a)
        if 'af_color406_matrix_blend' in a.symbols:
            from .cp_color_consumption406 import collect as collect_consumption
            result['native_color_consumption']=collect_consumption(cp,a)
            from .cp_context406 import collect as collect_context
            result['native_original_color_context']=collect_context(cp)
        return result
    finally:a.cpu=None
