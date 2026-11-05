"""原joint/helper规范保留区内的Capture门；只构建局部段和精确内存计划。"""
from pathlib import Path
import hashlib
import importlib.util
import struct

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features').is_dir())
BASE=0x108000
CP_SHA='18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
REGIONS=(('format',0xbef524,26),('rsource',0xbef582,6),('color',0xbef65a,6),
         ('rsource_record',0xbef678,8),('pool',0xbef69c,20),('release',0xbef6ec,20),('factor',0xbef838,400),('checker',0xbef5c0,96))
BEFORE=('659d36ca563ba4622daabb36a71dafaf6060cdcbf89bb12e75426198496d272c',
        'b0f66adc83641586656866813fd9dd0b8ebb63796075661ba45d1aa8089e1d44',
        'b0f66adc83641586656866813fd9dd0b8ebb63796075661ba45d1aa8089e1d44',
        'af5570f5a1810b7af78caf4bc70a660f0df51e42baf91d4de5b2328de0e83dfc',
        'de47c9b27eb8d300dbb5f2c353e632c393262cf06340c4fa7f1b40c4cbd36f90',
        'de47c9b27eb8d300dbb5f2c353e632c393262cf06340c4fa7f1b40c4cbd36f90',
        'd951593a570e83c7c31b32ab893175a5f76a24c0fc61b811d5d1ae6eddd44131',
        '82025b3afa761c0a9a04fc83d64ecd8b23c965499f692d59ff9be082050836b2')
TARGETS={name:'af_cp_capture406_'+name.lower()+'_target' for name in
         ('BIRTH','RESTORE','REBUILD','REVERSE','GAMMA','RELEASE','POOL','FORMAT','RSOURCE','COLOR')}
TARGETS['MATRIX9']='af_cp_components406_matrix9_shim'
CALLS={0x45bc80:'birth',0x45be6c:'birth',0x48d700:'rebuild',0x48d8b4:'rebuild',
       0x46e65a:'restore',0x335e56:'reverse',0x872682:'gamma',0x45c09a:'release',
       0xadf96c:'pool',0xadfd2c:'pool',0xae038c:'pool',0xaa7f08:'format',
       0xadd846:'rsource',0x24d32a:'color',0x24daba:'color',0x73e8dc:'color',0x73e94e:'color',
       0x73e9ba:'color',0x73ea62:'color',0x73ea68:'color',0x73ea8c:'color',
       0x73f10e:'color',0x73f174:'color',0x73f1e4:'color',0x73f278:'color',
       0x73f2e6:'color',0x73f362:'color',0x73f394:'color',0x73f3f4:'color',
       0x73f494:'color',0x73f4c6:'color',0x71d6ec:'matrix9'}
# 原尾调用不写LR，必须保持B.W；其余原BL仍保留真实返回地址。
TAIL_CALLS=frozenset((0x73e9ba,0x73ea62,0x73ea68,0x73ea8c,0x73f494))
FALLBACK={'birth':0xae0317,'restore':0x833cb5,'rebuild':0xaebdc3,'reverse':0x845cf5,
          'gamma':0x845db9,'release':0xae0361,'pool':0xae07e1,'format':0xaa81cb,
          'rsource':0x4596f5,'color':0x719ef7,'matrix9':0x71eccd}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def source():
    spec=importlib.util.spec_from_file_location('capture_cpio_reader',HERE.parent/'candidate_preflight.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    cp=module.read_cpio(ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio',
                        {'cp/cpapp-b.bin'})['cp/cpapp-b.bin']
    if len(cp)!=17617008 or sha(cp)!=CP_SHA:raise ValueError('Capture固定CP身份不符')
    return cp


