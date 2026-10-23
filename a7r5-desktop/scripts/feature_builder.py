"""精确4.00前像上的功能组合；共享布局保留，未选功能的入口恢复原厂。"""
import json
from pathlib import Path
import struct

import importlib.util

PROJECT = Path(__file__).resolve().parents[2]


def isolated_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MATERIALS=PROJECT/'a7r5-firmware-features/materials'
KEYS=('fl23','looks','ntsc','sound')
LABELS={'fl23':'启用 FL2 / FL3','looks':'六款自定义滤镜','ntsc':'关闭 NTSC 提示','sound':'电子快门声音'}
BASE=0x108000
AP='components/usr/lib/appFw.so'
CP='components/cpapp-b.bin'
CP_FL=[(0x12b8ca,96),(0x12be0e,96),(0x61643e,6),(0x61668c,6),(0x6166bc,4),
    *[(a,4) for a in (0x13c460,0x13c4fc,0x13ca62,0x13cc24,0x13cdb4,0x13cf44,
                      0x13d0d4,0x13d23c,0x13d35a,0x13d43a,0x13d4dc)],
    *[(a,2) for a in (0x9a0442,0x9a0466,0x9a0488,0x9a05f6,0x9a0a68)]]
CP_LOOKS=[(0x128ee0,48),(0x128f62,4),(0x1292f0,4),(0x9a020e,6),(0x9a0320,16),
    (0x9a06a6,10),*[(a,4) for a in (0x61641e,0x616670,0x6169c8,0x9a01ca,0x9a0688,0x30b63c,0x30b666)]]


def selection(values):
    if not isinstance(values,dict) or set(values)!=set(KEYS) or any(type(v) is not bool for v in values.values()):
        raise ValueError('功能选择必须包含四个明确的布尔开关')
    return values


def assembler():
    path=MATERIALS/'source/analysis/custom-features-20261021-03/research-materials-v3/code/assembler.py'
    return isolated_module(path,'client_feature_assembler').assemble


def recipe():
    return json.loads((MATERIALS/'recipes.json').read_text())


def build_ap(original,options):
    options=selection(options);rec=recipe();engine=isolated_module(MATERIALS/'reproduce.py','client_reproduce')
    integrated=engine.patch(original,rec['integrated'][0]);result=bytearray(original)
    # 每一处修改都有原配方来源；共享转换器和默认表按选择重建。
    for row in rec['integrated'][0]['patches']:
        at=row['offset'];raw=bytes.fromhex(row['after']);owner=None
        if at in (0x20c99a4,0x20c9ea4):owner='ntsc'
        elif at in (0x3f4a5cc,0x3f4a64c,0x4a249ba,0x4a25b99):owner='fl23'
        elif at in (0x60,0x1bc78a8,0x500fbc0) or 0x3f4a888<=at<=0x3f4ab08:owner='looks'
        if owner and options[owner]:result[at:at+len(raw)]=raw
    if options['fl23'] or options['looks']:
        # 两项均开启时精确复用最终选择代码；其余组合保留同一诊断尾部。
        if options['fl23'] and options['looks']:
            code=integrated[0x3550354:0x35503d8]
        else:
            lines=['cmp w0,#16','b.eq special']
            if options['fl23']:lines+=['cmp w0,#17','b.eq fl2','cmp w0,#18','b.eq fl3']
            if options['looks']:lines+=['sub w3,w0,#10','cmp w3,#5','b.ls custom']
            lines += ['cmp w1,#'+('11' if options['fl23'] else '9'),'b.hi 0x35503d8',
                'adrp x0,0x4b72000','add x0,x0,#0x4d0','ldrb w0,[x0,w1,uxtw]',
                'store:','strb w0,[x2]','ret']
            if options['fl23']:lines+=['fl2:','mov w0,#19','b store','fl3:','mov w0,#20','b store']
            if options['looks']:lines+=['custom:','add w0,w3,#249','b store']
            lines+=['special:','mov w0,#-1','b store']
            code=assembler()(lines,0x3550354,'aarch64')
            if len(code)>132:raise ValueError('选择器超出原函数空间')
            code+=bytes.fromhex('1f2003d5')*((132-len(code))//4)
        result[0x3550354:0x35503d8]=code
        result[0x4b724d0:0x4b724dc]=bytes([0,3,2,1,16,15,17,18,5,13,19,20])
    for index in range(54):
        slot=index%18;at=0x4a422f8+index*8+4
        if (options['looks'] and 10<=slot<=15) or (options['fl23'] and slot in (16,17)):
            result[at:at+4]=integrated[at:at+4]
    return bytes(result)


def build_cp(original,options):
    options=selection(options);rec=recipe();engine=isolated_module(MATERIALS/'reproduce.py','client_reproduce')
    # 原始完整摘要由原配方验证，即使全不选也不接收其他前像。
    integrated=engine.patch(original,rec['integrated'][1])
    if not options['fl23'] and not options['looks']:
        if not options['sound']:return original
        # 独立声音只需原生type1条件包装器与已验证text页内空隙。
        result=bytearray(original);at=BASE+0xae7220
        code=assembler()(['movs r1,#3','cmp r0,#0','beq store','movw ip,#0x1618',
            'ldr.w ip,[r4,ip]','cmp ip,#1','it ne','movne r1,#0','store:',
            'mov.w r0,#0x5b00','b.w 0x47f62e'],at)
        if any(original[0xae7218:0xae8000]) or len(code)>64:raise ValueError('声音代码布局前像不符')
        result[0xae7220:0xae7220+len(code)]=code
        result[0x20128:0x2012c]=struct.pack('<I',0xac8000)
        result[0x377622:0x377626]=assembler()([f'b.w 0x{at:x}'],0x47f622)
        return bytes(result)
    result=bytearray(integrated)
    def restore(at,size):result[at:at+size]=original[at:at+size]
    if not options['looks']:
        for at,size in CP_LOOKS:restore(at,size)
        # 叶函数的原生读指令恢复后，FL2/FL3仍须使用扩展路由表。
        result[0x9a06a6:0x9a06aa]=assembler()(['movw r2,#0xeefc'],0xaa86a6)
        result[0x9a06ac:0x9a06b0]=assembler()(['movt r2,#0x107'],0xaa86ac)
    if not options['fl23']:
        for at,size in CP_FL:restore(at,size)
        result[0xf76efc+19*8:0xf76efc+21*8]=original[0xcc467c+19*8:0xcc467c+21*8]
    if not options['sound']:restore(0x377622,4)
    return bytes(result)

