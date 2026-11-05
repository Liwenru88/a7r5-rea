"""同源CP仅内存的可逆补丁计划；不提供文件写出、签名或设备接口。"""
from pathlib import Path
import hashlib, importlib.util, io, json, struct, sys

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
sys.path.insert(0,str(ROOT/'a7r5-desktop/prepared/engine/site'))
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM,CS_MODE_ARM

BASE=0x108000
CP_SHA='18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
SOURCE=0x11d2000
TAIL=0xbef9e8

def sha(data): return hashlib.sha256(data).hexdigest()

def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

def arm_blx(at,target):
    if at&3 or not target&1: raise ValueError('ARM BLX地址/状态不符')
    delta=(target&~1)-(at+8)
    if delta&1 or not -(1<<25)<=delta<(1<<25): raise ValueError('BLX距离越界')
    raw=struct.pack('<I',0xfa000000|((delta>>2)&0xffffff)|((delta&2)<<23))
    instructions=list(Cs(CS_ARCH_ARM,CS_MODE_ARM).disasm(raw,at))
    if len(instructions)!=1 or instructions[0].mnemonic!='blx' or int(instructions[0].op_str[1:],16)!=(target&~1):
        raise ValueError('BLX独立解码不一致')
    return raw

def absolute_jump(target,thumb):
    if not target&1: raise ValueError('目标不是Thumb')
    return (bytes.fromhex('dff800f0') if thumb else bytes.fromhex('04f01fe5'))+struct.pack('<I',target)

def fnv(raw):
    value=0x811c9dc5
    for byte in raw:value=((value^byte)*0x1000193)&0xffffffff
    return value

