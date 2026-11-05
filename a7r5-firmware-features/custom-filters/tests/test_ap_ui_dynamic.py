"""动态AP绑定、原跳板和描述符恢复；服务边界明确，不冒充完整客体画面。"""
import io
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UcError
from unicorn import arm64_const as regs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7filters.ap_ui_hooks import HOOKS, CALL_TARGETS, branch

NATIVE = Path(__file__).resolve().parents[1]/'native'
SPAN = 0x8e84000
SHA = 'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'
STOCK = [h for h in HOOKS if h[3]]
WORDS = [0xa9be7bfd,0xa9bc7bfd,0xa9bb7bfd,0x5282bb03,0xb9402060,
         0xa9bc7bfd,0xa9bd7bfd,0xa9b97bfd,0xa9b97bfd,0xa9bd7bfd,
         0xa9bd7bfd,0xa9b87bfd,0xa9b67bfd] + [0xa9bc7bfd]*8 + [0xa9bb7bfd]*2 + [0x528566c2,0xa9be7bfd,0xa9be7bfd,0xa9bd7bfd,0xa9bc7bfd,0xa9b97bfd,0xa9bc7bfd,0xa9b67bfd]+[0xa9b87bfd]*4+[0xa9b77bfd]*4
EXTRA = {0x219750c:0x97ffff08,0x2199cc4:0x97ffff0a,0x219c1ac:0x97ffff04,0x219e694:0x97ffff02,0x2199510:0x97e8eff2,0x219b9e0:0x97e8e6be,0x219e07c:0x97e8dd17,0x21a0520:0x97e8d3ee,0x2197b5c:0xa9b87bfd,0x219a2ec:0xa9b87bfd,0x219c814:0xa9b87bfd,0x219ed00:0xa9b87bfd,0x2198040:0xa9b77bfd,0x219a808:0xa9b77bfd,0x219ccc0:0xa9b77bfd,0x219f21c:0xa9b77bfd,0x219712c:0xaa0003e1,0x21998ec:0xaa0003e1,0x219bdbc:0xaa0003e1,0x219e29c:0xaa0003e1,0x28cb488:0x9002b1a0,0x28cb49c:0x9002b1a0,0x28cb4b0:0x9002b1a0,0x28cb4c4:0x9002b1a0,0x28cb4d8:0x9002b1a0,0x28cb4ec:0x9002b1a0,0x28cb500:0x9002b1a0,0x28cb514:0x9002b1a0,0x28cb528:0x9002b1a0,0x28cb53c:0x9002b1a0,0x28cb550:0x9002b1a0,0x28cb564:0x9002b1a0,0x28cb578:0x9002b1a0,0x28cb58c:0x9002b1a0,0x28cb5a0:0x9002b1a0,0x28cb5b4:0x9002b1a0,0x23d5818:0xa9be7bfd,0x23d583c:0xa9be7bfd,0x3693c0c:0xa9ba7bfd,0x3694f64:0xa9bc7bfd,0x252d80c:0xa9bc7bfd,0x219a5d8:0xa9bd7bfd,0x23d58d0:0x39405001,0x23d5b8c:0x39405001,0x17feac0:0xa9ba7bfd,0x28a87e8:0xf002b2a0,0x17ffd84:0xf0020c60,
         0x28bfdcc:0x9002b200,0x1af11f0:0xa9bf7bfd,0x220929c:0xa9bf7bfd,
         0x28c54cc:0xd002b1c0,0x1c91e94:0xa9bc7bfd,0x2dc6160:0x7100481f,
         0x220b4e0:0xa9bf7bfd,0x1af3cdc:0xa9be7bfd,0x1bd54d8:0xa9be7bfd,
         0x220b838:0x52923ec0,0x1bd5508:0xa9be7bfd,
         0x2e7d208:0xa9b97bfd,0x28c5684:0xd002b1c0,0x28c5698:0xd002b1c0,
         0x220a6a4:0xa9bd7bfd,0x220a670:0x39405001,0x220920c:0xa9be7bfd,
         0x1c91c40:0xa9bc7bfd,0x1c935e0:0xa9bc7bfd,0x1bd906c:0x91002002,
         0x1bd924c:0xa9bc7bfd,0x1bd9348:0xa9bc7bfd,
         0x1c938a8:0xa9bc7bfd,0x1c933ec:0xa9bc7bfd,0x28b0464:0xf002b260,0x1bd5720:0xa9be7bfd,0x1cdbb08:0xf9400003,0x28a8720:0xf002b2a0,0x28a8734:0xf002b2a0,
         0x21d68d8:0x39405001,0x21d62a8:0xa9be7bfd,0x21d62cc:0xa9be7bfd,0x21f3ed8:0xa9bd7bfd,0x21edb2c:0xaa0003e1,0x1c05f18:0xa9bd7bfd,0x28ae4b0:0xb002b280,
         **{at:0xd002b1c0 for at in (0x28c5544,0x28c556c,0x28c5594,0x28c55bc,
                                    0x28c55e4,0x28c560c,0x28c5634,0x28c565c)}}


