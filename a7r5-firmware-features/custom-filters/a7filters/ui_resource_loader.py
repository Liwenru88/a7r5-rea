"""原资源文件加载、引用与回收联验；POSIX仍为只读内存后端。"""
import hashlib
import struct

from .access_evidence import AP_SHA, WORK, require_source
from .investigate import AP
from .ui_resource_lookup import OBJ_SHA
from .ui_resources import append_name_fixture
from .resource_vm import ResourceMachine

XDB_PATH='/usr/share/app/global.xdb'
XDB_BYTES=16424
XDB_SHA='9a006e3d9e04d4a5aa6651db6cb7a578a8265eda05389d86ac7f704bbc421c46'


def _bank_paths(machine,namespace,count):
    data=machine.call(0x1229e8,machine.database)
    table=machine.call(0x122930,data+8,namespace)
    if not table or struct.unpack('<I',machine.cpu.mem_read(table+4,4))[0]&0x1fff!=count:
        raise ValueError('原数据库分组条数不符')
    result=[]
    for bank in range(count):
        entry=machine.call(0x122930,table,bank)
        if not entry or bytes(machine.cpu.mem_read(entry,1))!=b'\x80':raise ValueError('原分组不是已知外部分文件')
        basename=machine.string(entry+1).decode()
        if '/' in basename or '..' in basename or not basename.endswith('.uxc'):
            raise ValueError('原分组文件名越界')
        result.append('/usr/share/app/'+basename)
    return result


def _record(machine,label):
    out=WORK+0x7220;machine.write(out,b'\0'*8)
    pointer=machine.call(0x123840,machine.database,label,out)
    owner=struct.unpack('<Q',machine.cpu.mem_read(out,8))[0]
    if pointer and not owner:raise ValueError('原记录未返回所属引用对象')
    return pointer,owner


def _check_text(machine,pointer,path,label):
    # 按唯一记录身份搜索源字节作独立参考，不复刻原指针表计算。
    raw=machine.files[path];needle=struct.pack('<I',0x1e000000|(label&0xffffff))
    offset=raw.find(needle)
    if offset<0 or raw.find(needle,offset+1)>=0:raise ValueError('参考名称记录缺失或不唯一')
    end=raw.find(b'\0',offset+4)
    if end<0:raise ValueError('参考名称文本未终止')
    text=raw[offset+4:end]
    maps=[a for a,info in machine.maps.items() if info['path']==path]
    if len(maps)!=1 or pointer!=maps[0]+offset or machine.string(pointer+4)!=text:
        raise ValueError('原加载/查找未保持文件、记录身份、地址或内容')
    return text.decode('utf-8')


def _scene(obj_raw,files,user_paths,factory_path,language,candidate,labels,factory):
    machine=ResourceMachine(obj_raw,files,guard=True)
    try:
        if machine.load()!=1:raise ValueError('原UXA加载未成功')
        prior=None;queries=missing=0;texts=[]
        for orientation in range(2):
            bank=language*2+orientation;path=user_paths[bank]
            if machine.call(0x1235d8,machine.database,5,bank,0)!=1:raise ValueError('原用户资源切换失败')
            pointer,owner=_record(machine,labels[0]);machine.call(0x123090,owner)
            _check_text(machine,pointer,path,labels[0])
            if prior:
                old_pointer,old_owner,old_path=prior
                _check_text(machine,old_pointer,old_path,labels[0])
                if owner==old_owner:raise ValueError('原不同分组错误共用引用对象')
                machine.call(0x123660,old_owner)
            for index,label in enumerate(labels):
                current,current_owner=_record(machine,label);queries+=1
                if not candidate and index>=6:
                    if current:raise ValueError('原资源凭空包含新增用户名称')
                    missing+=1;continue
                if not current or current_owner!=owner:raise ValueError('同分组原名称引用不一致')
                _check_text(machine,current,path,label)
            prior=(pointer,owner,path)
        machine.call(0x123660,prior[1])
        machine.call(0x1235d8,machine.database,227,language,0)
        pointer,owner=_record(machine,factory[0]);machine.call(0x123090,owner)
        for label in factory:
            current,current_owner=_record(machine,label);queries+=1
            if not current or current_owner!=owner:raise ValueError('原厂名称引用不一致')
            texts.append(_check_text(machine,current,factory_path,label))
        machine.call(0x123660,owner)
        banks=((5,language*2),(5,language*2+1),(227,language))
        cleanup=machine.cleanup(banks)
        opened=[e['path'] for e in machine.events if e['operation']=='open']
        expected={XDB_PATH,user_paths[language*2],user_paths[language*2+1],factory_path}
        if len(opened)!=4 or set(opened)!=expected:raise ValueError('原路径解析或缓存复用不符')
        return dict(language=language,candidate=candidate,user_paths=user_paths[language*2:language*2+2],
                    factory_path=factory_path,factory_texts=texts,queries=queries,missing_new_names=missing,
                    pinned_reference_survived_switch=True,open_calls=4,cleanup=cleanup,
                    guard_patch=machine.guard_patch,
                    native_entry_hits={hex(a):n for a,n in machine.hits.items()},events=machine.events)
    finally:machine.dispose()


