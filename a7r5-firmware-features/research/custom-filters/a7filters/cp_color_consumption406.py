"""完整16扇区矩阵与动态CC1校准的隔离消费；不提供像素/真实运行后端。"""
import hashlib
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import WORK,STACK
from .cp_color406 import setup,MATRIX,ADJUST,DIAGONAL,_half,_original,_native,_matrix_source,_cc1_source

ROOT,PIPE,COLOR=WORK+0x3000,WORK+0x8000,WORK+0xa000
DYNAMIC=WORK+0xc000
CALIBRATION_BYTES=bytes((128,255,0,127,128,255,0,127))


def _call(a,name,source,weights,size):
    a.cpu.mem_write(WORK+0x1000,source)
    a.cpu.mem_write(WORK+0x2000,weights)
    a.cpu.mem_write(WORK+0x3000-16,b'\xa5'*(size+32))
    args=(WORK+0x1000,WORK+0x2000,WORK+0x3000) if weights else (WORK+0x1000,WORK+0x3000)
    if a.call(name,*args):raise ValueError('新颜色消费拒绝已声明有效输入')
    if (bytes(a.cpu.mem_read(WORK+0x1000,len(source)))!=source or
        bytes(a.cpu.mem_read(WORK+0x2000,len(weights)))!=weights or
        bytes(a.cpu.mem_read(WORK+0x3000-16,16))!=b'\xa5'*16 or
        bytes(a.cpu.mem_read(WORK+0x3000+size,16))!=b'\xa5'*16):
        raise ValueError('新颜色消费改变了源输入或输出保护区')
    return bytes(a.cpu.mem_read(WORK+0x3000,size))


def _matrix_setup(cp,profile,weights,marker=0,flag=1,extreme=False,header=None):
    m,prop,style=setup(cp,marker,flag)
    try:
        prop=bytearray(prop)
        struct.pack_into('<16H',prop,0x100,*[i*64 for i in range(16)])
        if extreme:
            for e in range(3):
                for sector in range(16):
                    struct.pack_into('<6H',prop,0x1e0+e*192+sector*12,
                        *[(e*24113+sector*197+j*12539)&65535 for j in range(6)])
        prop=bytes(prop);m.put(MATRIX,prop)
        for offset,address in ((8,DYNAMIC),(12,WORK+0xf000)):m.word(ROOT+offset,address)
        for offset,address in ((0,WORK+0x9000),(4,WORK+0xb000),(8,COLOR),(12,WORK+0xe000),(28,WORK+0xd000)):
            m.word(PIPE+offset,address)
        m.word(WORK+0x9000,WORK+0x1000)
        m.put(COLOR-16,b'\xa5'*(0x400+32));m.put(COLOR,b'\0'*0x400)
        m.put(COLOR+1,bytes([profile if header is None else header]));m.word(COLOR+12,0x40004000)
        m.put(WORK+0x2025,bytes([profile]))
        main,secondary1,secondary2,mix=weights
        m.put(WORK+0x2076,_half((main,256-secondary1-secondary2,secondary2,secondary1,mix)))
        return m,prop,style
    except Exception:
        m.cpu=None
        raise


def _matrix_run(m):
    result=m.run(0x71d37c,arguments=(ROOT,PIPE),limit=1000000,stop_before=(0x722396,0xb0de92))
    if result['status']!='RETURNED':raise ValueError('完整原矩阵消费到达未支持的诊断边界')
    allowed=((COLOR+0x10,COLOR+0x18),(COLOR+0x5c,COLOR+0x1e4),
             (WORK+0x10c2,WORK+0x10d4),(STACK,STACK+0x10000))
    for write in m.writes:
        at=int(write['address'],16)
        if not any(first<=at<at+write['bytes']<=last for first,last in allowed):
            raise ValueError('原矩阵消费写入了未声明区域：'+str(write))
    if m.read(COLOR-16,16)!=b'\xa5'*16 or m.read(COLOR+0x400,16)!=b'\xa5'*16:
        raise ValueError('原矩阵消费破坏上下文保护区')
    output=m.read(COLOR+0x5c,16*18)
    if m.read(WORK+0x10c2,18)!=output[:18]:raise ValueError('原矩阵首扇区状态副本不符')
    return output


