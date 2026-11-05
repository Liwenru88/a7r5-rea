"""两个名称调用点的AArch64路由契约；原字符串复制另由锁定libObj验证。"""
import io
from pathlib import Path
import shutil
import struct
import subprocess

from elftools.elf.elffile import ELFFile
import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as r

NATIVE = Path(__file__).resolve().parents[1]/'native'
TOKEN = 0x7fca0001
MENUS = list(range(0x858,0x85e))+list(range(0x15d9,0x15e7))


@pytest.fixture(scope='module')
def names_module(tmp_path_factory):
    directory=tmp_path_factory.mktemp('ap-names')
    objects=[]
    for name in ('af_labels.c','af_ap_names.c','af_ap_manage.c','af_slots.c','af_ap_targets.c','af_ap_browser.c', 'af_ap_cards.c'):
        target=directory/(name+'.o')
        result=subprocess.run([shutil.which('clang'),'--target=aarch64-none-elf',
            '-std=c11','-O2','-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector',
            '-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-c',str(NATIVE/name),'-o',str(target)],
            capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        objects.append(str(target))
    script=directory/'names.ld'
    script.write_text((NATIVE/'af_ap_ui_dynamic.ld').read_text().replace(
        'ENTRY(af_ap_register)','ENTRY(af_ap_names_title)'))
    target=directory/'names.elf'
    result=subprocess.run([shutil.which('ld.lld') or '/opt/homebrew/opt/lld/bin/ld.lld',
        '-shared','-Bsymbolic','--no-undefined','-z','max-page-size=4096','-T',str(script),
        *objects,'-o',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return target.read_bytes()


class NamesMachine:
    """原AP/getter及libObj接口在此明确替换为可观察的测试服务。"""
    def __init__(self, raw):
        self.ap,self.obj,self.base=0x7000000000,0x7300000000,0x7100000000
        self.work,self.stack,self.stop=0x7400000000,0x7400010000,0x7400020000
        self.labels,self.text,self.binding=self.work+0x1000,self.work+0x4000,self.work+0x100
        self.u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);self.pages=set()
        self.map(self.work,0x10000);self.map(self.stack,0x10000);self.map(self.stop,4096)
        elf=ELFFile(io.BytesIO(raw))
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD':
                self.map(self.base+segment['p_vaddr'],segment['p_memsz'])
                self.u.mem_write(self.base+segment['p_vaddr'],segment.data())
        self.symbols={s.name:self.base+s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()
                      if s.name and s['st_shndx']!='SHN_UNDEF'}
        for section in elf.iter_sections():
            if section['sh_type']=='SHT_RELA':
                for rel in section.iter_relocations():
                    assert rel['r_info_type']==1027
                    self.u.mem_write(self.base+rel['r_offset'],struct.pack('<Q',self.base+rel['r_addend']))
        self.preimages={self.ap+0x2208e8c:0x97e7319f,self.ap+0x220c8a0:0x97e7231a,self.ap+0x1885b38:0x97f9566e,
                        self.ap+0x28b0464:0xf002b260,
                        self.obj+0x16d2a4:0xa9bd7bfd,self.obj+0x16d498:0xa9bd7bfd,
                        self.obj+0x16bc64:0xf84d0c01}
        for address,word in self.preimages.items():
            self.map(address,4);self.u.mem_write(address,struct.pack('<I',word))
        self.native_calls=[];self.resource_calls=[];self.text_calls=[];self.fail_allocation=False
        self.sprite=self.work+0x7000;self.record=False
        self.language=self.work+0x6800
        self.map(self.ap+0x1bd5508,4)
        def service(cpu,pc,size,data):
            a=cpu.reg_read(r.UC_ARM64_REG_X0);b=cpu.reg_read(r.UC_ARM64_REG_X1)
            if pc==self.ap+0x1bd5508:
                self.native_calls.append(a);value=self.original(a)
            elif pc==self.ap+0x28b0464:value=self.language
            elif pc==self.obj+0x16d498:
                self.resource_calls.append((a,b));value=0
            elif pc==self.obj+0x16d2a4:
                assert a==self.sprite
                name=bytearray()
                for offset in range(64):
                    ch=bytes(cpu.mem_read(b+offset,1))
                    if ch==b'\0':break
                    name.extend(ch)
                else:raise AssertionError('名称未在63字节后终止')
                self.text_calls.append(bytes(name));self.record=not self.fail_allocation
                value=0xffffffffffffffff  # 原void重载的返回寄存器不可当状态。
            elif pc==self.obj+0x16bc64:value=self.sprite+0xd0 if self.record else 0
            else:return
            cpu.reg_write(r.UC_ARM64_REG_X0,value)
            cpu.reg_write(r.UC_ARM64_REG_PC,cpu.reg_read(r.UC_ARM64_REG_LR))
        self.u.hook_add(UC_HOOK_CODE,service)
        self.call('af_labels_init',self.labels)

    def map(self,address,size):
        for page in range(address&~4095,(address+size+4095)&~4095,4096):
            if page not in self.pages:self.u.mem_map(page,4096);self.pages.add(page)

    @staticmethod
    def original(menu):
        return 0x200abd8+MENUS.index(menu) if menu in MENUS else 0x21000000|(menu&0xffffff)

    def call(self,name,*args):
        u=self.u
        for i,value in enumerate(args):u.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),value)
        saved={i:0x1234567800000000+i for i in range(19,30)}
        for i,value in saved.items():u.reg_write(getattr(r,'UC_ARM64_REG_X'+str(i)),value)
        for i in range(8,16):u.reg_write(getattr(r,'UC_ARM64_REG_Q'+str(i)),0x5566778800000000+i)
        u.reg_write(r.UC_ARM64_REG_SP,self.stack+0x8000);u.reg_write(r.UC_ARM64_REG_LR,self.stop)
        u.emu_start(self.symbols[name],self.stop,count=200000)
        assert u.reg_read(r.UC_ARM64_REG_PC)==self.stop and u.reg_read(r.UC_ARM64_REG_SP)==self.stack+0x8000
        assert all(u.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i)))==v for i,v in saved.items())
        assert all(u.reg_read(getattr(r,'UC_ARM64_REG_Q'+str(i)))&((1<<64)-1)==0x5566778800000000+i for i in range(8,16))
        value=u.reg_read(r.UC_ARM64_REG_X0)
        return value-(1<<32) if value<1<<32 and value&(1<<31) else value

    def bind(self,version=1,labels=None,obj=None):
        self.u.mem_write(self.binding,struct.pack('<IIQQQ',version,32,self.ap,self.obj if obj is None else obj,
                                                self.labels if labels is None else labels))
        return self.call('af_ap_names_bind',self.binding)

    def publish(self,slot,name,generation=1):
        raw=name.encode() if isinstance(name,str) else name
        if raw:self.u.mem_write(self.text,raw)
        return self.call('af_labels_publish',self.labels,slot,generation,self.text if raw else 0,len(raw))


