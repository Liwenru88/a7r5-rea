"""执行新增AArch64适配器，并在隔离AP回调入口验证用户分流；不写固件。"""
import hashlib
import io
import struct

from .access_evidence import AP_SHA, WORK, STOP, arm64_cpu, run64, require_source
from .investigate import AP
from .ui_evidence import MENU_IDS, SELECTORS


def collect(ap_raw,adapter_raw):
    require_source(ap_raw,AP_SHA,'AP')
    from elftools.elf.elffile import ELFFile
    from unicorn import UC_HOOK_CODE
    from unicorn import arm64_const as regs
    elf=ELFFile(io.BytesIO(adapter_raw))
    if elf['e_machine']!='EM_AARCH64' or elf['e_type']!='ET_EXEC' or not elf.little_endian:
        raise ValueError('适配器必须是独立AArch64测试ELF')
    symbols={s.name:int(s['st_value']) for s in elf.get_section_by_name('.symtab').iter_symbols()
             if s.name and s['st_shndx']!='SHN_UNDEF'}
    required=('af_ui_item','af_ui_read','af_ui_step','af_catalog_bytes','af_catalog_init','af_install','af_read')
    if any(name not in symbols or not 0x92000000<=symbols[name]<0x92010000 for name in required):
        raise ValueError('适配器函数或测试链接地址不符')
    cpu=arm64_cpu(AP(ap_raw),[0x2209000,0x220a000])
    pages=set()
    for seg in elf.iter_segments():
        if seg['p_type']!='PT_LOAD':continue
        start,end=seg['p_vaddr'],seg['p_vaddr']+seg['p_memsz']
        if not ((start==0x200000 and end<=0x201000) or 0x92000000<=start<=end<=0x92020000):
            raise ValueError('适配器超出隔离映射预算')
        for page in range(start&~4095,(end+4095)&~4095,4096):
            if page not in pages:
                cpu.mem_map(page,4096);pages.add(page)
        cpu.mem_write(start,seg.data())
    def call(address,*arguments):
        for i,value in enumerate(arguments):
            cpu.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value)
        cpu.reg_write(regs.UC_ARM64_REG_LR,STOP)
        run64(cpu,address)
        return cpu.reg_read(regs.UC_ARM64_REG_X0)&0xffffffff
    size=call(symbols['af_catalog_bytes'])
    if not 0<size<0x8000:raise ValueError('目录尺寸超出隔离预算')
    catalog,preset,output=WORK+0x2000,WORK+0x1800,WORK+0x900
    call(symbols['af_catalog_init'],catalog)
    originals={}
    for slot in range(1,21):
        values=[slot%10,-(slot%10),2,1,-2,3,3,4]
        raw=struct.pack('<BB8b64x',18,0,*values)
        cpu.mem_write(preset,raw)
        if call(symbols['af_install'],catalog,slot,preset,0)!=0:
            raise ValueError('目标C目录安装夹具失败')
        originals[slot]=raw
    for index,menu in enumerate(MENU_IDS):
        route=WORK+0x800
        if call(symbols['af_ui_item'],index,route)!=0:
            raise ValueError('目标C身份映射失败')
        fields=struct.unpack('<5I',cpu.mem_read(route,20))
        if fields[0]!=menu or fields[3]!=SELECTORS[index]:
            raise ValueError('目标C与当前AP候选身份表不一致')
    entries={0x2209918+p*0x154:p for p in range(8)}
    selected={'menu':0,'calls':0}
    def entry_boundary(u,at,length,data):
        if at not in entries:return
        direction=u.reg_read(regs.UC_ARM64_REG_X1)
        # 仅模拟未来入口分流；真正运行目标C，不以Python修改目录或返回成功。
        arguments=(catalog,selected['menu'],entries[at],direction,output)
        for i,value in enumerate(arguments):
            u.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value)
        selected['calls']+=1
        u.reg_write(regs.UC_ARM64_REG_PC,symbols['af_ui_step'])
    cpu.hook_add(UC_HOOK_CODE,entry_boundary)
    for row in range(12,32):
        menu=MENU_IDS[row];slot=row-11
        selected['menu']=menu
        for parameter in range(8):
            initial=struct.unpack_from('<b',originals[slot],2+parameter)[0]
            for direction in (0,1):
                cpu.mem_write(output-8,b'\xa5'*20)
                if call(0x2209918+parameter*0x154,WORK+0x600,direction)!=0:
                    raise ValueError('AP入口分流后的目标C调节失败')
                current=struct.unpack('<i',cpu.mem_read(output,4))[0]
                high=(9,9,9,9,9,9,5,9)[parameter]
                expected=min(initial+1,high) if direction==0 else min(initial+1,high)-1
                if current!=expected or bytes(cpu.mem_read(output-8,8))!=b'\xa5'*8 or bytes(cpu.mem_read(output+4,8))!=b'\xa5'*8:
                    raise ValueError('目标调参结果或输出保护区不符')
                if call(symbols['af_ui_read'],catalog,menu,parameter,output)!=0 or struct.unpack('<i',cpu.mem_read(output,4))[0]!=expected:
                    raise ValueError('目标C调节和读取值不一致')
            # 初值在上界时，先减后加才能回到同一基线；本批夹具最大contrast为9。
            if initial==high:
                if call(symbols['af_ui_step'],catalog,menu,parameter,0,output)!=0:
                    raise ValueError('目标边界恢复失败')
        if call(symbols['af_read'],catalog,slot,1,preset)!=0 or bytes(cpu.mem_read(preset,74))!=originals[slot]:
            raise ValueError('用户调节误改保存值')
    before=bytes(cpu.mem_read(catalog,size))
    for slot in range(1,21):
        if call(symbols['af_read'],catalog,slot,0,preset)!=0 or bytes(cpu.mem_read(preset,74))!=originals[slot]:
            raise ValueError('目标调参回退后槽位之间发生串扰')
    for menu in MENU_IDS[:12]:
        cpu.mem_write(output,b'\xa5'*4)
        if call(symbols['af_ui_step'],catalog,menu,0,0,output)!=1 or bytes(cpu.mem_read(output,4))!=b'\xa5'*4:
            raise ValueError('目标C原厂委派契约不符')
        if call(symbols['af_ui_read'],catalog,menu,0,output)!=1 or bytes(cpu.mem_read(output,4))!=b'\xa5'*4:
            raise ValueError('目标C原厂读取委派契约不符')
    if bytes(cpu.mem_read(catalog,size))!=before:
        raise ValueError('原厂委派修改了用户目录')
    return dict(schema='a7r5-target-ui-adapter/1',adapter_sha256=hashlib.sha256(adapter_raw).hexdigest(),
                adapter_bytes=len(adapter_raw),catalog_bytes=size,identity_queries=33,
                user_callback_entries=selected['calls'],builtin_delegations=12,
                user_parameter_reads=320,
                target_c_instructions_executed=True,native_18_arrays_mapped=False,
                isolated_entry_hook_only=True,actual_ap_hook_installed=False,
                fixture_boundaries=['AP callback entry diversion','current menu identity','installed preset fixtures'],
                camera_io=False,cp_or_storage_called=False,firmware_modified=False,
                full_presenter_or_pixels_verified=False)