@pytest.fixture(scope='module')
def modules(tmp_path_factory):
    directory = tmp_path_factory.mktemp('ap-ui-dynamic')
    compiler = shutil.which('clang')
    linker = shutil.which('ld.lld') or '/opt/homebrew/opt/lld/bin/ld.lld'
    objects = []
    for name in ('af_slots.c','af_ui.c','af_ap_ui.c','af_ap_ui.S','af_labels.c','af_ap_names.c','af_ap_manage.c','af_ap_targets.c','af_ap_browser.c','af_ap_cards.c','af_ap_media.c'):
        output = directory/(name+'.o')
        result = subprocess.run([compiler,'--target=aarch64-none-elf','-DAF_AP_DYNAMIC',
            '-std=c11','-O2','-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector',
            '-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-c',str(NATIVE/name),'-o',str(output)],
            capture_output=True,text=True)
        assert result.returncode == 0, result.stderr
        objects.append(str(output))
    output = directory/'ui-dynamic.elf'
    result = subprocess.run([linker,'-shared','-Bsymbolic','--no-undefined','-z','max-page-size=4096',
        '-T',str(NATIVE/'af_ap_ui_dynamic.ld'),*objects,'-o',str(output)],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    return output.read_bytes()


class Machine:
    def __init__(self, raw, base=0x7000000000, module=0x7100000000):
        self.base, self.module = base, module
        self.u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.pages = set()
        self.stop, self.work, self.stack = 0x7200000000,0x7200001000,0x7200010000
        self.map(self.stop,0x1000);self.map(self.work,0x2000);self.map(self.stack,0x10000)
        elf = ELFFile(io.BytesIO(raw))
        assert elf['e_type'] == 'ET_DYN'
        for segment in elf.iter_segments():
            if segment['p_type'] != 'PT_LOAD': continue
            assert segment['p_flags'] in (5,6)
            self.map(module+segment['p_vaddr'],segment['p_memsz'])
            self.u.mem_write(module+segment['p_vaddr'],segment.data())
        self.symbols = {s.name:module+s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()
                        if s.name and s['st_shndx'] != 'SHN_UNDEF'}
        for section in elf.iter_sections():
            if section['sh_type'] != 'SHT_RELA': continue
            for rel in section.iter_relocations():
                assert rel['r_info_type'] == 1027
                self.u.mem_write(module+rel['r_offset'],struct.pack('<Q',module+rel['r_addend']))
        for segment in elf.iter_segments():
            if segment['p_type'] != 'PT_LOAD': continue
            start = (module+segment['p_vaddr'])&~4095
            end = (module+segment['p_vaddr']+segment['p_memsz']+4095)&~4095
            # ELF PF_R/PF_W/PF_X 与Unicorn位序不同，明确转换并验证RX/RW执行。
            permission = 1 | (2 if segment['p_flags']&2 else 4)
            self.u.mem_protect(start,end-start,permission)
        self.fingerprints = dict(EXTRA)
        self.fingerprints.update({h[0]:word for h,word in zip(STOCK,WORDS)})
        self.fingerprints.update({at:struct.unpack('<I',branch(at,target,True))[0]
                                  for at,target in CALL_TARGETS.items()})
        for offset,word in self.fingerprints.items():
            self.map(base+offset,4);self.u.mem_write(base+offset,struct.pack('<I',word))
        self.map(base+0x5858b08,0x100)
        self.u.mem_write(base+0x5858b08+0x54,struct.pack('<IQ',19,base+0x3f4a280))
        self.u.mem_write(base+0x5858b08+0x78,struct.pack('<Q',base+0x1c05f18))
        self.original_descriptor = bytes(self.u.mem_read(base+0x5858b08,0xa0))
        # 新私有current缓存只观察原690；默认零值是明确服务边界，各定向case可覆写。
        self.services = {base+0x28ae4b0:lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,self.work+0x1f00)};self.calls = []
        def boundary(cpu,pc,size,data):
            if pc in self.services:
                self.calls.append(pc)
                self.services[pc](cpu)
                cpu.reg_write(regs.UC_ARM64_REG_PC,cpu.reg_read(regs.UC_ARM64_REG_LR))
        self.u.hook_add(UC_HOOK_CODE,boundary)

    def map(self, address, size):
        for page in range(address&~4095,(address+size+4095)&~4095,4096):
            if page not in self.pages:self.u.mem_map(page,4096);self.pages.add(page)

    def call(self, name, *args):
        u = self.u
        for i,v in enumerate(args): u.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),v)
        u.reg_write(regs.UC_ARM64_REG_SP,self.stack+0x8000)
        u.reg_write(regs.UC_ARM64_REG_LR,self.stop)
        u.emu_start(self.symbols[name],self.stop,count=200000)
        assert u.reg_read(regs.UC_ARM64_REG_PC) == self.stop
        assert u.reg_read(regs.UC_ARM64_REG_SP) == self.stack+0x8000
        value = u.reg_read(regs.UC_ARM64_REG_X0)
        return value-(1<<32) if value&0xffffffff00000000 == 0 and value&(1<<31) else value

    def bind(self, **changes):
        values = dict(version=1,bytes=64,base=self.base,mapped_bytes=SPAN,
                      application_init=self.base+0x17feac0,sha=bytes.fromhex(SHA))
        values.update(changes)
        raw = struct.pack('<IIQQQ32s',*(values[n] for n in
                         ('version','bytes','base','mapped_bytes','application_init','sha')))
        self.u.mem_write(self.work,raw)
        return self.call('af_ap_bind',self.work)

    def registered(self):
        assert self.bind() == 0
        base,u = self.base,self.u
        self.map(base+0x5915b80,8);u.mem_write(base+0x5915b80,struct.pack('<Q',self.work+0x100))
        self.map(base+0x3f4a280,19*128)
        rows = bytes((i*17+3)%256 for i in range(19*128))
        u.mem_write(base+0x3f4a280,rows)
        self.registrations = []
        def register(cpu):
            self.registrations.append(tuple(cpu.reg_read(getattr(regs,'UC_ARM64_REG_X'+str(i))) for i in range(3)))
            # 原范围登记服务完成后发布实际行数，供post-original准入校验读取。
            if len(self.registrations) == 1:
                assert self.registrations[0][1:] == (base+0x5030590,base+0x5046300)
                u.mem_write(self.work+0x128,struct.pack('<Q',5591))
        self.services[base+0x1c91e94] = register
        self.call('af_ap_register',self.work+0x100,base+0x5030590,base+0x5046300)
        assert len(self.registrations) == 2
        assert bytes(u.mem_read(self.symbols['af_ap_rows'],18*128)) == rows[:18*128]
        assert bytes(u.mem_read(self.symbols['af_ap_rows']+32*128,128)) == rows[18*128:]
        return rows


