"""联合曲线的原厂消费者对照；只执行固定离线QEMU窗口。"""
import argparse
import json
from pathlib import Path
import struct

from look_materials import load,regular,sha
from look_joint import memory,curve,GAMMA_VA
from look_native import execute


def verify(materials):
    files,receipt=load(materials)
    if receipt['schema']!=7:raise ValueError('只接受联合参数材料')
    layout=json.loads(files['joint-layout.json']);basis=layout['basis']
    run=execute('cp',materials,request=[0],joint_check=True)
    lines=regular(run/'console.log',1_000_000).decode().splitlines()
    if lines[0]!='JOINT_STAGE_BEGIN' or lines[-1]!='JOINT_STAGE_END' or len(lines)!=76:
        raise ValueError('联合参数原厂消费输出不完整')
    seen=set();controls=set();partials=set();secondary=set()
    for line in lines[1:-1]:
        tag,slot,variant,hexdata=line.split();slot=int(slot,16);variant=int(variant,16)
        if tag in ('D','R'):
            key=(slot,variant);collection=secondary if tag=='D' else partials
            if slot not in range(6) or variant not in (0,1) or key in collection:raise ValueError('第二域或局部更新身份不符')
            if tag=='D':
                style=files['style-property.bin'];bank=style[0x1200]
                original=struct.unpack_from('<8h',style,0x1250+bank*64)
                values=[a+b for a,b in zip(original,basis[slot]['chroma_planes'][0])]
                expected=struct.pack('<8h',*values)+style[0xf00+variant*16:0xf10+variant*16]
            else:
                target=bytearray(96);target[0x4c]=1;target[0x4d]=variant
                if variant:
                    for offset in (0x30,0x34,0x40):struct.pack_into('<I',target,offset,51+slot*2)
                expected=bytes(target)
            if bytes.fromhex(hexdata)!=expected:raise ValueError('第二域或局部更新不符：'+str((tag,key)))
            collection.add(key);continue
        if tag=='O':
            if slot not in (49,50) or variant!=6 or slot in controls:raise ValueError('原曲线对照身份不符')
            pointer=struct.unpack('<I',memory(files,GAMMA_VA+slot*28+variant*4,4))[0]
            if bytes.fromhex(hexdata)!=memory(files,pointer,576)[:516]:raise ValueError('原FL2/FL3视频曲线改变')
            controls.add(slot);continue
        domain,column=divmod(variant,7);key=(slot,domain,column)
        if tag!='Y' or key in seen or slot not in range(6) or (domain,column) not in ((*((0,c) for c in range(7)),(1,6))):
            raise ValueError('联合曲线身份或顺序不符')
        pointer=struct.unpack('<I',memory(files,GAMMA_VA+(51+slot*2+domain)*28+column*4,4))[0]
        expected=curve(memory(files,pointer,576),basis[slot]['tone_q10'])[:516]
        if bytes.fromhex(hexdata)!=expected:raise ValueError('原厂Gamma与独立整数参照不一致：'+str(key))
        seen.add(key)
    if len(seen)!=48 or controls!={49,50} or len(partials)!=12 or len(secondary)!=12:raise ValueError('联合参数检查存在遗漏')
    report=dict(status='passed',CP_sha256=sha(files['cpapp-b.bin']),native_Gamma_cases=len(seen),native_original_movie_controls=len(controls),
        native_secondary_chroma_cases=len(secondary),native_partial_update_cases=len(partials),
        domains=['original ST row0 all7 columns','original ST row10 column6'],
        explicit_synthetic_context=True,full_CP_boot_verified=False,ISP_pixels_verified=False,
        camera_io=False,SD_io=False,run=str(run))
    (run/'joint-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2));return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--materials',required=True,type=Path)
    verify(parser.parse_args().materials)