def _failures(obj_raw,files,user_paths):
    from unicorn import UcError
    records=[]
    for kind in ('open','stat','database_magic','uxc_magic','mmap','mmap_guarded','mmap_uxc_guarded'):
        view=dict(files);fault=(kind,XDB_PATH) if kind in ('open','stat','mmap') else None
        guarded=kind in ('mmap_guarded','mmap_uxc_guarded')
        if guarded:fault=('mmap',user_paths[0] if kind=='mmap_uxc_guarded' else XDB_PATH)
        if kind=='database_magic':view[XDB_PATH]=b'BAD!'+view[XDB_PATH][4:]
        if kind=='uxc_magic':view[user_paths[0]]=b'BAD!'+view[user_paths[0]][4:]
        machine=ResourceMachine(obj_raw,view,fault,guard=guarded)
        try:
            try:
                loaded=machine.load()
                if kind in ('uxc_magic','mmap_uxc_guarded'):
                    if loaded!=1:raise ValueError('UXC故障前数据库加载失败')
                    pointer,owner=_record(machine,0x0200abd8)
                    if pointer or owner:raise ValueError('错误UXC魔数未拒绝')
                    cleanup=machine.cleanup(((5,0),))
                elif kind=='mmap':raise ValueError('未复现原MAP_FAILED无效读取')
                else:
                    if loaded!=0:raise ValueError('原数据库失败错误报告成功')
                    cleanup=machine.cleanup()
                records.append(dict(case=kind,result='REJECTED_AND_CLEANED',cleanup=cleanup,
                                    guard_patch=machine.guard_patch,events=machine.events))
            except UcError as error:
                pc=machine.cpu.reg_read(machine.r.UC_ARM64_REG_PC)
                if kind!='mmap' or pc!=0x122a84:raise
                records.append(dict(case=kind,result='ORIGINAL_INVALID_READ_REPRODUCED',pc=hex(pc),
                                    error=str(error),native_recovery_verified=False,
                                    open_files=len(machine.fds),mappings=len(machine.maps),events=machine.events))
        finally:machine.dispose()
    return records


def collect(ap_raw,obj_raw,files):
    require_source(ap_raw,AP_SHA,'AP');require_source(obj_raw,OBJ_SHA,'libObj')
    require_source(files.get(XDB_PATH,b''),XDB_SHA,'global.xdb')
    if len(files)!=103:raise ValueError('资源加载联验需要103个同包内存文件')
    ap=AP(ap_raw)
    labels=[ap.u32(0x3f4a280+i*128+8) for i in range(12,18)]+list(range(0x0200abde,0x0200abec))
    factory=[ap.u32(0x3f4a280+i*128+8) for i in range(12)]
    inventory=ResourceMachine(obj_raw,files)
    try:
        if inventory.load()!=1:raise ValueError('原数据库分组获取失败')
        users=_bank_paths(inventory,5,68);factories=_bank_paths(inventory,227,34)
        if set(files)!={XDB_PATH,*users,*factories}:raise ValueError('内存文件集合与原数据库不一致')
        inventory_cleanup=inventory.cleanup()
    finally:inventory.dispose()
    candidates=dict(files)
    for path in users:candidates[path]=append_name_fixture(files[path])[0]
    scenes=[]
    for candidate,view in ((False,files),(True,candidates)):
        for language,path in enumerate(factories):
            scenes.append(_scene(obj_raw,view,users,path,language,candidate,labels,factory))
    for language in range(34):
        if scenes[language]['factory_texts']!=scenes[34+language]['factory_texts']:
            raise ValueError('追加用户名称改变原厂名称')
    failures=_failures(obj_raw,files,users)
    if not all(s['guard_patch']['restored'] for s in scenes):raise ValueError('资源研究保护未精确恢复')
    return dict(status='OFFLINE_NATIVE_LOADING_WITH_RESEARCH_MMAP_GUARD',library_sha256=OBJ_SHA,
                source_files={p:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for p,raw in sorted(files.items())},
                user_language_orientation_files=68,factory_language_files=34,logical_name_ids=32,
                source_and_candidate_scenes=68,name_queries=sum(s['queries'] for s in scenes),
                missing_new_name_results=sum(s['missing_new_names'] for s in scenes),
                scene_file_opens=sum(s['open_calls'] for s in scenes),scenes=scenes,failures=failures,
                inventory_probe_cleanup=inventory_cleanup,original_database_loader_executed=True,
                original_uxc_file_loader_executed=True,original_file_objects_executed=True,
                factory_name_records_verified=True,user_name_records_verified=True,
                native_cache_reference_and_cleanup_verified=True,posix_backend='read-only memory files',
                native_mmap_error_recovery_verified=False,research_guard_recovery_verified=True,
                anonymous_guard_restored=True,font_or_pixels_verified=False,
                full_engine_initialization_verified=False,host_file_or_device_io=False,
                input_modified=False,installable_candidate_allowed=False,
                fixture_boundaries=['engine context and allocator interface','bounded memory/libc primitives and logger',
                                    'POSIX read-only memory filesystem','selected cache-list/database constructors'])