def test_binding_rejects_bad_config_before_any_pointer_access_and_can_unbind(modules):
    m = Machine(modules)
    for changes in ({'version':2},{'bytes':63},{'base':1},{'base':0},
                    {'base':(1<<64)-4096},{'mapped_bytes':SPAN-4096},
                    {'application_init':0},{'sha':bytes(32)}):
        assert m.bind(**changes) == -1
        assert m.call('af_ap_bound_base') == 0
        assert bytes(m.u.mem_read(m.symbols['af_ap_stock_targets'],44*8)) == bytes(44*8)
    assert m.bind() == 0
    assert m.call('af_ap_bound_base') == m.base
    assert m.bind() == -4
    assert m.call('af_ap_unbind') == 0
    assert m.call('af_ap_bound_base') == 0
    assert bytes(m.u.mem_read(m.symbols['af_ap_stock_targets'],44*8)) == bytes(44*8)


def test_each_instruction_and_descriptor_preimage_is_checked_without_partial_binding(modules):
    m = Machine(modules)
    for offset,word in m.fingerprints.items():
        m.u.mem_write(m.base+offset,struct.pack('<I',word^1))
        assert m.bind() == -5,hex(offset)
        assert m.call('af_ap_bound_base') == 0
        assert bytes(m.u.mem_read(m.symbols['af_ap_stock_targets'],44*8)) == bytes(44*8)
        m.u.mem_write(m.base+offset,struct.pack('<I',word))
    for offset,raw in ((0x54,struct.pack('<I',18)),(0x58,struct.pack('<Q',0x3f4a280)),(0x78,struct.pack('<Q',0x1c05f18))):
        m.u.mem_write(m.base+0x5858b08+offset,raw)
        assert m.bind() == -5
        m.u.mem_write(m.base+0x5858b08,m.original_descriptor)
    assert m.bind() == 0


