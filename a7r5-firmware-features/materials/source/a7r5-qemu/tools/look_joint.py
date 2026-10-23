"""最新六款联合参数的A7R5离线适配；不含相机或SD入口。"""
import base64
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

from look_materials import regular, sha
from look_matrix_embed import BASE, branch
from runtime_manifest import LAB

SOURCE_SHA='31f21cce9da148998c065ecf9d927e353d70a24ff245f2842cfa05cc21ce2c3b'
TARGET_SHA='18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
SPEC_SHA='9b48e4a2fe2b5bfff1280fbcc52c5795f9a3826c32b1f9c6d08559dd2e13e1fb'
NAMES=('Classic Neg.','Classic Chrome','Nostalgic Neg.','Astia','GR Positive Film','GR Negative Film')
PARAMS_VA=0x1a39450
GAMMA_VA=PARAMS_VA+648
MATRIX_VA=0x1a3a000
CURVE_VAS=(0x1a39dbc,0x1a3a900)
RETIRED=(0xbef700,0xbef940)
CODE_VA=RETIRED[0]
STAGING_VA=0x11d3000
PAYLOAD_END=CURVE_VAS[-1]+576
PAYLOAD_BYTES=PAYLOAD_END-PARAMS_VA
GAMMA_FILE=0xf76968
TABLE_FILE=0x108d080+576


def fnv(raw):
    value=2166136261
    for b in raw:value=((value^b)*16777619)&0xffffffff
    return value


def basis(document):
    if (document.get('schema'),document.get('base'),document.get('table_format')) != (
        'a7c2-creative-look/1','ST','native-5x9x9-s7-planar'):
        raise ValueError('上游外观格式不符')
    if document.get('target')!={'model':'ILCE-7CM2','firmware':'2.01'}:
        raise ValueError('来源目标不符，不把外部机型当成本机校准')
    table=base64.b64decode(document['table_base64'],validate=True)
    if len(table)!=1215 or any(not -64<=v<=63 for v in struct.unpack('1215b',table)):
        raise ValueError('色表超出原生完整七位格式')
    spec=document['native_photo']['runtime_basis']
    if spec['schema']!='a7c2-photo-q10-endpoint-uniform-matrix/1':raise ValueError('联合参数版本不符')
    tone=spec['tone_q10'];matrix=spec['matrix_planes'];chroma=spec['chroma_planes']
    if len(tone)!=3 or len(matrix)!=3 or len(chroma)!=3 or any(len(v)!=6 for v in matrix) or any(len(v)!=8 for v in chroma):
        raise ValueError('联合参数维度不符')
    values=tone+[v for row in matrix+chroma for v in row]
    if any(type(v) is not int or not -1024<=v<=1024 for v in values):raise ValueError('联合参数范围不符')
    expanded=[]
    for a,b,c,d,e,f in matrix:expanded.extend((a+b,-a,-b,-c,c+d,-d,-e,-f,e+f))
    return table,struct.pack('<54h',*(tone+expanded+[v for row in chroma for v in row])),spec


def curve(record,tone):
    """独立整数参照；不推断像素色彩空间。"""
    values=struct.unpack_from('<129I',record);top=values[-1]
    if len(record)!=576 or not 0<top<=0x3ffff:raise ValueError('曲线记录端点不符')
    result=[];gain,toe,shoulder=tone
    for y in values:
        x=(y<<12)//top;v=4096-x
        delta=(y*gain)>>10
        delta+=((((y*toe)>>10)*v)>>12)*v>>12
        delta+=((((y*shoulder)>>10)*x)>>12)*v>>12
        result.append(max(0,min(0x3ffff,y+delta)))
    if any(a>b for a,b in zip(result,result[1:])):raise ValueError('联合曲线非单调')
    out=bytearray(record);struct.pack_into('<129I',out,0,*result);struct.pack_into('<I',out,0x220,result[-1])
    return bytes(out)


def memory(files,address,size):
    """从静态载荷重建仅限本轮数据的运行地址，不猜测任意RAM。"""
    cp=files['cpapp-b.bin']
    if 'joint-layout.json' in files and PARAMS_VA<=address<=PAYLOAD_END-size:
        offset=STAGING_VA-BASE+address-PARAMS_VA
    elif BASE<=address<=BASE+len(cp)-size:offset=address-BASE
    else:raise ValueError('参数地址不在固定CP或联合数据范围')
    return cp[offset:offset+size]


