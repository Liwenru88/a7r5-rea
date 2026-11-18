"""当前CP完整Gamma选表/构造与新非均匀采样接口，无ISP像素执行。"""
import hashlib
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK
from .investigate import CP_BASE

TABLE,SOURCE,DESTINATION,PAYLOAD_BYTES=0x1a396d8,0x11d3000,0x1a39450,5872
WIRES=(0,3,2,1,16,15,17,18,5,13,19,20)


def setup(cp,wire,column):
    m=CpMachine(cp)
    m.map_ram(0x1a39000,0x2000);m.map_ram(0x19d1000,0x1000)
    # 显式影子载荷模型；不冒充原引导复制/清理或完整CP启动。
    m.put(DESTINATION,cp[SOURCE-CP_BASE:SOURCE-CP_BASE+PAYLOAD_BYTES])
    m.put(WORK+0x1000,struct.pack('<II2B',1,wire,0,0))
    m.run(0xaa8688,arguments=(WORK+0x1000,WORK+0x2000))
    route=m.word(WORK+0x2030)
    m.put(WORK+0x2038,bytes([column]))
    return m,route


def record(cp,m,pointer):
    if CP_BASE<=pointer<=CP_BASE+len(cp)-576:return cp[pointer-CP_BASE:pointer-CP_BASE+576]
    if DESTINATION<=pointer<=DESTINATION+PAYLOAD_BYTES-576:return m.read(pointer,576)
    raise ValueError('原Gamma记录指针不在声明数据区：'+hex(pointer))


def construct(m):
    m.put(WORK+0x4000-16,b'\xa5'*(0x800+32))
    m.run(0x41363c,arguments=(0,WORK+0x2000,WORK+0x4000),limit=100000)
    if m.read(WORK+0x4000-16,16)!=b'\xa5'*16 or m.read(WORK+0x4800,16)!=b'\xa5'*16:
        raise ValueError('原Gamma完整构造越过输出保护区')
    return m.read(WORK+0x4018,516),m.read(WORK+0x424c,516)