@pytest.mark.parametrize('base,module',[(0x7000000000,0x7100000000),(0x44000000,0x28000000)])
def test_all_original_trampolines_replay_first_instruction_and_jump_beyond_bl_range(modules,base,module):
    m = Machine(modules,base,module)
    assert abs(base-module) > (1<<27) and m.bind() == 0
    u = m.u
    for h,word in zip(STOCK,WORDS):
        before = {}
        for i in range(31):
            value = m.work+0x300 if i == 3 else 0x1234567800000000+i
            if i == 30:value = m.stop
            u.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value);before[i] = value
        for i in range(32):u.reg_write(getattr(regs,'UC_ARM64_REG_Q'+str(i)),0xabcdef00+i)
        u.reg_write(regs.UC_ARM64_REG_NZCV,0xa0000000)
        u.reg_write(regs.UC_ARM64_REG_SP,m.stack+0x8000)
        u.mem_write(m.work+0x320,struct.pack('<I',0x87654321))
        u.emu_start(m.symbols[h[3]],base+h[0]+4,count=100)
        assert u.reg_read(regs.UC_ARM64_REG_PC) == base+h[0]+4
        expected = dict(before);expected[16] = base+h[0]+4
        sp = m.stack+0x8000
        if word == 0x5282bb03:expected[3] = 0x15d8
        elif word == 0x528566c2:expected[2] = 0x2b36
        elif word == 0xb9402060:expected[0] = 0x87654321
        else:
            immediate = (word>>15)&127
            if immediate&64:immediate -= 128
            sp += immediate*8
            assert bytes(u.mem_read(sp,16)) == struct.pack('<QQ',before[29],before[30])
        assert u.reg_read(regs.UC_ARM64_REG_SP) == sp
        for i,value in expected.items():assert u.reg_read(getattr(regs,'UC_ARM64_REG_X'+str(i))) == value
        assert u.reg_read(regs.UC_ARM64_REG_NZCV) == 0xa0000000
        for i in range(32):assert u.reg_read(getattr(regs,'UC_ARM64_REG_Q'+str(i))) == 0xabcdef00+i


def test_unbound_dynamic_trampoline_stops_instead_of_using_address_zero(modules):
    m = Machine(modules)
    with pytest.raises(UcError):m.call('af_stock_register',0,0,0)
    assert m.u.reg_read(regs.UC_ARM64_REG_PC) != 0


def test_new_slot_icons_use_dedicated_resources_before_native_finite_tables(modules):
    m = Machine(modules);m.registered();u=m.u
    for name in ('icon','icon_alternate'):
        stock=m.symbols['af_stock_'+name]
        def original(cpu):
            assert cpu.reg_read(regs.UC_ARM64_REG_X0)==m.work
            assert cpu.reg_read(regs.UC_ARM64_REG_X1) in (0x84c,0x85d,0x85e,0x15d8)
            cpu.reg_write(regs.UC_ARM64_REG_X0,0x2000713)
        m.services[stock]=original
        for enabled in (0,1):
            assert m.call('af_ap_research_enable',enabled)==0
            for menu in range(0x15d9,0x15e7):
                before=len(m.calls)
                # 新身份不能解引用原对象或进入旧图标索引，禁用时不得访问新增资源。
                expected=0x02001ea4+menu-0x15d9 if enabled else -1
                assert m.call('af_ap_'+name,0,menu)==expected
                assert len(m.calls)==before
            for menu in (0x84c,0x85d,0x85e,0x15d8):
                assert m.call('af_ap_'+name,m.work,menu)==0x2000713
                assert m.calls[-1]==stock