def _matrix_expected(m,profile,sector,prop,marker,flag,weights):
    raw,_=_matrix_source(m,profile,sector,prop);values=struct.unpack('<18H',raw);endpoints=[]
    def signed(value):return (value+32768)%65536-32768
    for offset in range(0,18,6):
        a,b,c,d,e,f=values[offset:offset+6]
        endpoints.extend(map(signed,(DIAGONAL[0]+a+b,-a,-b,-c,DIAGONAL[1]+c+d,-d,-e,-f,DIAGONAL[2]+e+f)))
    if 249<=marker<=254 and flag<=1:
        delta=struct.unpack('<27h',m.read(0x1a39450+(marker-249)*108+6,54))
        endpoints=[signed(x+d) for x,d in zip(endpoints,delta)]
    def rounded(value):return (1 if value>=0 else -1)*((abs(value)+128)//256)
    def saturated(value):return max(-32768,min(32767,value))
    main,secondary1,secondary2,mix=weights;output=[]
    for i in range(9):
        x,y,z=endpoints[i],endpoints[i+9],endpoints[i+18]
        first=saturated(x+rounded((y-x)*main))
        second=saturated(x+rounded((y-x)*secondary1+(z-x)*secondary2))
        output.append(saturated(rounded(first*(256-mix)+second*mix)))
    return _half(endpoints),_half(output)


def _calibration_cases(cp,a):
    helpers=[];constructors=[]
    for branch in (0,1,2):
        for disabled in (False,True):
            for profile in (0,3,54,55):
                m,prop,style=setup(cp,adjust=not disabled)
                try:
                    m.put(WORK+0x11e0,bytes([branch]))
                    # 只有精确动态分支可读取该指针；其它门控设置不可读哨兵。
                    m.word(ROOT+8,DYNAMIC if branch==1 and not disabled else 0xdead0000)
                    m.put(DYNAMIC+0x1a,CALIBRATION_BYTES)
                    canonical=CALIBRATION_BYTES if branch==1 else bytes(v&255 for v in ADJUST)
                    wanted=(0,)*8 if disabled else tuple(v-256 if i<4 and v>=128 else v for i,v in enumerate(canonical))
                    if profile==0:
                        actual,result=_original(m,0x71e74e,(WORK+0x4000,ROOT),16)
                        if actual!=(b'\xa5'*16 if disabled else _half(wanted)) or result['status']!='RETURNED':
                            raise ValueError('原动态CC1修正门控/字节符号不符')
                        if not disabled and _call(a,'af_color406_adjust',canonical,b'',16)!=actual:
                            raise ValueError('原CC1修正与新AArch64解码不符')
                        helpers.append(dict(state_branch=branch,disabled=disabled,original_complete=True,
                            original_no_write=disabled,adjust=list(wanted),unselected_pointer_unread=branch!=1 or disabled))
                    raw,_=_cc1_source(cp,profile,style)
                    v=struct.unpack('<24H',raw)
                    expected=_half([v[i%8]+wanted[i%8]+(v[i] if i>=8 else 0) for i in range(24)])
                    actual,result=_original(m,0x71e670,(WORK+0x5000,profile,ROOT),48)
                    if result['status']!='RETURNED' or actual!=expected or _native(a,'af_color406_primary',raw,_half(wanted))!=actual:
                        raise ValueError('完整原CC1主域未按动态门控构造')
                    modes=[]
                    if profile in (0,3):
                        for mode in (0,1):
                            metadata=style[0xf00+mode*16:0xf10+mode*16]
                            actual,result=_original(m,0x71e9c8,(WORK+0x6000,profile,mode,ROOT),32)
                            if (result['status']!='RETURNED' or actual!=expected[:16]+metadata or
                                _native(a,'af_color406_secondary',raw[:16],_half(wanted),metadata)!=actual):
                                raise ValueError('完整原CC1第二域动态修正/元数据不符')
                            modes.append(mode)
                    constructors.append(dict(profile=profile,state_branch=branch,disabled=disabled,
                        primary_complete=True,secondary_modes=modes,primary_sha256=hashlib.sha256(expected).hexdigest()))
                finally:m.cpu=None
    return helpers,constructors


def _identity_cases(cp):
    cases=[];weights=(129,63,129,128)
    for wire,wanted in ((0,0),(19,54),(20,55)):
        m,_,_=_matrix_setup(cp,0,weights)
        try:
            m.put(WORK+0x1018,b'\x02');m.put(WORK+0x102e,bytes([wire]))
            # 执行原包装器的选择→CC1→矩阵前缀，网格入口前停止；不假装整函数返回。
            before_cal=m.read(WORK+0x2000,0x600)
            result=m.run(0x719ef6,arguments=(ROOT,PIPE),limit=2000000,stop_before=(0x230da8,0x722396,0xb0de92))
            selected=m.read(COLOR+1,1)[0];calibration_profile=m.read(WORK+0x2025,1)[0]
            if (result['status']!='STOPPED_BEFORE_BOUNDARY' or result['boundary']['address']!='0x230da8' or
                result['boundary']['registers']['r0']!=hex(ROOT) or result['boundary']['registers']['r1']!=hex(PIPE) or
                selected!=wanted or calibration_profile!=0 or m.read(WORK+0x2000,0x600)!=before_cal):
                raise ValueError('完整原选择器的独立profile字段边界发生变化')
            if m.read(COLOR-16,16)!=b'\xa5'*16 or m.read(COLOR+0x400,16)!=b'\xa5'*16:
                raise ValueError('原颜色前缀破坏输出保护区')
            stale=m.read(COLOR+0x5c,16*18)
            if m.read(WORK+0x10c2,18)!=stale[:18]:raise ValueError('原包装器矩阵状态副本不符')
        finally:m.cpu=None
        # 对照使用另一个显式上下文；不是宣称已找到/执行原厂上游身份生产器。
        m,_,_=_matrix_setup(cp,selected,weights)
        try:coherent=_matrix_run(m)
        finally:m.cpu=None
        different=stale!=coherent
        if different!=(wire!=0):raise ValueError('未重现双profile字段的隔离反例')
        cases.append(dict(wire=wire,selector_complete=True,header_profile=selected,calibration_profile=calibration_profile,
            wrapper_prefix='0x719ef6..before 0x230da8',prefix_status=result['status'],complete_wrapper_verified=False,
            independent_coherent_profile=selected,stale_matrix_sha256=hashlib.sha256(stale).hexdigest(),
            coherent_matrix_sha256=hashlib.sha256(coherent).hexdigest(),matrix_difference=different,
            upstream_identity_producer_verified=False,camera_bug_claimed=False))
    return cases


def collect(cp,a):
    require_source(cp,CP_SHA,'CP')
    helpers,constructors=_calibration_cases(cp,a)
    cases=[]
    weights=((0,0,0,0),(256,256,0,256),(128,0,256,256),(129,63,129,128),(1,1,254,1),(255,127,128,255))
    plans=[(p,w,0,1,False) for p in (0,3,5,15,18,54,55,56,57) for w in weights]
    plans += [(0,weights[3],marker,flag,False) for marker in range(249,255) for flag in (1,2)]
    plans += [(0,w,0,1,True) for w in weights]
    for profile,w,marker,flag,extreme in plans:
        m,prop,style=_matrix_setup(cp,profile,w,marker,flag,extreme)
        try:
            before_prop=m.read(MATRIX,len(prop));before_cal=m.read(WORK+0x2000,0x600)
            actual=_matrix_run(m);expected=b''
            for sector in range(16):
                endpoints,want=_matrix_expected(m,profile,sector,prop,marker,flag,w)
                native=_call(a,'af_color406_matrix_blend',endpoints,_half(w),18)
                if native!=want or actual[sector*18:sector*18+18]!=want:
                    raise ValueError('完整原16扇区矩阵/独立整数/AArch64不符：'+str((profile,sector,w,marker,flag,extreme)))
                expected+=want
            if m.read(MATRIX,len(prop))!=before_prop or m.read(WORK+0x2000,0x600)!=before_cal:
                raise ValueError('原矩阵消费者改变了运行属性/校准源')
            cases.append(dict(profile=profile,weights=list(w),marker=marker,source_flag=flag,extreme_property=extreme,
                sectors=16,original_complete=True,state_copy_equal=True,bounds_preserved=True,source_unchanged=True,
                sha256=hashlib.sha256(expected).hexdigest()))
        finally:m.cpu=None
    return dict(status='OFFLINE_NATIVE_COLOR_CONSUMPTION_VERIFIED',cp_sha256=CP_SHA,
        original_matrix_consumer='0x71d37c',original_adjust='0x71e74e',dynamic_pointer_accessor='0x73e654',
        calibration_helpers=helpers,calibration_constructors=constructors,matrix_consumption=cases,
        identity_cases=_identity_cases(cp),original_wrapper='0x719ef6',
        original_wrapper_sequence=['0x232fe0','0x231eb8','0x71d37c','0x230da8','0x71a05e','0x71f674'],
        complete_color_pixel_model=False,actual_runtime_properties=False,upstream_identity_producer_verified=False,
        hardware_upload_verified=False,actual_evfjpg_binding=False,camera_io=False,input_modified=False,
        fixture_boundaries=['explicit dynamic/global bytes and synthetic runtime matrix/style properties',
            'declared matrix weights, temporal smoothing and optional matrix transforms disabled',
            'normal matrix profiles only; special profiles 16/17/36/37 and monochrome 53 excluded',
            'original selector/CC1/matrix prefix stops before grid; complete wrapper and upstream identity producer not verified',
            'identity counterexample is an incomplete anonymous context, not a demonstrated camera defect',
            'parameter consumption is not hardware pixel processing or sRGB conversion'])
