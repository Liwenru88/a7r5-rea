"""真实锁定AP的非零基址注册/列表联验；不替代Qt整帧或CP成像。"""
import hashlib
from pathlib import Path
import struct
import sys

import pytest
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from unicorn import arm64_const as regs

FEATURE = Path(__file__).resolve().parents[2]
ROOT = FEATURE.parents[1]
sys.path[:0] = [str(FEATURE),str(FEATURE/'tests'),str(ROOT/'a7r5-qemu/tools'),str(Path(__file__).resolve().parent)]
from a7filters.ap_ui_hooks import HOOKS
from a7filters.ui_evidence import MENU_IDS,ROW_TABLE,ROW_BYTES,candidate_rows
from media_candidate import extract
from test_ap_ui_dynamic import modules
from loader import NativeUiLoader
from runtime import ShiftedRegistry


@pytest.fixture(scope='module')
def source():
    path = ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    if not path.is_file():pytest.skip('匹配4.06的隔离源归档不存在')
    assert not path.is_symlink() and path.resolve()==path.absolute()
    with path.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest() == (
        'c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80')
    names = ['usr/lib/appFw.so','usr/lib/libstdc++.so.6.0.22','usr/lib/libObj.so']
    raw = extract(path,names)
    return tuple(raw[name] for name in names)


def setup(source,modules,near=False):
    m = ShiftedRegistry(*source,0x7000000000)
    module_base = m.base+0x9000000 if near else 0x7100000000
    loader = NativeUiLoader(m,modules,module_base,m.base+0x9300000)
    loader.prepare();loader.install()
    assert {p['kind'] for p in loader.patches} == ({'direct'} if near else {'island'})
    return m,loader


def registry_and_list(m,loader,late=False):
    u,base,work = m.u,m.base,m.work
    rows,aliases = work+0x100,work+0x200
    if not late:m.initialize_tree(rows);m.initialize_tree(aliases)
    for offset,address in ((0x5915b80,rows),(0x592f4c8,aliases)):
        m.map_ap(offset);u.mem_write(base+offset,struct.pack('<Q',address))
    # 从原初始化BL进入新模块，再调用真实原行注册器及同包C++树操作。
    if late:m.call(loader.symbols['af_ap_register'],rows,base+ROW_TABLE,base+ROW_TABLE+ROW_BYTES)
    else:m.call(base+0x16f6610,rows,base+ROW_TABLE,base+ROW_TABLE+ROW_BYTES,stop=base+0x16f6614)
    assert struct.unpack('<Q',u.mem_read(rows+0x28,8))[0] == 5605
    assert bytes(u.mem_read(loader.symbols['af_ap_rows'],33*128)) == candidate_rows(m.ap)
    descriptor = bytes(u.mem_read(base+0x5858b08,0xa0))
    assert m.call(loader.symbols['af_ap_research_enable'],1) == 0
    old = MENU_IDS[:18]+[0x85e]
    u.mem_write(work+0x10000,b''.join(struct.pack('<II',k,k) for k in old))
    m.call(base+0x1c935e0,aliases,work+0x10000,work+0x10000+len(old)*8)
    obj,vt = work+0x400,work+0x800
    u.mem_write(obj,struct.pack('<Q',vt))
    points = {0x10:work+0xa000,0x1a8:base+0x1bcfffc,0x790:base+0x1bd9f98,
              0x798:base+0x1bd9ffc,0x700:work+0xa010,0x550:base+0x1bc7840,
              0x560:base+0x1bc785c,0x8c8:base+0x1bc78a4,0x328:work+0xa018,
              0x8d0:work+0xa020,0x210:work+0xa028}
    for offset,address in points.items():u.mem_write(vt+offset,struct.pack('<Q',address))
    m.map_ap(0x591f9a8);u.mem_write(base+0x591f9a8,struct.pack('<Q',vt-16))
    qualification = {'value':1,'menus':[]}
    m.extra[work+0xa000] = lambda cpu:base+0x5858b08
    def qualify(cpu):
        qualification['menus'].append(cpu.reg_read(regs.UC_ARM64_REG_X1));return qualification['value']
    m.extra[work+0xa010] = qualify
    m.extra[work+0xa018] = lambda cpu:0x1e6
    m.extra[work+0xa020] = lambda cpu:0
    m.extra[work+0xa028] = lambda cpu:1
    m.extra[base+0x1be12d0] = lambda cpu:1
    m.extra[base+0x2e7d208] = lambda cpu:0
    m.extra[base+0x2e7cee4] = lambda cpu:0
    def bounded_copy(cpu):
        dest,src,size = [cpu.reg_read(r) for r in (regs.UC_ARM64_REG_X0,regs.UC_ARM64_REG_X1,regs.UC_ARM64_REG_X2)]
        assert size==128
        cpu.mem_write(dest,bytes(cpu.mem_read(src,size)));return dest
    m.extra[base+0x16d9770] = bounded_copy
    native_selector = m.call(base+0x28ae4b0)
    m.map_ap(native_selector-base)
    output = work+0x2800
    cases = []
    for state,special,expected in ((1,0,MENU_IDS[:-1]),(1,16,MENU_IDS),(0,16,[])):
        qualification['value'] = state;qualification['menus'] = []
        u.mem_write(native_selector,struct.pack('<I',special))
        u.mem_write(output-8,b'\xa5'*(33*4+16))
        count = m.call(base+0x1bcf3fc,obj,0x1e6,output,33)
        assert count == len(expected)
        assert list(struct.unpack('<'+'I'*count,u.mem_read(output,count*4))) == expected
        assert not any(k>=0x15d9 for k in qualification['menus'])
        assert bytes(u.mem_read(output-8,8)) == bytes(u.mem_read(output+132,8)) == b'\xa5'*8
        cases.append({'qualification':state,'native_selector':special,'count':count,
                      'menus':list(struct.unpack('<'+'I'*count,u.mem_read(output,count*4)))})
    for row,menu in enumerate(MENU_IDS[:-1]):
        assert m.call(base+0x1bd8eb8,menu) == menu
        expected = m.ap.u32(0x3f4a280+row*128+8) if row<18 else 0x0200abde+row-18
        assert m.call(base+0x1bd1b88,obj,menu) == expected
    assert all(m.hits.get(loader.symbols[name],0)>0 for name in
               ('af_ap_register','af_ap_visible','af_ap_alias','af_ap_name'))
    assert m.redzones()
    return rows,descriptor,cases