def test_new_slot_parent_uses_creative_look_descriptor_without_other_page_aliases(modules):
    m=Machine(modules);m.registered();u=m.u
    stock=m.symbols['af_stock_parent']
    def original(cpu):cpu.reg_write(regs.UC_ARM64_REG_X0,0xca4)
    m.services[stock]=original
    for enabled in (0,1):
        assert m.call('af_ap_research_enable',enabled)==0
        for menu in range(0x15d9,0x15e7):
            before=len(m.calls)
            assert m.call('af_ap_parent',0,menu)==(0x1e6 if enabled else 0xca4)
            assert len(m.calls)==before+(not enabled)
        for menu in (0x84c,0x85d,0x85e,0x15d8,0x1605):
            assert m.call('af_ap_parent',m.work,menu)==0xca4
            assert m.calls[-1]==stock
        for menu in range(0x15e7,0x15ec):
            assert m.call('af_ap_parent',m.work,menu)==(0xca4 if not enabled else 0x7f if menu==0x15e7 else 0x15e7)


def test_parameter_presenter_reads_private_working_defaults_and_rejects_stale_or_empty_slots(modules):
    m=Machine(modules);m.registered();u=m.u;base=m.base
    assert m.call('af_ap_research_enable',1)==0
    model=m.work+0x400;mode=m.work+0x408;object=m.work+0x4000
    m.map(object,0x5000);u.mem_write(model,struct.pack('<I',0x15d9));u.mem_write(mode,bytes(4))
    u.mem_write(object+0x3b18,struct.pack('<I',0x15d9))
    def value(v):return lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,v)
    m.services[base+0x28a87e8]=value(model);m.services[base+0x17ffd84]=value(0)
    m.services[base+0x28bfdcc]=value(mode)
    focus={'option':1}
    m.services[base+0x220b4e0]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,focus['option'])
    params=(-3,4,-5,6,7,8,3,9)
    u.mem_write(m.work+0x500,struct.pack('<BB8b64s',0,0,*params,bytes(64)))
    catalog=m.symbols['af_ap_catalog']
    assert m.call('af_install',catalog,7,m.work+0x500,0)==0
    assert m.call('af_edit',catalog,7,0,-2)==0
    for option in range(1,9):
        focus['option']=option
        assert m.call('af_ap_parameter_value',object)==(-2 if option==1 else params[option-1])
        assert m.call('af_ap_parameter_default',object)==params[option-1]
        assert m.call('af_ap_parameter_disabled',object)==0
    focus['option']=0
    assert m.call('af_ap_parameter_value',object)==0
    assert m.call('af_ap_parameter_disabled',object)==0
    for kind in ('stale','empty','restricted'):
        u.mem_write(object+0x3b18,struct.pack('<I',0x15da if kind=='stale' else 0x15d9))
        u.mem_write(model,struct.pack('<I',0x15da if kind=='empty' else 0x15d9))
        u.mem_write(mode,struct.pack('<I',1 if kind=='restricted' else 0))
        for name,expected in (('value',0),('default',0),('disabled',1)):
            assert m.call('af_ap_parameter_'+name,object)==expected
    u.mem_write(mode,bytes(4))
    for name in ('value','default','disabled'):
        stock=m.symbols['af_stock_parameter_'+name];m.services[stock]=value(55)
        for menu in (0x84c,0x858,0x85d,0x85e):
            u.mem_write(model,struct.pack('<I',menu))
            assert m.call('af_ap_parameter_'+name,object)==55
            assert m.calls[-1]==stock
    assert base+0x2dc6160 not in m.calls


def test_shifted_registry_descriptor_restore_and_unconnected_base_edit_stay_isolated(modules):
    m = Machine(modules);rows = m.registered();u = m.u;base = m.base
    assert m.call('af_ap_research_enable',1) == 0
    assert struct.unpack('<IQ',u.mem_read(base+0x5858b08+0x54,12)) == (33,m.symbols['af_ap_rows'])
    # 原入口用显式服务边界返回模型地址，只证明动态路由与禁用行为。
    u.mem_write(m.work+0x400,struct.pack('<I',0x15d9))
    u.mem_write(m.work+0x408,struct.pack('<I',0))
    def value(pointer):
        return lambda cpu: cpu.reg_write(regs.UC_ARM64_REG_X0,pointer)
    m.services[base+0x28a87e8] = value(m.work+0x400)
    m.services[base+0x17ffd84] = value(0)
    m.services[base+0x28bfdcc] = value(m.work+0x408)
    before = bytes(u.mem_read(m.symbols['af_ap_catalog'],m.call('af_catalog_bytes')))
    m.call('af_ap_base_cycle',m.work+0x500,0)
    assert base+0x220ac78 not in m.calls
    assert bytes(u.mem_read(m.symbols['af_ap_catalog'],len(before))) == before
    assert m.call('af_ap_unbind') == -4
    # 他人改变描述符时不覆盖；恢复该夹具后再精确禁用。
    u.mem_write(base+0x5858b08+0x54,struct.pack('<I',31))
    assert m.call('af_ap_research_enable',0) == -5
    assert struct.unpack('<I',u.mem_read(base+0x5858b08+0x54,4))[0] == 31
    u.mem_write(base+0x5858b08+0x54,struct.pack('<I',33))
    assert m.call('af_ap_research_enable',0) == 0
    assert bytes(u.mem_read(base+0x5858b08,0xa0)) == m.original_descriptor
    assert bytes(u.mem_read(base+0x3f4a280,len(rows))) == rows