def mov16(register,value,*,high=False):
    first=(0xf2c0 if high else 0xf240)|((value>>12)&15)|((value>>11)&1)<<10
    second=((value>>8)&7)<<12|register<<8|(value&255)
    return struct.pack('<HH',first,second)


def compile_asm(source,address,out,stem,extra=()):
    out=Path(out);ld=out/(stem+'.ld');elf=out/(stem+'.elf');binary=out/(stem+'.bin')
    targets=dict(native_matrix_continue=0x71e422,native_primary_continue=0x71e674,
        native_secondary_continue=0x71e9cc,native_gamma_full_continue=0xaa81ce,
        native_gamma_partial_continue=0xaa868c,native_gamma_partial_invalid=0xaa86b8,
        native_gamma_continue=0x413640,native_sound_store=0x47f62e)
    ld.write_text(''.join(f'{name} = {at:#x};\n' for name,at in targets.items())+
        f'SECTIONS {{ . = {address:#x}; .text : {{ *(.text*) }} /DISCARD/ : {{ *(.ARM.attributes*) }} }}\n')
    command=['/opt/homebrew/opt/llvm/bin/clang','--target=armv7a-none-eabi','-mthumb','-nostdlib',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-Wl,-T,'+str(ld),'-Wl,--build-id=none',
        *extra,str(source),'-o',str(elf)]
    p=subprocess.run(command,capture_output=True,text=True,timeout=30)
    (out/(stem+'-compiler.log')).write_text(p.stdout+p.stderr)
    if p.returncode:raise ValueError('联合参数指令编译失败：'+p.stderr)
    subprocess.run(['/opt/homebrew/opt/llvm/bin/llvm-objcopy','-O','binary',str(elf),str(binary)],check=True,capture_output=True)
    symbols=subprocess.check_output(['/opt/homebrew/opt/llvm/bin/llvm-nm','-n',str(elf)],text=True)
    labels={fields[2]:int(fields[0],16)&~1 for line in symbols.splitlines() if len(fields:=line.split())==3}
    return binary.read_bytes(),labels,dict(command=command,source_sha256=sha(Path(source).read_bytes()),binary_sha256=sha(binary.read_bytes()))