@pytest.mark.parametrize('near',[True,False])
def test_actual_original_registry_and_enumeration_through_nonzero_dynamic_loader(source,modules,near,request):
    m,loader = setup(source,modules,near)
    rows,descriptor,cases = registry_and_list(m,loader)
    enabled_descriptor=bytes(m.u.mem_read(m.base+0x5858b08,0xa0))
    with pytest.raises(ValueError,match='禁止卸挂'):loader.remove()
    assert loader.state=='INSTALLED'
    assert bytes(m.u.mem_read(m.base+0x5858b08,0xa0)) == enabled_descriptor
    assert all(bytes(m.u.mem_read(p['source'],4))==p['after'] for p in loader.patches)
    for menu in MENU_IDS[18:32]:
        m.u.mem_write(m.work+0x80,struct.pack('<I',menu))
        holder = m.call(m.base+0x1bd90c4,rows,m.work+0x80)
        pointer = struct.unpack('<Q',m.u.mem_read(holder,8))[0]
        assert pointer == loader.symbols['af_ap_rows']+(18+menu-0x15d9)*128
        assert struct.unpack('<I',m.u.mem_read(pointer,4))[0] == menu
    assert m.redzones()
    request.node.user_properties.append(('native_ui_case',{
        'ap_base':hex(m.base),'module_base':hex(loader.base),'island_base':hex(loader.island),
        'entry_kind':'direct' if near else 'island','patched_entries':len(loader.patches),
        'registry_rows':struct.unpack('<Q',m.u.mem_read(rows+0x28,8))[0],
        'list_cases':cases,'allocator_calls':len(m.allocations),'redzones_valid':m.redzones(),
        'module_entry_hits':{name:m.hits.get(loader.symbols[name],0) for name in
                             ('af_ap_register','af_ap_visible','af_ap_alias','af_ap_name')},
        'native_register_hits':m.hits.get(m.base+0x1c91e94,0),
        'native_rebalance_hits':m.hits.get(m.std_base+0xa6350,0),
        'final_loader_state':loader.state,'registered_user_row_pointers_still_valid':14,
        'registered_detach_rejected_without_mutation':True,
        'all_entry_instructions_retained':all(bytes(m.u.mem_read(p['source'],4))==p['after'] for p in loader.patches),
        'full_gui':False,'CP_imaging':False,
        'boundaries':['bounded node allocator','screen qualification and menu mode predicates',
                      'transaction lock boundary','bounded 128-byte temporary copy',
                      'empty tree and menu object references, not full application boot']}))