def collect(cp,a):
    require_source(cp,CP_SHA,'CP')
    if struct.unpack_from('<12H',cp,0x413d8c-CP_BASE)!=(32,32,64,128,256,512,1024,2048,4096,8192,16384,32768):
        raise ValueError('原Gamma分段宽度变化')
    if struct.unpack_from('<12H',cp,0x413da4-CP_BASE)!=(0,32,64,128,256,512,1024,2048,4096,8192,16384,32768):
        raise ValueError('原Gamma分段起点变化')
    cases=[];axis_digest=set()
    for wire in WIRES+tuple(range(249,255)):
        for column in range(7):
            m,route=setup(cp,wire,column)
            try:
                expected_route=struct.unpack_from('<I',cp,0xf76efc+wire*8)[0] if wire<249 else 51+2*(wire-249)
                if route!=expected_route:raise ValueError('原Gamma局部选择/现有六款映射不符')
                source_pointer=m.word(TABLE+route*28+column*4);raw=record(cp,m,source_pointer)
                axis,values=construct(m);source_for_values=raw
                if wire>=249:
                    tone=m.read(DESTINATION+(wire-249)*108,6)
                    a.cpu.mem_write(WORK+0x1000,raw);a.cpu.mem_write(WORK+0x2000,tone)
                    if a.call('af_joint_gamma_record',WORK+0x1000,WORK+0x2000,WORK+0x3000):
                        raise ValueError('原六款联合Gamma整数参考失败')
                    source_for_values=bytes(a.cpu.mem_read(WORK+0x3000,576))
                if values!=source_for_values[:516]:raise ValueError('原Gamma完整构造没有消费所选曲线')
                a.cpu.mem_write(WORK+0x1000,raw);a.cpu.mem_write(WORK+0x5000-16,b'\xa5'*548)
                if a.call('af_gamma406_axis',WORK+0x1000,WORK+0x5000) or bytes(a.cpu.mem_read(WORK+0x5000,516))!=axis:
                    raise ValueError('新AArch64轴与原CP完整构造不符')
                if bytes(a.cpu.mem_read(WORK+0x5000-16,16))!=b'\xa5'*16 or bytes(a.cpu.mem_read(WORK+0x5000+516,16))!=b'\xa5'*16:
                    raise ValueError('新Gamma轴破坏保护区')
                digest=hashlib.sha256(axis).hexdigest();axis_digest.add(digest)
                cases.append(dict(wire=wire,column=column,route=route,source_pointer=hex(source_pointer),
                    source_sha256=hashlib.sha256(raw).hexdigest(),axis_sha256=digest,
                    values_sha256=hashlib.sha256(values).hexdigest(),native_constructor_complete=True,
                    aarch64_axis_equal=True,legacy_tone_preserved=wire>=249,bounds_preserved=True))
            finally:m.cpu=None
    replacements=[]
    for wire,column in [(w,c) for w in (0,3,19,20) for c in (0,6)]+[(249,0)]:
        m,route=setup(cp,wire,column)
        try:
            pointer=m.word(TABLE+route*28+column*4);raw=record(cp,m,pointer)
            old_axis,_=construct(m)
            curve=struct.pack('<129I',*[(i*i*180001)//16384 for i in range(129)])
            a.cpu.mem_write(WORK+0x1000,raw);a.cpu.mem_write(WORK+0x2000,curve)
            a.cpu.mem_write(WORK+0x3000,b'\xa5'*576)
            if a.call('af_gamma406_replace',WORK+0x1000,WORK+0x2000,WORK+0x3000):
                raise ValueError('新Gamma完整曲线替换被拒绝')
            candidate=bytes(a.cpu.mem_read(WORK+0x3000,576));expected=bytearray(raw)
            expected[:516]=curve;struct.pack_into('<I',expected,0x220,180001)
            if candidate!=expected:raise ValueError('Gamma替换改变了原附属字段')
            m.put(WORK+0x8000,candidate);m.word(TABLE+route*28+column*4,WORK+0x8000)
            new_axis,new_values=construct(m);legacy=wire>=249
            if legacy:
                a.cpu.mem_write(WORK+0x1000,candidate)
                a.cpu.mem_write(WORK+0x2000,m.read(DESTINATION+(wire-249)*108,6))
                if a.call('af_joint_gamma_record',WORK+0x1000,WORK+0x2000,WORK+0x3000):
                    raise ValueError('原六款二次tone参考失败')
                wanted=bytes(a.cpu.mem_read(WORK+0x3000,516))
                if new_values==curve:raise ValueError('未复现原六款tone继续处理完整候选')
            else:wanted=curve
            if new_axis!=old_axis or new_values!=wanted:raise ValueError('原Gamma未保持轴或消费完整候选')
            replacements.append(dict(wire=wire,column=column,route=route,axis_preserved=True,
                full_curve_consumed=not legacy,legacy_tone_reapplied=legacy,
                candidate_sha256=hashlib.sha256(candidate).hexdigest(),native_values_sha256=hashlib.sha256(new_values).hexdigest()))
        finally:m.cpu=None
    spans=[]
    axis_bytes=bytes(a.cpu.mem_read(WORK+0x5000,516));xs=struct.unpack('<129I',axis_bytes)
    for code in (0,1,31,32,2048,2049,61440,65534,65535):
        if a.call('af_gamma406_locate',WORK+0x5000,code,WORK+0x6000):raise ValueError('AArch64原域区间定位失败')
        actual=struct.unpack('<4I',a.cpu.mem_read(WORK+0x6000,16))
        left=max(i for i,x in enumerate(xs[:-1]) if x<=code)
        if actual!=(left,left+1,code-xs[left],xs[left+1]-xs[left]):raise ValueError('原域区间定位边界不符')
        spans.append(dict(code=code,left=left,right=left+1,offset=actual[2],width=actual[3]))
    return dict(status='OFFLINE_NATIVE_GAMMA_DOMAIN_VERIFIED',cp_sha256=CP_SHA,
        domain=[0,65535],axis_points=129,axis_kind='nonuniform-segmented',unique_axes=len(axis_digest),
        cases=cases,replacements=replacements,span_cases=spans,
        shadow_payload_sha256=hashlib.sha256(cp[SOURCE-CP_BASE:SOURCE-CP_BASE+PAYLOAD_BYTES]).hexdigest(),
        original_selector='0xaa8688',original_constructor='0x41363c',
        full_color_model_verified=False,hardware_interpolation_rounding_verified=False,
        actual_startup_copy_verified=False,camera_io=False,input_modified=False,
        fixture_boundaries=['declared anonymous joint-payload copy', 'zero Gamma debug globals',
            'partial-update input active=1, mode/contrast flags zero',
            'seven numeric columns without EVF/JPG identity', 'candidate pointer only in anonymous Gamma table'])