def test_base_cycle_keeps_private_parameters_and_uses_native_order_without_imaging_writes(modules):
    m=Machine(modules);m.registered();u=m.u;base=m.base;catalog=m.symbols['af_ap_catalog']
    assert m.call('af_ap_research_enable',1)==0
    model=m.work+0x400;mode=m.work+0x408;object=m.work+0x4000
    m.map(object,0x5000);u.mem_write(model,struct.pack('<I',0x15d9));u.mem_write(mode,bytes(4))
    def value(v):return lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,v)
    for offset,v in ((0x28a87e8,model),(0x17ffd84,0),(0x28bfdcc,mode),(0x1af11f0,0xf),(0x220929c,0)):
        m.services[base+offset]=value(v)
    m.services[m.symbols['af_stock_parameter_init']]=value(0)
    focus_restores=[]
    m.services[base+0x1af3cdc]=lambda cpu:focus_restores.append((cpu.reg_read(regs.UC_ARM64_REG_X0),cpu.reg_read(regs.UC_ARM64_REG_X1)))
    m.services[m.symbols['af_stock_base_label']]=lambda cpu:None
    m.services[base+0x1bd5508]=lambda cpu:None
    m.services[m.symbols['af_stock_base_icon']]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,cpu.reg_read(regs.UC_ARM64_REG_X1))
    params=(-3,4,-5,2,6,7,3,8)
    u.mem_write(m.work+0x500,struct.pack('<BB8b64s',0,0,*params,bytes(64)))
    assert m.call('af_install',catalog,7,m.work+0x500,0)==0
    snapshot=m.work+0x600;output=m.work+0x800
    u.mem_write(snapshot,bytes(0x100));u.mem_write(snapshot+0x20,struct.pack('<I',19))
    m.call('af_ap_display',0,output,0,snapshot)
    manager=object+0x1000;view=object+0x2000
    u.mem_write(view,struct.pack('<Q',base+0x58ca720))
    u.mem_write(manager+0x338,struct.pack('<Q',view))
    m.services[m.symbols['af_stock_refresh']]=value(0)
    assert m.call('af_ap_label_refresh',0)==-1 and m.call('af_ap_label_refresh',21)==-1
    assert m.call('af_ap_label_refresh',8)==0 and m.call('af_ap_refresh',manager)==0
    assert m.call('af_ap_label_refresh',7)==0 and m.call('af_ap_refresh',manager)==1
    m.call('af_ap_display',0,output,0,snapshot)
    initial=bytes(u.mem_read(catalog,m.call('af_catalog_bytes')))
    assert m.call('af_ap_base_available')==1 and m.call('af_ap_inhibited',object)==0
    for direction,expected in [(0,9),(1,0)]+[(1,v) for v in (1,2,3,4,5,17,18,6,7,8,9,0)]:
        m.call('af_ap_base_cycle',object,direction)
        assert m.call('af_read',catalog,7,0,m.work+0x900)==0
        raw=bytes(u.mem_read(m.work+0x900,74))
        assert raw[0]==expected and raw[1:]==struct.pack('<B8b64s',0,*params,bytes(64))
        assert focus_restores[-1]==(object+0x1a0,0xf)
        expected_menu=0x84c+expected if expected<=5 else 0x84e+expected if expected<=9 else 0x852 if expected==17 else 0x853
        assert m.call('af_ap_base_label',0x1e6)==0x1e6
        assert m.call('af_ap_base_icon',object,0x0200abde)==expected_menu
        assert m.call('af_read',catalog,7,1,m.work+0xa00)==0
        assert bytes(u.mem_read(m.work+0xa00,74))==struct.pack('<BB8b64s',0,0,*params,bytes(64))
    assert bytes(u.mem_read(catalog,len(initial)))==initial
    for guard in ('direction','focus','option','stale','restricted'):
        m.services[base+0x1af11f0]=value(0x10 if guard=='focus' else 0xf)
        m.services[base+0x220929c]=value(1 if guard=='option' else 0)
        u.mem_write(model,struct.pack('<I',0x15da if guard=='stale' else 0x15d9))
        u.mem_write(mode,struct.pack('<I',1 if guard=='restricted' else 0))
        m.call('af_ap_base_cycle',object,2 if guard=='direction' else 1)
        assert bytes(u.mem_read(catalog,len(initial)))==initial
    u.mem_write(mode,bytes(4));u.mem_write(model,struct.pack('<I',0x15d9))
    m.services[base+0x220929c]=value(0)
    u.mem_write(m.work+0x500,struct.pack('<BB8b32s32s',0,1,*params,b'\xab'*32,b'\xcd'*32))
    assert m.call('af_install',catalog,7,m.work+0x500,1)==0
    lut=bytes(u.mem_read(catalog,len(initial)))
    assert m.call('af_ap_base_available')==0 and m.call('af_ap_inhibited',object)==1
    m.call('af_ap_base_cycle',object,1)
    assert bytes(u.mem_read(catalog,len(initial)))==lut
    for menu in (0x84c,0x852,0x853,0x858,0x85d):
        u.mem_write(model,struct.pack('<I',menu))
        m.services[m.symbols['af_stock_base_cycle']]=value(77)
        m.services[m.symbols['af_stock_base_available']]=value(55)
        m.call('af_ap_base_cycle',object,1)
        assert m.calls[-1]==m.symbols['af_stock_base_cycle']
        assert m.call('af_ap_base_available')==55
        assert m.call('af_ap_base_label',menu)==menu
        assert m.call('af_ap_base_icon',object,0x1234)==0x1234
        m.services[m.symbols['af_stock_preview_menu']]=value(66)
        m.call('af_ap_preview_menu',menu)
        assert m.calls[-1]==m.symbols['af_stock_preview_menu']
    assert not {base+0x2dc6160,base+0x263d3ec,base+0x263bdb0}&set(m.calls)


