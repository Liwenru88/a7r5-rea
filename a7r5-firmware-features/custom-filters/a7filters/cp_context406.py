"""从原运行期生产器建立颜色上下文；不提供ISP或物理查询后端。"""
import hashlib
import struct

from .access_evidence import CP_SHA, require_source
from .cp_machine import WORK, STACK, STOP
from .cp_color406 import setup, MATRIX, _matrix_source

INPUT, CONTEXT = WORK+0x4000, 0x1214e98
BANKS = (0x1efb7d0, 0x1efd1a8)
FACTORY = (0,3,2,1,16,15,17,18,5,13,19,20)
ENTRIES = (0x240d34,0x232fe0,0x231eb8,0x71d37c,0x230da8,0x71a05e,0x71f674)


def layout(machine, root, aggregate, bank):
    """身份相等不足以替代原内存别名；拒绝被拆散的上下文。"""
    if bank not in BANKS:
        raise ValueError('不是原颜色双缓冲银行')
    pipe=aggregate+0x50
    expected={root+4:bank+0x624,pipe+8:bank+0x648,
              pipe+12:0x1ef5ef4,pipe+16:bank+0xbd0,
              pipe+20:0x1ef7900,pipe+24:0x1efeb88,pipe+28:0x1eff4d8}
    if any(machine.word(at)!=value for at,value in expected.items()):
        raise ValueError('原颜色上下文别名或所属对象被拆散')
    if machine.word(pipe)!=machine.word(root)+0x38c:
        raise ValueError('原颜色上下文的原始状态间接引用不符')
    if machine.word(machine.word(pipe))!=bank+0xe3c:
        raise ValueError('原状态生产器没有构造颜色原始银行引用')
    return pipe


def _call(machine, entry, args, stack, *, stop_before=()):
    # 原描述符仍在父函数的活动栈帧中。不能重置到栈顶覆盖它们。
    machine.register('sp',stack)
    machine.register('lr',STOP|1)
    result=machine.run(entry,arguments=args,preserve_state=True,returned=False,
                       limit=2000000,stop_before=stop_before)
    if result['status']=='WINDOW_EXECUTED':
        if machine.register('sp')!=stack:
            raise ValueError('原颜色函数返回时破坏了父栈帧')
        result=dict(result,status='RETURNED')
    return result


def _prepare(cp,wire,values,bank):
    machine,_,_=setup(cp)
    try:
        machine.enable_initialized_data(0x1193000,0x1000)
        machine.map_ram(WORK+0x10000,0x2000)
        for address,size in ((0x1ef5000,0xc000),(0x1915000,0x2000),(0x1214000,0x2000),
                             (0x198c000,0x2000),(0x1950000,0x1000),(0x19d1000,0x1000),
                             (0x18bf000,0x1000),(0x1721000,0x1000),(0x1571000,0x2000)):
            machine.map_ram(address,size)
        # 来源均显式：原C4构造读取这些输入引用，不为NULL映射零页。
        # 这是有限的运行属性/帧元数据夹具，不是相机校准捕获。
        machine.word(INPUT+0x4b2c,WORK+0x1000)
        machine.word(INPUT+0x4b40,WORK+0x2000)
        machine.word(INPUT+0x4b34,WORK+0x10000)
        machine.put(WORK+0x1016,struct.pack('<H',0x3011))
        machine.word(0x16afd04,WORK+0x3000)
        machine.put(MATRIX+0x100,struct.pack('<16H',*[i*64 for i in range(16)]))
        machine.put(INPUT+10,struct.pack('<H',0x403))
        machine.word(INPUT+0x1d4,2)
        machine.word(INPUT+0xa40,wire)
        from .investigate import PARAMETERS
        for item,value in zip(PARAMETERS,values):
            machine.put(INPUT+item[7],bytes([value&255]))
        # 同一源银行作为上一帧；只声明原选择位，不假造成像完成事件。
        machine.put(0x198d5ca,bytes([1-BANKS.index(bank)]))
        machine.run(0xafd2da,arguments=(INPUT,CONTEXT))
        return machine
    except Exception:
        machine.cpu=None
        raise