def build(directory,flags,run,inspect,module_symbols,factor_symbols,cp):
    directory=Path(directory);directory.mkdir()
    for name,a,b,digest in (
        ('preserved-gamma-native.bin',0xbef8bc,0xbef8e0,'7fdfea2c1e2b69f9d43c2bea16c454875513ebc004e469202c3d9a25f26c7749'),
        ('preserved-gamma-call-cleanup.bin',0xbef9ae,0xbef9c8,'ec7b0327df95252b8f56ccd7cb51b851db2b84fd172bcb9fa0393ce1cb447b21')):
        data=cp[a-BASE:b-BASE]
        if sha(data)!=digest:raise ValueError('Capture原Gamma固定切片不符')
        (directory/name).write_bytes(data)
    constants={'PHASE_ENTRY':factor_symbols['permanent_phase']&~1,'PAYLOAD_LITERAL':factor_symbols['payload_base']}
    constants.update({name+'_TARGET':module_symbols[symbol] for name,symbol in TARGETS.items()})
    lines=[f'#define AF_CAPTURE_{name} 0x{value:x}' for name,value in constants.items()]
    lines += ['#define AF_CAPTURE_PRESERVED_NATIVE_BIN "'+str(directory/'preserved-gamma-native.bin')+'"',
              '#define AF_CAPTURE_PRESERVED_CALL_BIN "'+str(directory/'preserved-gamma-call-cleanup.bin')+'"']
    (directory/'native_capture_constants.h').write_text('\n'.join(lines)+'\n')
    objects=[]
    for name in ('capture_factor.S','capture_aux.S'):
        local=directory/name;local.write_bytes((HERE/'bootstrap'/name).read_bytes());obj=directory/(name+'.o')
        run([*flags,'-I'+str(directory),'-c',local,'-o',obj]);objects.append(obj)
    script=directory/'capture.ld'
    script.write_text('SECTIONS {\n'+''.join(f'.capture_{name} 0x{address:x} : {{ *(.text.capture_{name}) }}\n'
        for name,address,_ in sorted(REGIONS,key=lambda row:row[1]))+'/DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes*) *(.comment*) }\n}\n'+
        ''.join(f'ASSERT(SIZEOF(.capture_{name}) == {size}, "capture {name} size drift");\n'
                for name,_,size in REGIONS)+'capture_original_memcpy = 0x5f51bc;\n')
    target=directory/'capture.elf'
    run(['/opt/homebrew/bin/ld.lld','--no-undefined','--build-id=none','-T',script,*objects,'-o',target])
    elf,symbols=inspect(target.read_bytes());regions=[]
    for (name,address,size),digest in zip(REGIONS,BEFORE):
        section=elf.get_section_by_name('.capture_'+name);raw=section.data()
        if section['sh_addr']!=address or len(raw)!=size or sha(cp[address-BASE:address-BASE+size])!=digest:
            raise ValueError('Capture段地址/前像/长度不符')
        path=directory/('capture-'+name+'.bin');path.write_bytes(raw)
        regions.append(dict(name=name,address=address,bytes=size,path=str(path),sha256=sha(raw),before_sha256=digest))
    validate(cp,elf,symbols,module_symbols,factor_symbols,regions)
    return symbols,regions


def validate(cp,elf,symbols,module_symbols,factor_symbols,regions):
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    raw_by_name={}
    for row,(name,address,size),digest in zip(regions,REGIONS,BEFORE):
        raw=Path(row['path']).read_bytes();section=elf.get_section_by_name('.capture_'+name)
        if row!={**row,'name':name,'address':address,'bytes':size,'sha256':sha(raw),'before_sha256':digest} or \
           len(raw)!=size or section['sh_addr']!=address or section.data()!=raw or sha(cp[address-BASE:address-BASE+size])!=digest:
            raise ValueError('Capture真实局部段或来源漂移')
        raw_by_name[name]=raw
    if len(regions)!=8:raise ValueError('Capture必须恰为八个局部区间')
    def at(address,size):
        for name,base,length in REGIONS:
            if base<=address and address+size<=base+length:return raw_by_name[name][address-base:address-base+size]
        raise ValueError('Capture记录越出已批准局部区间')
    for kind,fallback in FALLBACK.items():
        address=symbols['permanent_capture_'+kind]&~1
        name=next(n for n,a,s in REGIONS if a<=address<a+s);base=next(a for n,a,s in REGIONS if n==name)
        raw=raw_by_name[name];code=list(decoder.disasm(raw[address-base:address-base+6],address))
        if len(code)!=3 or any(i.size!=2 for i in code) or code[0].mnemonic!='push' or code[0].op_str!='{r0, r1, r2, lr}':
            raise ValueError('Capture永久门不再为固定6B ABI')
        if code[2].mnemonic!='b' or int(code[2].op_str[1:],16)!=(factor_symbols['permanent_phase']&~1):
            raise ValueError('Capture记录读取或phase分流不符')
        if kind=='color':
            if code[1].mnemonic!='ldr' or code[1].op_str!='r0, [pc, #0x4c]' or address!=0xbef65a:
                raise ValueError('Capture颜色门字面量读取漂移')
            pointer=((code[1].address+4)&~3)+0x4c
            record=struct.unpack('<I',at(pointer,4))[0]
            if pointer!=0xbef6ac or record!=0xbef534:raise ValueError('Capture颜色门记录指针漂移')
        else:
            if code[1].mnemonic not in ('adr','addw'):raise ValueError('Capture记录ADR漂移')
            record=((code[1].address+4)&~3)+int(code[1].op_str.split('#')[1],16)
        if record&3 or struct.unpack('<2I',at(record,8))!=(module_symbols[TARGETS[kind.upper()]],fallback):
            raise ValueError('Capture实际门未配对同次C入口或原回退')
    validate_checker(cp[0xbef5c0-BASE:0xbef620-BASE],raw_by_name['checker'])
    raw=raw_by_name['factor'];base=0xbef838
    for a,b in ((0xbef838,0xbef850),(0xbef8bc,0xbef8c4),(0xbef9ae,0xbef9c4)):
        if raw[a-base:b-base]!=cp[a-BASE:b-BASE]:raise ValueError('Capture原公开入口/调用栈身份漂移')
    for at in (0xbef856,0xbef866,0xbef9b6):
        if raw[at-base:at-base+4]!=cp[at-BASE:at-BASE+4]:raise ValueError('Capture原BL/LR改变')