def create_plan(cp,build):
    if len(cp)!=17617008 or sha(cp)!=CP_SHA: raise ValueError('CP身份不符')
    hot={
        0x5e3ed4:'10402de90000a0e3',
        0x5e8178:'e92c00eb',
        0x60800c:'0020a0e3002080e5002081e51eff2fe1',
        0x495fd8:'f0b503af2de9000f',
        0x496044:'242022f192ee3078',
        0x89856c:'4bf2d070c0f25710',
    }
    for at,raw in hot.items():
        expected=bytes.fromhex(raw)
        if cp[at-BASE:at-BASE+len(expected)]!=expected:raise ValueError('原入口语义前像不符: '+hex(at))
    original_call=list(Cs(CS_ARCH_ARM,CS_MODE_ARM).disasm(cp[0x5e8178-BASE:0x5e817c-BASE],0x5e8178))
    if len(original_call)!=1 or original_call[0].mnemonic!='bl' or original_call[0].op_str!='#0x5f3524':
        raise ValueError('原缓存调用目标不符')
    package=ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406/check_placement.py'
    placement=load_module(package,'placement34')
    placement.checked_span(cp,TAIL,408)
    build=Path(build);receipt_raw=(build/'verification.json').read_bytes();receipt=json.loads(receipt_raw)
    for path,digest in receipt['source_sha256'].items():
        if sha(Path(path).read_bytes())!=digest: raise ValueError('bootstrap源码已变')
    paired=load_module(HERE/'build_paired.py','paired34')
    module,raw,rx,rw,symbols=paired.checked_module(Path(receipt['module_receipt']))
    if sha(raw)!=receipt['module_receipt_sha256']: raise ValueError('模块回执已变')
    elf_raw=(build/'bootstrap.elf').read_bytes();blob=(build/'bootstrap-rx.bin').read_bytes()
    if sha(elf_raw)!=receipt['bootstrap_elf_sha256'] or sha(blob)!=receipt['bootstrap_raw_sha256']:
        raise ValueError('bootstrap产物身份不符')
    elf=ELFFile(io.BytesIO(elf_raw));sec=elf.get_section_by_name('.text')
    if sec['sh_addr']!=TAIL or sec.data()!=blob or len(blob)!=408:raise ValueError('408B范围不符')
    sy={v.name:int(v['st_value']) for v in elf.get_section_by_name('.symtab').iter_symbols()}
    if sy['af_boot34_snapshot']!=module['expected_snapshot_entry']:raise ValueError('快照包装器未配对')
    if SOURCE+len(rx)>0x11d3000:raise ValueError('与旧六槽源重叠')
    if fnv(cp[0x11d3000-BASE:0x11d46f0-BASE])!=0x8855bcca:raise ValueError('旧六槽FNV身份不符')
    # 完整原header、旧六槽数据源和包装器前像必须仍与已锁同包一致。
    h=cp[0x128000-BASE:0x12817c-BASE]
    if struct.unpack_from('<3I',h,0x148)!=(0x106f000,0x8a3b40,0x1197000):raise ValueError('BSS描述符漂移')
    root=lambda size:((0x106f000+size+0x4fff)&~0x3fff)+0x128000
    extension=len(rw)+4
    phase=0x1a3ab40+len(rw)
    if phase+4>0x1a3b000 or receipt.get('phase_address')!=hex(phase):raise ValueError('phase与RW重叠或越界')
    if root(0x8a3b40+extension)!=0x1a3c000:raise ValueError('扩展导致页表移动')
    if not 0x1197418<=SOURCE<SOURCE+len(rx)<=0x1a39448:raise ValueError('源不在原必清BSS')
    rows=[]
    def add(address,after,reason):
        offset=address-BASE;before=cp[offset:offset+len(after)]
        if len(before)!=len(after):raise ValueError('补丁越界')
        rows.append(dict(address=address,offset=offset,bytes=len(after),before=before.hex(),after=after.hex(),reason=reason))
    add(0x12814c,struct.pack('<I',0x8a3b40+extension),f'显式保留RW{len(rw)}+phase4，原L1/L2/栈不移动')
    add(0x5e3ed8,arm_blx(0x5e3ed8,sy['af_boot34_prepare']),'仅替原MOV r0,0，原PUSH保持，返回值恒0')
    add(0x5e8178,arm_blx(0x5e8178,sy['af_boot34_cache']),'原D维护仍执行，另加原I维护，随后原TLB序列保持')
    add(0x60800c,absolute_jump(sy['af_boot34_map'],False),'原extraMap callback，原unmap保持')
    for at,name in ((0x495fd8,'af_boot34_start'),(0x496044,'af_boot34_hs'),(0x89856c,'af_boot34_snapshot')):
        add(at,absolute_jump(sy[name],True),'永久phase准入及原指令回退')
    add(TAIL,blob,'明确回收的408B原RX尾')
    add(SOURCE,rx,'仅原必清BSS且不与旧载荷源重叠的冷源')
    rows.sort(key=lambda row:row['offset'])
    if any(a['offset']+a['bytes']>b['offset'] for a,b in zip(rows,rows[1:])):raise ValueError('补丁重叠')
    changed=bytearray(cp)
    for row in rows:changed[row['offset']:row['offset']+row['bytes']]=bytes.fromhex(row['after'])
    if changed[0x11d3000-BASE:0x11d4900-BASE]!=cp[0x11d3000-BASE:0x11d4900-BASE]:raise ValueError('旧载荷被修改')
    if changed[0xbef700-BASE:TAIL-BASE]!=cp[0xbef700-BASE:TAIL-BASE]:raise ValueError('旧包装器前缀被修改')
    if changed[0x5e3ed4-BASE:0x5e3ed8-BASE]!=bytes.fromhex('10402de9'):raise ValueError('原PUSH未保留')
    expected=cp[0x898548-BASE:0x898548-BASE+118]
    actual=changed[0x898548-BASE:0x898548-BASE+118]
    if actual[:36]!=expected[:36] or actual[44:]!=expected[44:]:raise ValueError('118B窗口超出单gate')
    return dict(status='MEMORY_ONLY_REVERSIBLE_PROPOSAL',source_sha256=CP_SHA,
        candidate_sha256=sha(changed),bytes=len(cp),patches=rows,
        bootstrap_receipt_sha256=sha(receipt_raw),module_artifact=module['artifact'],
        preserved_old_joint_fnv='0x8855bcca',RX_source_address=hex(SOURCE),
        BSS_extension_bytes=extension,phase_address=hex(phase),original_page_root='0x1a3c000',
        target_executed=False,CP_file_written=False,installed=False,installable_firmware=False)

def transform(cp,plan,reverse=False):
    key='candidate_sha256' if reverse else 'source_sha256'
    if sha(cp)!=plan[key] or len(cp)!=plan['bytes']:raise ValueError('整包前像不符')
    before,after=('after','before') if reverse else ('before','after')
    # 全部前检通过后才构造副本；失败不触碰输入。
    for row in plan['patches']:
        i,n=row['offset'],row['bytes']
        if i<0 or n<=0 or i+n>len(cp) or cp[i:i+n]!=bytes.fromhex(row[before]):raise ValueError('补丁前像不符')
    out=bytearray(cp)
    for row in plan['patches']:
        i,n=row['offset'],row['bytes'];value=bytes.fromhex(row[after])
        if len(value)!=n:raise ValueError('补丁长度不符')
        out[i:i+n]=value
    if sha(out)!=plan['source_sha256' if reverse else 'candidate_sha256']:raise ValueError('结果摘要不符')
    return bytes(out)
