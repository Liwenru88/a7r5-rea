"""隔离回放原版 Edit Gamma 指令，对照 CPU／MPS；不启动应用或连接设备。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edit', type=Path, required=True)
    source_group=parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument('--cp', type=Path)
    source_group.add_argument('--record', type=Path, help='已绑定摘要的原始576字节CP记录')
    parser.add_argument('--bin', type=Path, required=True)
    parser.add_argument('--python', type=Path, default=ROOT/'.venv/bin/python')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    from audit_edit_renderer import Mach, PIN, THIN_PIN
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn import arm64_const as registers
    sys.path.insert(0, str(ROOT/'compilers'))
    from custom_filter_v4 import unpack, CP_SHA
    sha = lambda value: hashlib.sha256(value).hexdigest()
    fat = args.edit.read_bytes()
    if sha(fat) != PIN:
        raise ValueError('Edit 源版本摘要不符')
    slices = [struct.unpack_from('>5I', fat, 8+20*i) for i in range(struct.unpack_from('>I', fat, 4)[0])]
    _, _, offset, size, _ = next(row for row in slices if row[0] == 0x100000c)
    data = fat[offset:offset+size]
    if sha(data) != THIN_PIN:
        raise ValueError('Edit ARM64 源版本摘要不符')
    if args.cp is not None:
        cp = args.cp.read_bytes()
        if sha(cp) != CP_SHA:
            raise ValueError('CP 源版本摘要不符')
        record = cp[0xcc4a0c:0xcc4a0c+576]
    else:
        record = args.record.read_bytes()
    record_sha = 'f4e9f31bce38b4c705721a501c7597705852e671bc39baf60b02dac8b88f95ac'
    if len(record)!=576 or sha(record) != record_sha:
        raise ValueError('CP Gamma 记录摘要不符')
    axis = [0]
    for span, start, exponent in zip(
            (32,32,64,128,256,512,1024,2048,4096,8192,16384,32768),
            (0,32,64,128,256,512,1024,2048,4096,8192,16384,32768),record[0x204:0x210]):
        step = span >> exponent
        axis.extend(32*min(65535,start+j*step) for j in range(1,span//step+1))
    if len(axis) != 129 or axis[-3:] != [1835008,1966080,2097120]:
        raise ValueError('CP Gamma 横坐标不符')
    image = Mach(data)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for segment in image.segments:
        if segment['size']:
            cpu.mem_map(segment['va'], (segment['vsize']+4095)&~4095)
            cpu.mem_write(segment['va'], data[segment['offset']:segment['offset']+segment['size']])
    gamma, ax, values, contrast_address = 0x30100000,0x30130000,0x30131000,0x30133000
    stop, stack, guard = 0x31000000,0x303f0000,0x30220000
    cpu.mem_map(0x30000000,0x400000)
    cpu.mem_map(stop,4096)
    cpu.reg_write(registers.UC_ARM64_REG_CPACR_EL1,3<<20)
    cpu.mem_write(0x1002c02e8,struct.pack('<Q',guard))
    cpu.mem_write(guard,struct.pack('<Q',0x123456789abcdef0))
    contrast_at=image.off(0x100249e60+18*0x1004)
    contrast_bytes=data[contrast_at:contrast_at+4100]
    contrast=list(struct.unpack('<1025i',contrast_bytes))
    cpu.mem_write(contrast_address,contrast_bytes)
    cases=[dict(name='factory-ST',q=list(struct.unpack_from('<129I',record)))]
    config=unpack(args.bin.read_bytes())
    cases.extend(dict(name=entry['short_name'],q=entry['gamma_native_129'])
                 for entry in config['entries'] if entry['number'] in (5,6,14))
    cases.append(dict(name='linear-native',q=[min(131071,2*(v//32)) for v in axis]))
    source=next(entry['gamma_native_129'] for entry in config['entries'] if entry['number']==5)
    for index in (127,128):
        q=source.copy()
        q[index] = min(q[index]+1000,131071) if index==127 else max(q[index-1],120000)
        cases.append(dict(name='tail-node-'+str(index),q=q))
    rows=[]
    for case in cases:
        for use_contrast in (False,True):
            xb=struct.pack('<129i',*axis);yb=struct.pack('<129i',*[2*v for v in case['q']])
            for at,value in ((ax,xb),(values,yb),(gamma-16,b'\xa5'*16),
                             (gamma,b'\xcc'*0x20000),(gamma+0x20000,b'\x5a'*16)):
                cpu.mem_write(at,value)
            for i,value in enumerate((0,gamma,ax,values,129,contrast_address if use_contrast else 0)):
                cpu.reg_write(getattr(registers,'UC_ARM64_REG_X'+str(i)),value)
            cpu.reg_write(registers.UC_ARM64_REG_SP,stack)
            cpu.reg_write(registers.UC_ARM64_REG_LR,stop)
            cpu.emu_start(0x1000c82d4,stop,count=4_000_000)
            if cpu.reg_read(registers.UC_ARM64_REG_PC)!=stop or cpu.reg_read(registers.UC_ARM64_REG_SP)!=stack:
                raise RuntimeError('原始函数未在指令预算内返回')
            if (bytes(cpu.mem_read(ax,len(xb)))!=xb or bytes(cpu.mem_read(values,len(yb)))!=yb
                    or bytes(cpu.mem_read(gamma-16,16))!=b'\xa5'*16
                    or bytes(cpu.mem_read(gamma+0x20000,16))!=b'\x5a'*16):
                raise ValueError('原始函数输入或输出边界变化')
            rows.append(dict(name=case['name'],q=case['q'],contrast=use_contrast,
                             edit_table_sha256=sha(bytes(cpu.mem_read(gamma,0x20000))),guards_intact=True))
    # 数值环境与指令回放环境独立，避免安装依赖或使用不同 Python ABI。
    child = '''import sys,json,hashlib,numpy as np
from pathlib import Path
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'scripts'),str(root/'web')]
from edit_native_model import expand_gamma
from native_gamma import EDIT_AXIS,tensor_table
from edit_color_pipeline import static_table
data=json.load(sys.stdin);out=[]
neutral=static_table(0x100249e60+18*0x1004,1025,'<i4')
assert neutral.tolist()==data['contrast']
for row in data['rows']:
 c=neutral if row['contrast'] else None;q=np.array(row['q'])
 cpu=expand_gamma(EDIT_AXIS,2*q,c)
 gpu=tensor_table(q,contrast=c,device='mps').cpu().numpy().astype('<u2')
 digest=hashlib.sha256(cpu.tobytes()).hexdigest()
 assert digest==row['edit_table_sha256'],row['name']
 assert np.array_equal(cpu,gpu),row['name']
 out.append({k:v for k,v in row.items() if k!='q'}|dict(cpu_matches_edit=True,mps_matches_cpu=True,samples=65536))
print(json.dumps(out))
'''
    completed=subprocess.run([str(args.python),'-B','-c',child,str(ROOT)],
        input=json.dumps(dict(rows=rows,contrast=contrast)),text=True,capture_output=True,check=True)
    result=dict(schema='r5-edit-native129-replay/1',edit_sha256=PIN,edit_arm64_sha256=THIN_PIN,
        expected_cp_sha256=CP_SHA,full_cp_file_verified=args.cp is not None,
        source_record_sha256=record_sha,binary_sha256=sha(args.bin.read_bytes()),
        device_io=False,app_launched=False,unmodified_original_instructions=True,
        implementation_sha256={name:sha((ROOT/name).read_bytes()) for name in
            ('scripts/native_gamma.py','scripts/edit_native_model.py','scripts/verify_edit_gamma129.py')},
        limits=['仅覆盖已绑定的 Gamma 构造函数、中性对比度表及无附加对比度；不证明相机ISP像素插值。'],
        cases=json.loads(completed.stdout))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(cases=len(rows),all_cpu_and_mps_match_original_Edit=True,output=str(args.output))))


if __name__=='__main__':
    main()