def validate_checker(original, candidate):
    """将两份完整CFG归一到同一寄存器操作序列；不执行目标指令。"""
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    base=0xbef5c0
    if len(original)!=96 or sha(original)!='82025b3afa761c0a9a04fc83d64ecd8b23c965499f692d59ff9be082050836b2':
        raise ValueError('checker完整96B原像漂移')
    if len(candidate)!=96 or struct.unpack_from('<5I',candidate,60)!=(0x11952c0,0x364c3741,0x10006,0x811c9dc5,0x1000193):
        raise ValueError('checker只读常量或80B边界漂移')
    def normalized(raw, code_bytes, literal):
        ins=list(decoder.disasm(raw[:code_bytes],base))
        if not ins or sum(i.size for i in ins)!=code_bytes:
            raise ValueError('checker CFG未覆盖完整代码')
        out=[];mapping={};i=0
        while i<len(ins):
            row=ins[i];mapping[row.address]=len(out)
            op,args=row.mnemonic,row.op_str
            if op=='movw':
                reg,value=args.split(', #');value=int(value,0)
                if i+1<len(ins) and ins[i+1].mnemonic=='movt' and ins[i+1].op_str.startswith(reg+', #'):
                    value|=int(ins[i+1].op_str.split('#')[1],0)<<16
                    mapping[ins[i+1].address]=len(out);i+=1
                out.append(('constant',reg,value))
            elif literal and op=='ldr' and '[pc,' in args:
                reg=args.split(',')[0];at=((row.address+4)&~3)+int(args.split('#')[1].split(']')[0],0)
                if not base+60<=at<=base+76 or at&3:raise ValueError('checker literal越界')
                out.append(('constant',reg,struct.unpack_from('<I',raw,at-base)[0]))
            elif (op,args) in (('add.w','r4, r4, #8'),('adds','r4, #8')):
                out.append(('add8','r4'))
            elif op in ('bne','beq','b'):
                out.append((op,int(args[1:],16)))
            else:out.append((op,args))
            i+=1
        for j,row in enumerate(out):
            if row[0] in ('bne','beq','b'):
                if row[1] not in mapping:raise ValueError('checker分支进入数据或新门')
                out[j]=(row[0],mapping[row[1]])
        return out,ins
    before,_=normalized(original,92,False)
    after,ins=normalized(candidate,60,True)
    if before!=after:raise ValueError('checker CFG或逐路径寄存器语义不等价')
    # ADDS后到任何条件读取前，固定循环必执行1215次；首轮SUBS覆盖全部NZCV。
    adds=next(i for i,row in enumerate(ins) if row.mnemonic=='adds')
    between=[(row.mnemonic,row.op_str) for row in ins[adds+1:]]
    expected=[('ldr.w','r4, [r4, r3, lsl #2]'),('ldr','r5, [pc, #0x2c]'),
              ('ldr','r6, [pc, #0x2c]'),('movw','r1, #0x4bf'),('ldrb','r0, [r2], #1'),
              ('eors','r5, r0'),('muls','r5, r6, r5'),('subs','r1, #1')]
    if between[:8]!=expected or not between[8][0]=='bne':
        raise ValueError('checker ADDS flags未在条件读取前被原SUBS覆盖')
    return dict(original_instructions=len(list(decoder.disasm(original[:92],base))),
                candidate_instructions=len(ins),normalized_operations=len(after),
                literal_bytes=20,checker_bytes=80,gate_address=0xbef610,record_address=0xbef618)


def blob(regions):return b''.join(Path(row['path']).read_bytes() for row in regions)