def test_preinit_hook_removal_unmaps_module_and_conflicting_owned_patch_is_untouched(source,modules):
    m,loader = setup(source,modules)
    # 先实际走过被替换的BL，撤销后再次走原BL，不能只比较字节而忽略执行缓存。
    assert m.call(m.base+0x220a898,0,stop=m.base+0x220a89c) == 0
    bad = loader.patches[7]
    m.u.mem_write(bad['source'],bytes(4))
    snapshot = [bytes(m.u.mem_read(p['source'],4)) for p in loader.patches]
    with pytest.raises(ValueError,match='其他拥有者'):loader.remove()
    assert loader.state == 'INSTALLED'
    assert [bytes(m.u.mem_read(p['source'],4)) for p in loader.patches] == snapshot
    m.u.mem_write(bad['source'],bad['after'])
    assert loader.remove() == 'UNLOADED'
    assert m.call(m.base+0x220a898,0,stop=m.base+0x220a89c) == 0
    assert not any(start<=loader.base<=end for start,end,_ in m.u.mem_regions())
    assert not any(start<=loader.island<=end for start,end,_ in m.u.mem_regions())


def test_preinit_names_enable_blocks_detach_even_after_names_are_disabled(source,modules):
    m,loader=setup(source,modules)
    assert m.call(loader.symbols['af_ap_names_enable'],1)==0
    assert m.call(loader.symbols['af_ap_names_enable'],0)==0
    with pytest.raises(ValueError,match='禁止卸挂'):loader.remove()
    assert loader.state=='INSTALLED'
    assert all(bytes(m.u.mem_read(p['source'],4))==p['after'] for p in loader.patches)


def test_source_mismatch_and_unowned_entry_reject_before_mapping(source,modules):
    damaged = source[0][:-1]+bytes([source[0][-1]^1])
    with pytest.raises(ValueError,match='身份'):ShiftedRegistry(damaged,source[1],source[2],0x7000000000)
    m = ShiftedRegistry(*source,0x7000000000)
    loader = NativeUiLoader(m,modules,0x7100000000,m.base+0x9300000)
    at = m.base+HOOKS[0][0];m.map_ap(HOOKS[0][0]);m.u.mem_write(at,bytes(4))
    with pytest.raises(ValueError,match='其他拥有者'):loader.prepare()
    assert not any(start<=loader.base<=end for start,end,_ in m.u.mem_regions())


def test_partial_install_failure_restores_only_owned_instructions(source,modules):
    m = ShiftedRegistry(*source,0x7000000000)
    loader = NativeUiLoader(m,modules,0x7100000000,m.base+0x9300000)
    loader.prepare()
    original = m.write_ap_code
    failure = {'raised':False}
    def injected(address,raw):
        if address == loader.patches[6]['source'] and not failure['raised']:
            failure['raised'] = True;raise RuntimeError('显式单指令写入故障')
        return original(address,raw)
    m.write_ap_code = injected
    with pytest.raises(RuntimeError,match='显式'):loader.install()
    assert loader.state == 'BOUND'
    assert all(bytes(m.u.mem_read(p['source'],4))==p['before'] for p in loader.patches)
    m.write_ap_code = original
    loader.install()
    assert loader.remove() == 'UNLOADED'


@pytest.mark.parametrize('owner',['module','AP'])
def test_changed_module_permissions_reject_removal_before_any_instruction_is_changed(source,modules,owner):
    m,loader = setup(source,modules)
    page = (next(loader.base+p for p,permission in loader.pages.items() if permission==5)
            if owner=='module' else loader.patches[8]['source']&~4095)
    m.u.mem_protect(page,4096,3)
    snapshot = [bytes(m.u.mem_read(p['source'],4)) for p in loader.patches]
    with pytest.raises(ValueError,match='权限'):loader.remove()
    assert [bytes(m.u.mem_read(p['source'],4)) for p in loader.patches] == snapshot
    m.u.mem_protect(page,4096,5)
    assert loader.remove() == 'UNLOADED'