def ready(raw):
    machine=NamesMachine(raw);assert machine.bind()==0
    assert machine.call('af_ap_names_enable',1)==0
    return machine


def test_only_title_tokens_route_twenty_user_names_and_native_resources_delegate(names_module):
    m=ready(names_module)
    for slot,menu in enumerate(MENUS,1):
        name='暖光·城市' if slot==7 else f'Filter {slot:02d}'
        assert m.publish(slot,name)==0
        token=m.call('af_ap_names_title',menu);assert token==TOKEN+slot-1
        m.call('af_ap_names_sprite',m.sprite,token)
        assert m.text_calls[-1]==name.encode()
    assert not m.native_calls and not m.resource_calls
    # 原名称ID即使与当前自定义槽匹配，也属于帮助/其他文字等完整原路径。
    for resource in (0x200abd8,0x200abde,0x200abeb,0x21c6e11,0xffffffff):
        m.call('af_ap_names_sprite',m.sprite,resource)
        assert m.resource_calls[-1]==(m.sprite,resource)
    for menu in (*range(0x84c,0x858),0x85e,0x15d8,0x1605):
        assert m.call('af_ap_names_title',menu)==m.original(menu)


def test_management_tokens_always_use_original_character_overload_without_resource_fallback(names_module):
    m=ready(names_module)
    expected=[b'Custom Filters',b'Save (Unavailable)',b'Save As (Unavailable)',
              b'Import LUT (Unavailable)',b'Create Filter (Unavailable)',b'Clear (Unavailable)',b'Rename (Unavailable)']
    for i,label in enumerate(expected):
        token=m.call('af_ap_names_title',0x15e7+i if i<5 else 0x1602+i-5)
        assert token==0x7fcb0001+i
        m.call('af_ap_names_sprite',m.sprite,token)
        assert m.text_calls[-1]==label
    assert not m.resource_calls
    assert m.call('af_ap_names_enable',0)==0
    m.call('af_ap_names_sprite',m.sprite,0x7fcb0002)
    assert m.text_calls[-1]==expected[1] and not m.resource_calls
    assert m.call('af_ap_names_detach_allowed')==-4


def test_empty_tombstone_disable_and_allocation_failure_fall_back_by_original_menu(names_module):
    m=ready(names_module);menu=0x15d9
    assert m.call('af_ap_names_title',menu)==m.original(menu)
    assert m.publish(7,'A'*63)==0
    token=m.call('af_ap_names_title',menu);assert token==TOKEN+6
    m.fail_allocation=True;m.call('af_ap_names_sprite',m.sprite,token)
    assert m.text_calls==[b'A'*63] and m.resource_calls[-1]==(m.sprite,m.original(menu))
    assert m.publish(7,b'',2)==0
    m.call('af_ap_names_sprite',m.sprite,token)
    assert len(m.text_calls)==1 and m.resource_calls[-1]==(m.sprite,m.original(menu))
    assert m.publish(7,'New name',3)==0
    assert m.call('af_ap_names_enable',0)==0
    assert m.call('af_ap_names_title',menu)==m.original(menu)
    m.call('af_ap_names_sprite',m.sprite,token)
    assert len(m.text_calls)==1 and m.resource_calls[-1]==(m.sprite,m.original(menu))