def test_new_slot_base_widgets_use_original_checked_records_and_publish_all_or_none(modules):
    m=Machine(modules);m.registered();u=m.u;base=m.base
    assert m.call('af_ap_research_enable',1)==0
    model=m.work+0x400;mode=m.work+0x408;object=m.work+0x4000;records=m.work+0xa000
    m.map(object,0x10000)
    def value(v):return lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,v)
    for offset,v in ((0x28a87e8,model),(0x17ffd84,0),(0x28bfdcc,mode)):
        m.services[base+offset]=value(v)
    m.services[m.symbols['af_stock_parameter_layout']]=value(0)
    u.mem_write(model,struct.pack('<I',0x15d9));u.mem_write(mode,bytes(4))
    u.mem_write(object,struct.pack('<Q',base+0x58ca720))
    u.mem_write(object+0x3b18,struct.pack('<I',0x15d9));u.mem_write(object+0x90,struct.pack('<Q',records))
    targets=[]
    for i,(offset,kind) in enumerate(zip((0x80,0x90,0xf0,0x280),(0,0,0x11,0))):
        data=records+0x1000+i*0x100;targets.append(data)
        u.mem_write(records+offset,struct.pack('<IIQ',kind,0,data));u.mem_write(data+0x2c,b'\x09')
    m.call('af_ap_parameter_layout',object)
    assert [bytes(u.mem_read(p+0x2c,1))[0] for p in targets]==[1,0,1,1]
    for p in targets:u.mem_write(p+0x2c,b'\x09')
    u.mem_write(records+0xf0,struct.pack('<I',0))
    m.call('af_ap_parameter_layout',object)
    assert [bytes(u.mem_read(p+0x2c,1))[0] for p in targets]==[9]*4
    u.mem_write(records+0xf0,struct.pack('<I',0x11));u.mem_write(model,struct.pack('<I',0x84c))
    m.call('af_ap_parameter_layout',object)
    assert [bytes(u.mem_read(p+0x2c,1))[0] for p in targets]==[9]*4


