"""当前CP完整矩阵/CC1构造与原生重建；属性和校准为显式夹具。"""
import hashlib
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK,STACK,STOP
from .cp_gamma406 import SOURCE,DESTINATION,PAYLOAD_BYTES
from .investigate import CP_BASE

MATRIX,STYLE=0x16b3414,0x16b0f14
DIAGONAL=(1056,992,1107)
ADJUST=(-125,110,-87,99,201,211,239,251)


def fixtures():
    matrix=bytearray(0x7000);style=bytearray(0x2000)
    for p in range(52):matrix[0x196+p]=p%56;style[0x1200+p]=p%40
    for bank in range(32):
        for e in range(3):
            for sector in range(16):
                struct.pack_into('<6H',matrix,0x1e0+bank*768+e*192+sector*12,
                    *[((bank*11+e*29+sector*7+j*13)%129-64)&65535 for j in range(6)])
    for bank in range(32,56):
        for e in range(3):struct.pack_into('<6H',matrix,0x61e0+(bank-32)*48+e*12,
            *[((bank*11+e*29+j*13)%129-64)&65535 for j in range(6)])
    for bank in range(40):struct.pack_into('<24H',style,0x1250+bank*64,
        *[((bank*3+j*11)%97-48)&65535 for j in range(24)])
    for mode in range(2):struct.pack_into('<8H',style,0xf00+mode*16,*[300+mode*200+j*17 for j in range(8)])
    return bytes(matrix),bytes(style)


def setup(cp,marker=0,flag=1,adjust=True):
    m=CpMachine(cp)
    try:
        m.map_ram(0x16af000,0xc000);m.map_ram(0x1a39000,0x2000);m.map_ram(0x195e000,0x2000)
        m.put(DESTINATION,cp[SOURCE-CP_BASE:SOURCE-CP_BASE+PAYLOAD_BYTES])
        matrix,style=fixtures();m.put(MATRIX,matrix);m.put(STYLE,style)
        m.put(0x195effc+0x30,bytes(ADJUST[4:])+bytes(v&255 for v in ADJUST[:4]))
        # 原全局修正器：bit3置位跳过修正，否则读取已声明的8字节全局回退。
        m.put(0x16afd14+12,bytes([0 if adjust else 8]))
        m.word(WORK+0x3000,WORK+0x1000);m.word(WORK+0x3004,WORK+0x2000)
        m.put(WORK+0x1001,bytes([flag]));m.put(WORK+0x102e,bytes([marker]))
        m.put(WORK+0x21a0,struct.pack('<3H',*DIAGONAL))
        return m,matrix,style
    except Exception:
        m.cpu=None
        raise


def _half(values):return struct.pack('<'+'H'*len(values),*[v&65535 for v in values])


def _original(m,entry,arguments,size,diagnostic=False):
    out=arguments[0];m.put(out-16,b'\xa5'*(size+32))
    result=m.run(entry,arguments=arguments,limit=30000,stop_before=(0x722396,) if diagnostic else ())
    if m.read(out-16,16)!=b'\xa5'*16 or m.read(out+size,16)!=b'\xa5'*16:
        raise ValueError('原颜色完整构造越过输出保护区')
    for write in m.writes:
        at=int(write['address'],16);end=at+write['bytes']
        if not (out<=at<end<=out+size or STACK<=at<end<=STACK+0x10000):
            raise ValueError('原颜色构造写入了未声明的输出/栈之外地址')
    return m.read(out,size),result


def _native(a,name,raw,extra,metadata=None):
    size={'af_color406_matrix':54,'af_color406_primary':48,'af_color406_secondary':32}[name]
    a.cpu.mem_write(WORK+0x1000,raw);a.cpu.mem_write(WORK+0x2000,extra)
    a.cpu.mem_write(WORK+0x3000-16,b'\xa5'*(size+32))
    args=(WORK+0x1000,WORK+0x2000,WORK+0x3000)
    if metadata is not None:
        a.cpu.mem_write(WORK+0x4000,metadata);args=(WORK+0x1000,WORK+0x2000,WORK+0x4000,WORK+0x3000)
    if a.call(name,*args):raise ValueError('新AArch64拒绝已验证颜色参数')
    if (bytes(a.cpu.mem_read(WORK+0x1000,len(raw)))!=raw or bytes(a.cpu.mem_read(WORK+0x2000,len(extra)))!=extra or
        bytes(a.cpu.mem_read(WORK+0x3000-16,16))!=b'\xa5'*16 or bytes(a.cpu.mem_read(WORK+0x3000+size,16))!=b'\xa5'*16 or
        metadata is not None and bytes(a.cpu.mem_read(WORK+0x4000,len(metadata)))!=metadata):
        raise ValueError('新颜色重建破坏源参数或保护区')
    return bytes(a.cpu.mem_read(WORK+0x3000,size))