def test_actual_hook_first_instructions_do_not_read_veneer_register_x16(source):
    image = ShiftedRegistry(*source,0x7000000000).ap
    decoder = Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);decoder.detail = True
    for at,_,_,_ in HOOKS:
        instruction = next(decoder.disasm(image.read(at,4),at))
        reads,_ = instruction.regs_access()
        assert not {'x16','w16'}&{instruction.reg_name(r) for r in reads}


def test_midway_module_mapping_failure_releases_only_new_owned_pages(source,modules):
    m = ShiftedRegistry(*source,0x7000000000)
    loader = NativeUiLoader(m,modules,0x7100000000,m.base+0x9300000)
    original = m.u.mem_map
    failed = loader.base+sorted(loader.pages)[1]
    def injected(address,size,permission=7):
        if address==failed:raise RuntimeError('显式第二页映射失败')
        return original(address,size,permission)
    m.u.mem_map = injected
    with pytest.raises(RuntimeError,match='第二页'):loader.prepare()
    assert loader.state == 'REJECTED' and not loader.failure['unmap_errors']
    regions = list(m.u.mem_regions())
    assert not any(start<=loader.base+p<=end for p in loader.pages for start,end,_ in regions)
    assert not any(start<=loader.island<=end for start,end,_ in regions)
    assert bytes(m.u.mem_read(m.work,8)) == bytes(8)
    assert all(bytes(m.u.mem_read(p['source'],4))==p['before'] for p in loader.patches)


def test_late_attach_preserves_all_original_registry_nodes_and_adds_only_fourteen(source,modules,request):
    m = ShiftedRegistry(*source,0x7000000000)
    rows,aliases = m.work+0x100,m.work+0x200
    m.initialize_tree(rows);m.initialize_tree(aliases)
    m.map_ap(0x5915b80);m.u.mem_write(m.base+0x5915b80,struct.pack('<Q',rows))
    m.call(m.base+0x16f6610,rows,m.base+ROW_TABLE,m.base+ROW_TABLE+ROW_BYTES,stop=m.base+0x16f6614)
    def snapshot():
        stack=[struct.unpack('<Q',m.u.mem_read(rows+0x10,8))[0]];result={};seen=set()
        while stack:
            node=stack.pop()
            if not node:continue
            assert node not in seen and len(seen)<6000;seen.add(node)
            raw=bytes(m.u.mem_read(node,48));key=struct.unpack_from('<I',raw,0x20)[0]
            assert key not in result
            result[key]=(node,struct.unpack_from('<Q',raw,0x28)[0])
            stack.extend(struct.unpack_from('<QQ',raw,0x10))
        assert len(result)==struct.unpack('<Q',m.u.mem_read(rows+0x28,8))[0]
        return result
    before=snapshot();assert len(before)==5591
    for i in range(5591):
        at=ROW_TABLE+i*16;key=m.ap.ptr(at)
        assert before[key][1]==m.base+m.ap.ptr(at+8)
    loader=NativeUiLoader(m,modules,0x7100000000,m.base+0x9300000)
    loader.prepare();loader.install()
    _,descriptor,cases=registry_and_list(m,loader,late=True)
    after=snapshot()
    assert len(after)==5605 and {k:after[k] for k in before}==before
    assert set(after)-set(before)==set(range(0x15d9,0x15e7))
    enabled_descriptor=bytes(m.u.mem_read(m.base+0x5858b08,0xa0))
    with pytest.raises(ValueError,match='禁止卸挂'):loader.remove()
    assert loader.state=='INSTALLED'
    assert bytes(m.u.mem_read(m.base+0x5858b08,0xa0))==enabled_descriptor
    assert all(bytes(m.u.mem_read(p['source'],4))==p['after'] for p in loader.patches)
    request.node.user_properties.append(('late_attach_case',{
        'original_nodes_preserved':len(before),'final_nodes':len(after),'new_nodes':len(after)-len(before),
        'all_original_values_and_node_addresses_preserved':True,'static_constructor_replayed':False,
        'list_counts':[c['count'] for c in cases],'final_loader_state':loader.state}))