def test_reset_restores_only_current_private_initial_state_and_native_ui_transaction(modules):
    m=Machine(modules);m.registered();u=m.u;base=m.base;catalog=m.symbols['af_ap_catalog']
    assert m.call('af_ap_research_enable',1)==0
    model,mode=m.work+0x400,m.work+0x408
    def value(v):return lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,v)
    for at,v in ((0x28a87e8,model),(0x17ffd84,0),(0x28bfdcc,mode)):
        m.services[base+at]=value(v)
    u.mem_write(model,struct.pack('<I',0x15d9));u.mem_write(mode,bytes(4))
    preset,output,snapshot=m.work+0x500,m.work+0x600,m.work+0x800
    initial=struct.pack('<BB8b64s',0,0,0,0,0,0,0,0,3,0,bytes(64))
    u.mem_write(preset,initial)
    assert m.call('af_install',catalog,7,preset,0)==0
    assert m.call('af_install',catalog,8,preset,0)==0
    assert m.call('af_edit_base',catalog,7,18)==0
    assert m.call('af_edit',catalog,7,0,4)==0
    u.mem_write(snapshot,bytes(0x100));u.mem_write(snapshot+0x20,struct.pack('<I',19))
    m.call('af_ap_display',0,output,0,snapshot)
    events=[];prop,meta=m.work+0x1100,m.work+0x1140
    m.services[base+0x28c5684]=value(prop);m.services[base+0x28c5698]=value(meta)
    def begin(cpu):
        p=cpu.reg_read(regs.UC_ARM64_REG_X0)
        assert bytes(cpu.mem_read(p,16))==bytes(16);events.append('begin')
    def set_value(cpu):
        p,q=[cpu.reg_read(r) for r in (regs.UC_ARM64_REG_X0,regs.UC_ARM64_REG_X1)]
        assert struct.unpack('<QQIBBHQ',cpu.mem_read(p,32))==(prop,meta,0x1700,0,0,0,0)
        assert struct.unpack('<I',cpu.mem_read(q,4))[0]==0x84c
        cpu.mem_write(prop,bytes(cpu.mem_read(q,4)));events.append('set')
    m.services[base+0x2e7d208]=begin;m.services[base+0x220a6a4]=set_value
    m.services[base+0x220a670]=lambda cpu:events.append('notify')
    m.services[base+0x220920c]=lambda cpu:events.append('finish')
    m.call('af_ap_reset',m.work+0x80)
    assert events==['begin','set','notify','finish']
    assert m.call('af_read',catalog,7,0,preset)==0 and bytes(u.mem_read(preset,74))==initial
    assert m.call('af_read',catalog,7,1,preset)==0 and bytes(u.mem_read(preset,74))==initial
    assert m.call('af_read',catalog,8,0,preset)==0 and bytes(u.mem_read(preset,74))==initial
    assert not {base+0x263d480,base+0x28ae4b0,base+0x2dc6160}&set(m.calls)
    # 扩展启用时，陈旧快照、空槽、未知身份及限制布局不落入原690重置入口。
    assert m.call('af_edit',catalog,7,0,4)==0
    before=bytes(u.mem_read(catalog,m.call('af_catalog_bytes')))
    for menu,restriction in ((0x15da,0),(0x15e6,0),(0xdeadbeef,0),(0x15d9,1)):
        u.mem_write(model,struct.pack('<I',menu));u.mem_write(mode,struct.pack('<I',restriction))
        m.call('af_ap_reset',m.work+0x80)
        assert bytes(u.mem_read(catalog,len(before)))==before and len(events)==4
    u.mem_write(mode,bytes(4));u.mem_write(model,struct.pack('<I',0x15d9))
    # 扩展禁用后按原约定委派原厂；服务边界必须有显式接收者。
    stock=[]
    m.services[m.symbols['af_stock_reset']]=lambda cpu:stock.append(cpu.reg_read(regs.UC_ARM64_REG_X0))
    assert m.call('af_ap_research_enable',0)==0;m.call('af_ap_reset',m.work+0x80)
    assert bytes(u.mem_read(catalog,len(before)))==before and len(events)==4 and stock==[m.work+0x80]
    calls=[]
    m.services[m.symbols['af_stock_reset']]=lambda cpu:calls.append(cpu.reg_read(regs.UC_ARM64_REG_X0))
    for menu in range(0x84c,0x85e):
        u.mem_write(model,struct.pack('<I',menu));m.call('af_ap_reset',m.work+0x80)
    assert calls==[m.work+0x80]*18