def test_bad_binding_or_corrupt_label_never_publish_a_partial_route(names_module):
    m=NamesMachine(names_module)
    assert m.bind(version=2)==-1 and m.call('af_ap_names_enable',1)==-1
    assert m.bind(labels=m.labels+1)==-1 and m.call('af_ap_names_enable',1)==-1
    assert m.bind(obj=0)==-1 and m.call('af_ap_names_enable',1)==-1
    for address in (m.obj+0x16bc64,m.ap+0x220c8a0):
        m.u.mem_write(address,b'\0'*4)
        assert m.bind()==-5 and m.call('af_ap_names_enable',1)==-1
        m.u.mem_write(address,struct.pack('<I',m.preimages[address]))
    assert m.bind()==0
    assert m.bind()==-4 and m.call('af_ap_names_enable',1)==0
    assert m.publish(7,'Valid')==0
    assert m.call('af_ap_names_enable',2)==-1
    assert m.call('af_ap_names_title',0x15d9)==TOKEN+6
    entry=m.labels+6*80
    m.u.mem_write(entry+8,struct.pack('<I',64))
    assert m.call('af_ap_names_title',0x15d9)==m.original(0x15d9)
    m.call('af_ap_names_sprite',m.sprite,TOKEN+6)
    assert not m.text_calls and m.resource_calls[-1]==(m.sprite,m.original(0x15d9))


def test_enabling_names_permanently_requires_resident_entry_points(names_module):
    m=NamesMachine(names_module)
    assert m.call('af_ap_names_detach_allowed')==0
    assert m.bind()==0 and m.call('af_ap_names_detach_allowed')==0
    assert m.call('af_ap_names_enable',1)==0
    assert m.call('af_ap_names_detach_allowed')==-4
    assert m.call('af_ap_names_enable',0)==0
    assert m.call('af_ap_names_detach_allowed')==-4


@pytest.mark.parametrize('language', [0,25])
def test_compact_rows_keep_full_selected_titles_and_never_truncate_utf8(names_module,language):
    m=ready(names_module)
    m.u.mem_write(m.language,struct.pack('<I',language))
    actions=['保存','另存','导入','新建'] if language==25 else ['Save','Copy','Load','New']
    expected={**{0x15e8+i:text for i,text in enumerate(actions)},
              **{0x15ed+i:f'C{i+1:02d}' for i in range(20)},
              **{0x1621+i:f'{i+1:02d}' for i in range(64)},
              0x1601:'取消' if language==25 else 'Back',
              0x1661:'上页' if language==25 else 'Prev',
              0x1662:'下页' if language==25 else 'Next',
              0x1663:'取消' if language==25 else 'Back',
              0x1602:'清空' if language==25 else 'Clear',
              0x1603:'改名' if language==25 else 'Name',
              0x1604:'导出' if language==25 else 'Exp.'}
    for menu,text in expected.items():
        token=m.call('af_ap_names_compact',menu)
        assert token==0x7fce0000+menu-0x15e7
        m.call('af_ap_names_sprite',m.sprite,token)
        assert m.text_calls[-1]==text.encode()
    # 完整选中标题仍走既有带状态／代际的资源，不被短序号替换。
    assert m.call('af_ap_names_title',0x15e8)==0x7fcb0002
    assert m.publish(7,'暖光·城市')==0
    assert m.call('af_ap_names_compact',0x15d9)==m.original(0x15d9)
    assert m.call('af_ap_names_title',0x15d9)==TOKEN+6
    assert not m.resource_calls
    m.call('af_ap_names_sprite',m.sprite,0x7fce001e)
    assert m.text_calls[-1]==b'?' and not m.resource_calls
    assert m.call('af_ap_names_enable',0)==0
    token=m.call('af_ap_names_compact',0x15e8)
    m.call('af_ap_names_sprite',m.sprite,token)
    assert m.text_calls[-1]==actions[0].encode() and not m.resource_calls


@pytest.mark.parametrize('language',[0,25])
def test_private_keyboard_title_uses_filter_name_and_never_system_settings_title(names_module,language):
    m=ready(names_module);m.u.mem_write(m.language,struct.pack('<I',language))
    m.call('af_ap_names_sprite',m.sprite,0x7fcf0001)
    assert m.text_calls[-1]==('滤镜名称' if language==25 else 'Filter Name').encode()
    assert not m.resource_calls