def _expected_matrix(machine,cp,profile,weights,properties,diagonal):
    def signed(v):return (v+32768)%65536-32768
    def rounded(v):return (1 if v>=0 else -1)*((abs(v)+128)//256)
    def saturated(v):return max(-32768,min(32767,v))
    result=[]
    for sector in range(16):
        raw,_=_matrix_source(machine,profile,sector,properties)
        endpoints=[]
        for start in (0,6,12):
            a,b,c,d,e,f=struct.unpack('<18H',raw)[start:start+6]
            endpoints.extend(map(signed,(diagonal[0]+a+b,-a,-b,-c,
                diagonal[1]+c+d,-d,-e,-f,diagonal[2]+e+f)))
        for i in range(9):
            a,b,c=endpoints[i],endpoints[i+9],endpoints[i+18]
            main=saturated(a+rounded((b-a)*weights[0]))
            second=saturated(a+rounded((b-a)*weights[3]+(c-a)*weights[2]))
            result.append(saturated(rounded(main*(256-weights[4])+second*weights[4])))
    return struct.pack('<144h',*result)


def execute(cp,wire,values=(0,0,0,0,0,0,1,0),bank=BANKS[1]):
    require_source(cp,CP_SHA,'CP')
    if wire not in FACTORY or len(values)!=8 or bank not in BANKS:
        raise ValueError('原上下文研究输入不在已声明的范围')
    limits=((-9,9),(-9,9),(-9,9),(0,9),(-9,9),(0,9),(1,5),(0,9))
    if any(not low<=v<=high for v,(low,high) in zip(values,limits)):
        raise ValueError('原上下文研究八项参数越界')
    machine=_prepare(cp,wire,values,bank)
    from unicorn import UC_HOOK_CODE
    trace=[]
    captures={}
    queries=[]
    def observe(cpu,at,size,data):
        if captures.get('query_return')==at:
            queries[-1]['result']=machine.register('r0')
            captures.pop('query_return')
        if at==0x415160:
            obj=machine.register('r0')
            index=2 if obj and machine.read(obj+0x660,1)!=b'\0' else 0
            record=machine.word(obj+0x184+index*8) if obj else 0
            queries.append(dict(object=hex(obj),record=hex(record),diagnostic=machine.register('r1')))
            captures['query_return']=machine.register('lr')&~1
        if at in ENTRIES:
            trace.append(hex(at))
        if at==0x71d37c:
            color=machine.word(captures['pipe']+8)
            captures['weights_before_matrix']=machine.read(color+0x52,10)
        if len(trace)>128:
            raise ValueError('原颜色调用轨迹超出预算')
    handle=machine.cpu.hook_add(UC_HOOK_CODE,observe)
    try:
        produced=machine.run(0x23091c,arguments=(CONTEXT,bank),limit=2000000,
            stop_before=(0x73edc8,0xb0de92,0x4eacd8))
        if produced.get('boundary',{}).get('address')!='0x73edc8':
            raise ValueError('原运行期状态生产器未完整返回：'+str(produced))
        root,aggregate=machine.register('r0'),machine.register('r1')
        stack=machine.register('sp')
        pipe=layout(machine,root,aggregate,bank)
        captures['pipe']=pipe
        state,cal,color=machine.word(root),machine.word(root+4),machine.word(pipe+8)
        if machine.read(state+0x2e,1)!=bytes([wire]):
            raise ValueError('原状态生产器没有消费同一输入基底')
        root_before=machine.read(root,32)
        init=_call(machine,0x719f2e,(root,pipe),stack,stop_before=(0xb0de92,0x4eacd8))
        if init['status']!='RETURNED' or machine.read(machine.word(pipe+16)+11,1)!=b'\x03':
            raise ValueError('原颜色初始化未完成网格状态初始化')
        if machine.word(color+0x184) or machine.word(color+0x20):
            raise ValueError('纯参数原初始化意外保留网格源/输出引用')
        result=_call(machine,0x719ef6,(root,pipe),stack,
                     stop_before=(0xb0de92,0x722396,0x4eacd8,0x414f44))
        if result['status']!='RETURNED':
            raise ValueError('完整原颜色应用未返回：'+str(result))
        if layout(machine,root,aggregate,bank)!=pipe or machine.read(root,32)!=root_before:
            raise ValueError('完整原颜色应用改变了上游指针关系')
        if trace!=list(map(hex,ENTRIES)):
            raise ValueError('完整原生产器/选择/CC1/矩阵/网格/后处理轨迹不符')
        profile=machine.read(color+1,1)[0]
        weights=machine.read(cal+0x76,10)
        if captures['weights_before_matrix']!=weights:
            raise ValueError('矩阵消费改变了CC1生产的同一权重')
        if not queries or any(q['record']!='0x0' or q.get('result')!=4 for q in queries):
            raise ValueError('原缺记录查询未保留返回4或意外获得了未声明句柄')
        if machine.word(color+0x20):
            raise ValueError('缺原查询记录时意外发布了网格输出引用')
        # 特殊/单色矩阵另有原分支；这里只为常规ST/PT和内嵌FL2/FL3作独立数值对照。
        actual=machine.read(color+0x5c,288)
        checked=profile not in (16,17,36,37,53)
        if checked:
            expected=_expected_matrix(machine,cp,profile,struct.unpack('<5H',weights),
                machine.read(MATRIX,0x7000),struct.unpack('<3H',machine.read(cal+0x1a0,6)))
            if actual!=expected:
                raise ValueError('同一原上下文的完整矩阵与独立整数期待不符')
        from .cp_gamma_source406 import execute_from_context
        gamma=execute_from_context(machine,CONTEXT)
        if gamma['source_wire']!=wire or gamma['source']!=hex(INPUT):
            raise ValueError('原颜色与Gamma不是同一个C4源基底')
        return dict(wire=wire,values=list(values),bank=hex(bank),profile=profile,
            original_producer='0x23091c → 0x240d34 → before 0x73edc8',
            original_producer_complete=True,complete_color_wrapper_returned=True,
            calls=trace,profile_address=hex(color+1),calibration_profile_address=hex(cal+0x25),
            profiles_share_one_byte=True,cc1_matrix_weights_share_bytes=True,
            weights=list(struct.unpack('<5H',weights)),matrix_independently_checked=checked,
            matrix_sha256=hashlib.sha256(actual).hexdigest(),
            stage=hex(machine.word(pipe+16)),stage_owner='original selected bank',
            queries=queries,
            native_grid_source_cache=hex(machine.word(color+0x184)),
            gamma=gamma,same_c4_source_verified=True,
            dynamic_grid_published=False,original_root_unchanged=True,
            source_calibration_captured=False,actual_evf_jpg_binding=False,
            actual_isp_pixels=False,frame_release_verified=False)
    finally:
        machine.cpu.hook_del(handle)
        machine.cpu=None


def collect(cp):
    require_source(cp,CP_SHA,'CP')
    cases=[execute(cp,wire,values,bank) for wire in FACTORY
           for values in ((0,0,0,0,0,0,1,0),(-3,4,-5,2,6,7,3,8))
           for bank in BANKS]
    return dict(schema='a7r5-native-color-context406/1',
        status='OFFLINE_ORIGINAL_CONTEXT_AND_COLOR_WRAPPER_VERIFIED',cp_sha256=CP_SHA,cases=cases,
        original_bank_payload_offset=0x2c0,calibration_offset=0x364,color_offset=0x388,
        profile_alias='color+1 == calibration+0x25',
        weight_alias='color+0x52..5a == calibration+0x76..7e',
        historical_split_fixture_is_real_layout=False,
        fixture_boundaries=['synthetic current-CP runtime matrix/style and hue properties',
            'bounded explicit C4 source calibration references and runtime property storage',
            'input operation code 0x403, photo-look mode 2, feature flags zero',
            'original producer returns before dispatch; color initialization and full wrapper called separately in live parent stack',
            'original processing object has no query record; native return 4 retained; no driver, ISP, DMA or frame-completion backend'],
        gamma_same_source_verified=True,actual_runtime_calibration=False,
        actual_evf_jpg_binding=False,frame_release_verified=False,camera_io=False,input_modified=False)