def _add(a,source,delta):
    n=len(source);a.cpu.mem_write(WORK+0x1000,source);a.cpu.mem_write(WORK+0x2000,delta)
    a.cpu.mem_write(WORK+0x3000-16,b'\xa5'*(n+32))
    if a.call('af_color406_add',WORK+0x1000,WORK+0x2000,n//2,WORK+0x3000):raise ValueError('新颜色增量被拒绝')
    if (bytes(a.cpu.mem_read(WORK+0x1000,n))!=source or bytes(a.cpu.mem_read(WORK+0x2000,n))!=delta or
        bytes(a.cpu.mem_read(WORK+0x3000-16,16))!=b'\xa5'*16 or bytes(a.cpu.mem_read(WORK+0x3000+n,16))!=b'\xa5'*16):
        raise ValueError('新颜色增量破坏源或保护区')
    return bytes(a.cpu.mem_read(WORK+0x3000,n))


def _matrix_source(m,profile,sector,matrix):
    sector=sector if sector<=15 else 0
    if 54<=profile<=57:
        at=0x1a3a000+(profile-54)*576+sector*36
        return m.read(at,36),dict(kind='current CP embedded payload',pointer=hex(at),sector=sector)
    bank=matrix[0x196+profile] if profile<=51 else 0
    if bank>55:bank=0
    offsets=[0x1e0+bank*768+e*192+sector*12 if bank<32 else 0x61e0+(bank-32)*48+e*12 for e in range(3)]
    return b''.join(matrix[at:at+12] for at in offsets),dict(kind='synthetic runtime property',bank=bank,sector=sector,offsets=offsets)


def _cc1_source(cp,profile,style):
    if profile==52 or profile>57:return None,dict(kind='native no-write')
    if profile==53:
        at=0xe8d502;return cp[at-CP_BASE:at-CP_BASE+48],dict(kind='original fixed record',pointer=hex(at))
    if profile>=54:
        at=0xbef3ec+(profile-54)*48;return cp[at-CP_BASE:at-CP_BASE+48],dict(kind='current CP embedded record',pointer=hex(at))
    bank=style[0x1200+profile];bank=bank if bank<=39 else 0;at=0x1250+bank*64
    return style[at:at+48],dict(kind='synthetic runtime property',bank=bank,offset=at)


def _blend_original(cp,profile,marker,parameter,mix):
    m,matrix,style=setup(cp,marker)
    try:
        # 六参数原调用约定：前四项寄存器，root和pipeline放在调用者栈。
        pipe,holder,color=WORK+0x8000,WORK+0x9000,WORK+0xa000
        m.word(pipe,holder);m.word(holder,WORK+0x1000);m.word(pipe+4,WORK+0xb000);m.word(pipe+8,color)
        # 此参数范围内原0x71f852的固定段；只用于建立可独立复算的数值夹具。
        white=16384+(((16384-parameter)*293+128)>>8)
        limit,low=(0,0) if mix==0 else (512,white-256) if mix==128 else (1,0)
        m.put(0x16afd14+0x400,struct.pack('<10H',100,200,1000,200,800,400,600,limit,limit,0))
        m.put(0x16afd14+0x606,struct.pack('<H',1000))
        output=WORK+0x7000;m.put(output-16,b'\xa5'*48)
        m.register('sp',STACK+0xe000);m.register('lr',STOP|1)
        m.put(STACK+0xe000,struct.pack('<2I',WORK+0x3000,pipe))
        state=m.run(0x71b8a0,arguments=(profile<<8,0,(parameter<<16)|low,output),preserve_state=True,limit=30000)
        if state['status']!='RETURNED' or m.read(output-16,16)!=b'\xa5'*16 or m.read(output+16,16)!=b'\xa5'*16:
            raise ValueError('原CC1完整插值未返回或破坏保护区')
        allowed=((output,output+16),(color+0x52,color+0x5c),(WORK+0x13de,WORK+0x13ec),(STACK,STACK+0x10000))
        for write in m.writes:
            at=int(write['address'],16)
            if not any(first<=at<at+write['bytes']<=last for first,last in allowed):
                raise ValueError('原CC1插值写入未声明区域')
        weights=struct.unpack('<5H',m.read(color+0x52,10))
        primary=((max(100,min(1000,parameter))-100)*256)//900
        if parameter<=200:secondary=(256,0,0)
        elif parameter<=400:
            q=(parameter-200)*256//200;secondary=(256-q,q,0)
        elif parameter<=600:secondary=(0,256,0)
        elif parameter<=800:
            q=(parameter-600)*256//200;secondary=(0,256-q,q)
        else:secondary=(0,0,256)
        if weights!=(primary,*secondary,mix):raise ValueError('原CC1插值权重与独立阈值期待不符')
        raw,_=_cc1_source(cp,profile,style);v=struct.unpack('<24H',raw)
        endpoints=[v[i%8]+ADJUST[i%8]+(v[i] if i>=8 else 0) for i in range(24)]
        if marker>=249:
            delta=struct.unpack('<24h',m.read(DESTINATION+(marker-249)*108+60,48))
            endpoints=[x+d for x,d in zip(endpoints,delta)]
        endpoints=struct.unpack('<24h',_half(endpoints));c_weights=(primary,secondary[2],secondary[1],mix)
        expected=[]
        def signed(value):return (value+32768)%65536-32768
        for i in range(8):
            x,y,z=endpoints[i],endpoints[i+8],endpoints[i+16]
            first=signed(x+(y-x)*primary//256)
            second=signed(x+((y-x)*secondary[2]+(z-x)*secondary[1])//256)
            result=first*(256-mix)+second*mix
            expected.append(signed((abs(result)+128)//256*(1 if result>=0 else -1)))
        actual=m.read(output,16)
        if actual!=_half(expected):raise ValueError('原CC1两级插值/有符号舍入与独立期待不符')
        return actual,_half(endpoints),c_weights
    finally:m.cpu=None


def collect(cp,a):
    require_source(cp,CP_SHA,'CP')
    if a.call('af_color406_target_check'):raise ValueError('AArch64颜色构造契约失败')
    checks=struct.unpack('<4I',a.cpu.mem_read(a.symbols['af_color406_target_report'],16))
    if checks[0]!=0x43323331 or checks[1]<100 or checks[2:]!=(27,24):raise ValueError('AArch64颜色契约报告不符')
    matrix_cases=[];primary_cases=[];secondary_cases=[];legacy=[];blend_cases=[]
    for profile in range(58):
        m,matrix,style=setup(cp)
        try:
            sectors=range(16) if profile in (0,31,32,54) else (0,15)
            for sector in sectors:
                raw,origin=_matrix_source(m,profile,sector,matrix)
                coefficients=struct.unpack('<18H',raw);want=[]
                for offset in range(0,18,6):
                    x,y,z,u,v,w=coefficients[offset:offset+6]
                    want.extend((DIAGONAL[0]+x+y,-x,-y,-z,DIAGONAL[1]+z+u,-u,-v,-w,DIAGONAL[2]+v+w))
                actual,_=_original(m,0x71e41e,(WORK+0x4000,sector,WORK+0x3000,profile),54)
                native=_native(a,'af_color406_matrix',raw,_half(DIAGONAL))
                if actual!=_half(want) or native!=actual:raise ValueError('原矩阵完整构造/独立/AArch64不一致')
                matrix_cases.append(dict(profile=profile,requested_sector=sector,source=origin,sha256=hashlib.sha256(actual).hexdigest()))
        finally:m.cpu=None
    for profile,sector,override in ((0,16,None),(54,16,None),(58,7,None),(0xffffffff,7,None),
                                  *((1,sector,bank) for bank in (52,53,54,55,255) for sector in (0,15))):
        m,matrix,style=setup(cp)
        try:
            if override is not None:
                changed=bytearray(matrix);changed[0x196+profile]=override;matrix=bytes(changed);m.put(MATRIX,matrix)
            raw,origin=_matrix_source(m,profile,sector,matrix)
            actual,_=_original(m,0x71e41e,(WORK+0x4000,sector,WORK+0x3000,profile),54)
            if _native(a,'af_color406_matrix',raw,_half(DIAGONAL))!=actual:raise ValueError('原矩阵回退/统一银行构造不符')
            matrix_cases.append(dict(profile=profile,requested_sector=sector,property_override=override,source=origin,sha256=hashlib.sha256(actual).hexdigest()))
        finally:m.cpu=None
    profiles=tuple(range(60))+(0xffffffff,)
    for profile,adjusted,override in [(p,True,None) for p in profiles]+[(p,False,None) for p in (0,53,54,57)]+[(1,True,255)]:
        m,matrix,style=setup(cp,adjust=adjusted)
        try:
            if override is not None:
                changed=bytearray(style);changed[0x1200+profile]=override;style=bytes(changed);m.put(STYLE,style)
            raw,origin=_cc1_source(cp,profile,style);delta=ADJUST if adjusted else (0,)*8
            actual,state=_original(m,0x71e670,(WORK+0x5000,profile,WORK+0x3000),48)
            if raw is None:
                if actual!=b'\xa5'*48:raise ValueError('原CC1抑制路径写入了输出')
            else:
                values=struct.unpack('<24H',raw);want=[values[i%8]+delta[i%8]+(values[i] if i>=8 else 0) for i in range(24)]
                if actual!=_half(want) or _native(a,'af_color406_primary',raw,_half(delta))!=actual:
                    raise ValueError('原CC1完整构造/差分/全局修正不符')
            primary_cases.append(dict(profile=profile,global_adjust=adjusted,property_override=override,source=origin,written=raw is not None,
                native_complete=state['status']=='RETURNED',sha256=hashlib.sha256(actual).hexdigest()))
            for mode in (0,1):
                actual,state=_original(m,0x71e9c8,(WORK+0x6000,profile,mode,WORK+0x3000),32,True)
                supported=profile<52 or profile==53
                if not supported:
                    if state['status']!='STOPPED_BEFORE_BOUNDARY' or actual!=b'\xa5'*32:
                        raise ValueError('原CC1不支持第二域未停在诊断边界')
                else:
                    if state['status']!='RETURNED' or raw is None:raise ValueError('原CC1合法第二域未完整返回')
                    metadata=style[0xf00+mode*16:0xf10+mode*16]
                    want=_half([v+d for v,d in zip(struct.unpack('<8H',raw[:16]),delta)])+metadata
                    if actual!=want or _native(a,'af_color406_secondary',raw[:16],_half(delta),metadata)!=actual:
                        raise ValueError('原第二域参数/元数据不符')
                secondary_cases.append(dict(profile=profile,mode=mode,global_adjust=adjusted,property_override=override,supported=supported,
                    status=state['status'],diagnostic=state.get('boundary'),sha256=hashlib.sha256(actual).hexdigest()))
        finally:m.cpu=None
    for profile,mode in ((0,2),(53,0xffffffff)):
        m,_,_=setup(cp)
        try:
            actual,state=_original(m,0x71e9c8,(WORK+0x6000,profile,mode,WORK+0x3000),32,True)
            if (state['status']!='STOPPED_BEFORE_BOUNDARY' or state['boundary']['registers']['r0']!='0x258' or
                actual!=b'\xa5'*32):raise ValueError('原CC1非法第二域模式没有保留诊断/输出')
            secondary_cases.append(dict(profile=profile,mode=mode,invalid_mode=True,supported=False,
                status=state['status'],diagnostic=state['boundary'],sha256=hashlib.sha256(actual).hexdigest()))
        finally:m.cpu=None
    for marker in range(249,255):
        for flag in (0,1,2):
            m,matrix,style=setup(cp,marker,flag)
            try:
                enabled=flag<=1;payload=m.read(DESTINATION+(marker-249)*108,108);deltas=payload[6:60]
                for sector in (0,7,15):
                    raw,_=_matrix_source(m,0,sector,matrix)
                    baseline=_native(a,'af_color406_matrix',raw,_half(DIAGONAL))
                    expected=_add(a,baseline,deltas) if enabled else baseline
                    actual,_=_original(m,0x71e41e,(WORK+0x4000,sector,WORK+0x3000,0),54)
                    if actual!=expected:raise ValueError('旧六款完整矩阵增量不符')
                raw,_=_cc1_source(cp,0,style);base=_native(a,'af_color406_primary',raw,_half(ADJUST))
                expected=_add(a,base,payload[60:108]) if enabled else base
                actual,_=_original(m,0x71e670,(WORK+0x5000,0,WORK+0x3000),48)
                if actual!=expected:raise ValueError('旧六款完整CC1增量不符')
                for mode in (0,1):
                    metadata=style[0xf00+mode*16:0xf10+mode*16]
                    base=_native(a,'af_color406_secondary',raw[:16],_half(ADJUST),metadata)
                    expected=(_add(a,base[:16],payload[60:76])+metadata) if enabled else base
                    actual,_=_original(m,0x71e9c8,(WORK+0x6000,0,mode,WORK+0x3000),32)
                    if actual!=expected:raise ValueError('旧六款第二域误改元数据或增量不符')
                legacy.append(dict(marker=marker,source_flag=flag,increment_applied=enabled,
                    matrix_sectors=3,primary=1,secondary_modes=2,bounds_preserved=True))
            finally:m.cpu=None
    for profile,marker in [(p,0) for p in (0,3,54,55)]+[(0,m) for m in range(249,255)]:
        for parameter in (100,300,500,700,900,1000):
            for mix in (0,128,256):
                actual,endpoints,weights=_blend_original(cp,profile,marker,parameter,mix)
                a.cpu.mem_write(WORK+0x1000,endpoints);a.cpu.mem_write(WORK+0x2000,_half(weights))
                a.cpu.mem_write(WORK+0x3000-16,b'\xa5'*48)
                if a.call('af_color406_blend',WORK+0x1000,WORK+0x2000,WORK+0x3000):raise ValueError('新CC1插值拒绝原有效权重')
                if (bytes(a.cpu.mem_read(WORK+0x3000,16))!=actual or bytes(a.cpu.mem_read(WORK+0x1000,48))!=endpoints or
                    bytes(a.cpu.mem_read(WORK+0x2000,8))!=_half(weights) or
                    bytes(a.cpu.mem_read(WORK+0x3000-16,16))!=b'\xa5'*16 or bytes(a.cpu.mem_read(WORK+0x3010,16))!=b'\xa5'*16):
                    raise ValueError('原CC1实际消费与AArch64插值不一致或破坏边界')
                blend_cases.append(dict(profile=profile,marker=marker,numeric_parameter=parameter,
                    weights=list(weights),sha256=hashlib.sha256(actual).hexdigest(),native_complete=True,bounds_preserved=True))
    matrix,style=fixtures()
    return dict(status='OFFLINE_NATIVE_COLOR_PARAMETERS_VERIFIED',cp_sha256=CP_SHA,target_checks=checks,
        original_matrix='0x71e41e',original_primary='0x71e670',original_secondary='0x71e9c8',
        matrix_cases=matrix_cases,primary_cases=primary_cases,secondary_cases=secondary_cases,legacy_cases=legacy,blend_cases=blend_cases,
        fixture_properties=dict(matrix_sha256=hashlib.sha256(matrix).hexdigest(),style_sha256=hashlib.sha256(style).hexdigest()),
        diagonal=list(DIAGONAL),global_adjust=list(ADJUST),
        diagnostic_boundary='0x722396',original_blend='0x71b8a0',complete_color_pixel_model=False,actual_runtime_properties=False,
        actual_startup_copy_verified=False,hardware_upload_verified=False,camera_io=False,input_modified=False,
        fixture_boundaries=['synthetic runtime matrix/style properties and calibration diagonals',
            'original shadow payload explicitly copied, not boot copy execution',
            'global adjustment flag and fallback bytes, dynamic calibration branch not exercised',
            'regular two-stage CC1 interpolation; synthetic thresholds, not a measured color-temperature/exposure model',
            'no interception of original constructor/helper functions; unsupported secondary stops at original diagnostic',
            'numeric profiles not bound to actual EVF/JPG stream identities'])
