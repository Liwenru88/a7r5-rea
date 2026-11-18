"""执行原生资源记录查找窗口；不替代数据库加载、文件获取或字体绘制。"""
import struct

from .access_evidence import AP_SHA, require_source, arm64_cpu, run64
from .investigate import AP
from .ui_resources import decode, append_name_fixture

OBJ_PATH='/lib/libObj.so'
OBJ_BYTES=2888984
OBJ_SHA='0d0be8f1e48b3c74330f9afab698ac352b3c2a922f7231ffc836591529a9fdf9'


def collect(ap_raw,obj_raw,resources):
    require_source(ap_raw,AP_SHA,'AP')
    require_source(obj_raw,OBJ_SHA,'libObj')
    from unicorn import arm64_const as r
    ap,image=AP(ap_raw),AP(obj_raw)
    labels=sorted({ap.u32(0x3f4a280+i*128+8) for i in range(12,18)}|
                  set(range(0x0200abde,0x0200abec)))
    factory=[ap.u32(0x3f4a280+i*128+8) for i in range(12)]
    if len(labels)!=20 or len(resources)!=68 or any(v&~0x1fff!=0x0200a000 for v in labels):
        raise ValueError('原生名称查找缺少20文本身份、68资源或命名空间不符')
    cpu=arm64_cpu(image,[0x122000])
    arena,size=0x92000000,0x50000;data=arena+16
    cpu.mem_map(arena,size)
    cases=misses=0
    for name,original in sorted(resources.items()):
        candidate,_=append_name_fixture(original)
        for raw,required in ((original,labels[:6]),(candidate,labels)):
            if len(raw)+32>size:raise ValueError('名称资源超出查找窗口内存预算')
            layout=decode(raw)
            if not set(required)<=layout['entries'].keys():raise ValueError('原生名称查找缺少应存在的用户名称')
            cpu.mem_write(data-16,b'\xa5'*16+raw+b'\xa5'*16)
            for label in labels:
                index=label&0x1fff
                cpu.reg_write(r.UC_ARM64_REG_X0,data+8)
                cpu.reg_write(r.UC_ARM64_REG_X1,index)
                run64(cpu,0x122930,1000)
                actual=cpu.reg_read(r.UC_ARM64_REG_X0)
                entry=layout['entries'].get(label)
                expected=data+layout['data_base']+entry['pointer']*4 if entry else 0
                if actual!=expected:raise ValueError('原生UXC查找与记录位置不符: '+name)
                if entry:
                    text=entry['text'].encode()+b'\0'
                    header=struct.unpack('<I',cpu.mem_read(actual,4))[0]
                    if header!=0x1e000000|(label&0xffffff) or bytes(cpu.mem_read(actual+4,len(text)))!=text:
                        raise ValueError('原生名称查找未保持资源身份/UTF-8内容')
                cases+=1;misses+=not entry
            for index in (layout['count'],0xffff):
                cpu.reg_write(r.UC_ARM64_REG_X0,data+8)
                cpu.reg_write(r.UC_ARM64_REG_X1,index)
                run64(cpu,0x122930,1000)
                if cpu.reg_read(r.UC_ARM64_REG_X0)!=0:raise ValueError('资源越界索引未返回空指针')
                cases+=1;misses+=1
            if bytes(cpu.mem_read(data-16,16))!=b'\xa5'*16 or bytes(cpu.mem_read(data+len(raw),16))!=b'\xa5'*16:
                raise ValueError('原生资源查找修改保护区')
    return dict(status='NATIVE_RESOURCE_LOOKUP_WINDOW_EXECUTED',library_path=OBJ_PATH,
                library_sha256=OBJ_SHA,entry='0x122930',offset_decoder='0x122870',
                language_layout_resources=68,original_and_candidate_cases=cases,
                empty_or_out_of_range_cases=misses,user_text_name_ids=20,
                old_and_new_name_records_verified=True,factory_name_resource_ids=list(map(hex,factory)),
                factory_name_lookup_verified=False,redzones_unchanged=True,external_calls=0,
                database_loader_executed=False,uxc_file_loader_executed=False,
                font_or_pixels_verified=False,camera_io=False,resource_files_written=False,
                fixture_boundaries=['verified resource bytes staged in bounded memory','record index arguments'])