def build(original,documents,out):
    if len(original)!=17617008 or sha(original)!=SOURCE_SHA:raise ValueError('联合适配只接受固定最终CP前像')
    if tuple(d['name'] for d in documents)!=NAMES:raise ValueError('六款名称或顺序不符')
    prepared=[basis(d) for d in documents];output=bytearray(original);patches=[]
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    def put(at,raw,reason,expected=None):
        before=bytes(output[at:at+len(raw)])
        if expected is not None and before!=expected:raise ValueError('前像指令不符：'+hex(at))
        if any(not(at+len(raw)<=r['offset'] or r['offset']+r['bytes']<=at) for r in patches):raise ValueError('联合补丁重叠')
        output[at:at+len(raw)]=raw
        patches.append(dict(offset=at,bytes=len(raw),before=before.hex(),after=raw.hex(),reason=reason))
    payload=bytearray(PAYLOAD_BYTES)
    payload[:648]=b''.join(v[1] for v in prepared)
    gamma=bytearray(original[GAMMA_FILE:GAMMA_FILE+51*28]);relocations=[]
    for old,new in zip(RETIRED,CURVE_VAS):
        record=original[old-BASE:old-BASE+576];curve(record,(0,0,0))
        refs=[i for i in range(0,len(original)-3,4) if original[i:i+4]==struct.pack('<I',old)]
        if not refs or any(not GAMMA_FILE<=i<GAMMA_FILE+51*28 for i in refs):raise ValueError('曲线存在未覆盖的对齐指针')
        for at in refs:
            put(at,struct.pack('<I',new),'曲线搬迁，保留所有原厂引用')
            struct.pack_into('<I',gamma,at-GAMMA_FILE,new)
        payload[new-PARAMS_VA:new-PARAMS_VA+576]=record
        relocations.append(dict(before=old,after=new,pointer_offsets=refs,sha256=sha(record)))
    # 独立保留ST两个完整域，各列仍由原厂上下文选择。
    gamma.extend((gamma[:28]+gamma[280:308])*6)
    if GAMMA_VA+len(gamma)>CURVE_VAS[0]:raise ValueError('Gamma表覆盖搬迁曲线')
    payload[GAMMA_VA-PARAMS_VA:GAMMA_VA-PARAMS_VA+len(gamma)]=gamma
    old_matrix=original[0x11d4000-BASE:0x11d4000-BASE+2304]
    payload[MATRIX_VA-PARAMS_VA:MATRIX_VA-PARAMS_VA+2304]=old_matrix
    old_end=0x1197000+0x8a2448
    if PARAMS_VA<old_end or PAYLOAD_END>0x1a3b000:raise ValueError('联合数据覆盖全局变量或页表保留区')
    new_size=PAYLOAD_END-0x1197000
    root=lambda size:((0x106f000+size+0x4fff)&~0x3fff)+0x128000
    if root(new_size)!=root(0x8a2448):raise ValueError('联合数据会移动原页表或栈')
    code,labels,code_receipt=compile_asm(LAB/'source/guest/look-joint.S',CODE_VA,out,'joint',
        ['-DPARAMS_VA='+hex(PARAMS_VA),'-DGAMMA_VA='+hex(GAMMA_VA)])
    if len(code)>1152:raise ValueError('联合包装器超出两条已搬迁曲线范围')
    put(CODE_VA-BASE,code+bytes(1152-len(code)),'复用两条已搬迁曲线的已加载RX范围')
    for at,name in ((0x71e41e,'joint_matrix'),(0x71e670,'joint_primary'),(0x71e9c8,'joint_secondary'),
                    (0xaa81ca,'joint_gamma_full'),(0xaa8688,'joint_gamma_partial'),(0x41363c,'joint_gamma')):
        expected=original[at-BASE:at-BASE+4]
        if at!=0xaa8688 and expected!=bytes.fromhex('f0b503af'):raise ValueError('原厂完整函数入口不符')
        put(at-BASE,branch(at,labels[name]),'原厂函数包装：'+name,expected)
    # 保留所有原表行；六处消费者统一指向增加了12行的私有副本。
    for low,high,reg in ((0x41364a,0x413656,10),(0x413d26,0x413d2e,10),
        (0x413f3a,0x413f42,3),(0x413f88,0x413f90,3),(0x41405e,0x414066,2),(0xaa8a9a,0xaa8aa2,1)):
        put(low-BASE,mov16(reg,GAMMA_VA&65535),'Gamma表低地址',mov16(reg,0xe968))
        put(high-BASE,mov16(reg,GAMMA_VA>>16,high=True),'Gamma表高地址',mov16(reg,0x107,high=True))
    call=bytearray(branch(0x413666,labels['joint_record_primary']));call[3]|=0x40
    put(0x413666-BASE,bytes(call),'仅本包装器调用读取临时曲线',bytes.fromhex('51f82210'))
    # 回到原生type1分派，仅修改条件声音模式赋值；不新增音频文件。
    put(0x377601,b'\x0f','撤回旧type1重路由',b'\x02')
    put(0x47f622-BASE,branch(0x47f622,labels['joint_sound']),
        '仅type1对齐上游声音模式；保留R5共享分支的机械抑制',bytes.fromhex('03210028'))
    tables=[v[0] for v in prepared]
    table_blob=struct.pack('<8I',0x364c3741,0x10006,*(fnv(t) for t in tables))+b''.join(tables)
    put(TABLE_FILE,table_blob,'六款最新联合拟合色表，第四槽Astia')
    stage_start=STAGING_VA-BASE;stage_end=max(stage_start+len(payload),0x11d4900-BASE)
    stage_before=bytearray(original[stage_start:stage_end]);old_at=0x11d4000-STAGING_VA
    stage_before[old_at:old_at+2304]=bytes(2304)
    if any(stage_before):raise ValueError('新增暂存范围存在未知数据')
    put(stage_start,bytes(payload)+bytes(stage_end-stage_start-len(payload)),'等长文件尾暂存联合数据；复制后擦除')
    copier=(LAB/'source/guest/look-matrix-bootcopy.S').read_text()
    for old,new in (('0x011d4000',hex(STAGING_VA)),('0x01a3a000',hex(PARAMS_VA)),
                    ('#2304','#'+str(PAYLOAD_BYTES)),('#576','#'+str(PAYLOAD_BYTES//4)),
                    ('0xc08d9b7e',hex(fnv(payload)))):copier=copier.replace(old,new)
    boot_source=out/'joint-bootcopy.S';boot_source.write_text(copier)
    boot,_,boot_receipt=compile_asm(boot_source,0x108f40,out,'joint-bootcopy')
    if len(boot)!=124:raise ValueError('联合复制器改变引导占用范围')
    put(0x108f40-BASE,boot,'保留同一124字节复制器，扩大受校验数据范围')
    put(0x2014c,struct.pack('<I',new_size),'只增加BSS末尾映射，原变量/页表/栈不变')
    result=bytes(output);inverse=bytearray(result)
    for row in patches:inverse[row['offset']:row['offset']+row['bytes']]=bytes.fromhex(row['before'])
    if bytes(inverse)!=original:raise ValueError('联合修改不能精确反向还原')
    report=dict(schema=1,source_sha256=sha(original),target_sha256=sha(result),bytes=len(result),patches=patches,
        names=list(NAMES),basis=[v[2] for v in prepared],labels=labels,code=code_receipt,bootcopy=boot_receipt,
        payload_VA=PARAMS_VA,payload_source_VA=STAGING_VA,payload_bytes=PAYLOAD_BYTES,payload_sha256=sha(payload),
        gamma_table_VA=GAMMA_VA,original_gamma_rows=51,total_gamma_rows=63,curve_relocations=relocations,code_bytes=len(code),
        old_BSS_end=old_end,new_BSS_end=PAYLOAD_END,page_table_root=root(new_size),
        page_table_root_unchanged=True,stack_unchanged=True,initialized_data_descriptor_unchanged=True,
        source_CreativeLook_response_model='upstream A7C II fit; A7R5 physical color unverified',
        full_CP_boot_verified=False,device_sound_verified=False,device_deployment_ready=False)
    (out/'joint-layout.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return result,report


def prepare(folder,documents):
    from look_materials import load
    files,receipt=load(folder)
    if receipt['schema']!=6:raise ValueError('联合适配仅从封存整合候选派生')
    target=Path(tempfile.mkdtemp(prefix='look-materials-joint-',dir=LAB/'build'))
    cp,report=build(files['cpapp-b.bin'],documents,target)
    files['cp-joint-source.bin']=files['cpapp-b.bin'];files['cpapp-b.bin']=cp
    spec=json.loads(files['six-looks.json'])
    for i,doc in enumerate(documents):
        table,_,_=basis(doc);files[f'slot{i+1}.raw-s8.bin']=table
        spec['slots'][i]=dict(slot=i+1,name=doc['name'],required_base='ST',table=f'slot{i+1}.raw-s8.bin',
            table_bytes=1215,table_sha256=sha(table),
            upstream_profile_canonical_sha256=sha((json.dumps(doc,sort_keys=True)+'\n').encode()),
            upstream_method=doc['method'],attribution=doc['attribution'],
            upstream_fit_validation=doc['validation'],
            native_photo_basis=doc['native_photo']['runtime_basis'],source_target=doc['target'],
            target_color_calibrated_on_A7R5=False)
    spec['program_base']='4.00-derived offline joint-parameter candidate'
    spec['joint_parameters']=True
    files['six-looks.json']=(json.dumps(spec,ensure_ascii=False,indent=2)+'\n').encode()
    files['joint-layout.json']=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()
    for name,raw in files.items():(target/name).write_bytes(raw)
    receipt.update(schema=7,names=list(NAMES),files={n:dict(bytes=len(r),sha256=sha(r)) for n,r in files.items()},
        device_deployment_ready=False,CP_scope='six joint parameter candidates and selector sound; no device acceptance')
    (target/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    return target
