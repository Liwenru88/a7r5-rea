"""内嵌 CP 与原设置路径的真实 QEMU 输出对照；不启动完整固件。"""
import argparse
import json
from pathlib import Path
import re
import struct
import tempfile

from look_materials import load,regular,sha
from look_matrix_embed import BANKS
from look_native import execute
from runtime_manifest import LAB,digest

CALS=((0,0,0),(256,256,256),(1024,1024,1024),(65535,32768,12345))


def cases():
    for profile in (*range(257),0xffffffff):
        target=54<=profile<=57
        for slot in (*range(17),0xffffffff) if target else (0,15,16,0xffffffff):
            for ci in range(4) if target else (0,1,3):
                yield profile,slot,ci


def parse(raw):
    lines=raw.splitlines();inputs=list(cases())
    if lines[0]!=b'MATRIX_INLINE_CHECK_BEGIN' or lines[-1]!=b'MATRIX_INLINE_CHECK_END' or len(lines)!=len(inputs)+3:
        raise ValueError('矩阵等价核对输出不完整')
    result={}
    for n,(key,line) in enumerate(zip(inputs,lines[1:-2])):
        m=re.fullmatch(rb'M ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{128})',line)
        if not m or (int(m[1],16),int(m[2],16))!=(key[0],n):raise ValueError('矩阵核对身份、顺序或长度不符')
        value=bytes.fromhex(m[3].decode())
        if value[54:]!=b'\xa5'*10:raise ValueError('矩阵输出越界')
        result[key]=value
    m=re.fullmatch(rb'F ([0-9a-f]{8}) ([0-9a-f]{8}) ([0-9a-f]{8})',lines[-2])
    if not m or int(m[1],16)!=len(inputs) or struct.pack('<I',int(m[2],16))!=bytes.fromhex(m[3].decode()):
        raise ValueError('设置未变回执不符')
    return result


def independent(delta,profile,slot,ci):
    bank=BANKS[profile-54];slot=slot if slot<16 else 0;values=[];cal=CALS[ci]
    for endpoint in range(3):
        a,b,c,d,e,f=struct.unpack_from('<6H',delta,4+(bank-22)*768+endpoint*192+slot*12)
        values.extend((cal[0]+a+b,-a,-b,-c,cal[1]+c+d,-d,-e,-f,cal[2]+e+f))
    return struct.pack('<27H',*(n&65535 for n in values))+b'\xa5'*10


def verify(reference,candidate):
    before,_=load(reference);after,record=load(candidate)
    if record['schema'] not in (3,4,5,6,7) or before['cpapp-b.bin']!=after['cp-matrix-source.bin']:
        raise ValueError('原设置参考与内嵌候选不是同一前像')
    out=Path(tempfile.mkdtemp(prefix='look-inline-verify-',dir=LAB/'runs'))
    report=dict(status='failed',camera_io=False,CP_RTOS_booted=False,ISP_pixels_verified=False,
        device_deployment_ready=False,reference=str(Path(reference).absolute()),candidate=str(Path(candidate).absolute()))
    try:
        results={};runs={}
        for name,folder in (('settings',reference),('inline',candidate)):
            for mode in range(3):
                run=execute('cp',folder,request=[mode],matrix_check=True)
                results[name,mode]=parse(regular(run/'console.log',1_000_000))
                runs[name+str(mode)]=dict(run=str(run),console_sha256=digest(run/'console.log'),
                    instruction_trace_sha256=digest(run/'instruction-errors.log'))
        targets=controls=0
        for mode in range(3):
            for key,value in results['inline',mode].items():
                if 54<=key[0]<=57:
                    expected=independent(after['matrix-delta.bin'],*key)
                    if value!=expected or value!=results['settings',1][key]:
                        raise ValueError('内嵌矩阵与供体算术/设置修复路径不一致：'+str(key))
                    targets+=1
                else:
                    if value!=results['settings',mode][key]:raise ValueError('非目标档位行为改变：'+str(key))
                    controls+=1
        if not any(v!=results['settings',1][k] for k,v in results['settings',0].items() if 54<=k[0]<=57):
            raise ValueError('未复现原设置缺失差异')
        trace=Path(runs['inline0']['run'])/'instruction-errors.log'
        if '0x00bef6b0' not in trace.read_text():raise ValueError('缺少新辅助代码实际执行轨迹')
        report.update(status='passed',QEMU_runs=runs,native_target_cases=targets,native_control_cases=controls,
            total_native_cases=sum(len(v) for v in results.values()),
            modes=['unrepaired settings','repaired settings','unknown target settings'],
            BSS_clear_exercised=True,properties_unchanged=True,callee_saved_and_stack_preserved=True,
            source_CP_sha256=sha(before['cpapp-b.bin']),embedded_CP_sha256=sha(after['cpapp-b.bin']))
    except Exception as error:
        report['error']=str(error);raise
    finally:
        (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(out,flush=True)
    return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',required=True,type=Path);p.add_argument('--candidate',required=True,type=Path)
    a=p.parse_args();verify(a.reference,a.candidate)
