"""核对内嵌矩阵的文件跨度与原厂NOR分段加载代码；静态证据不冒充加载链执行。"""
import argparse
import json
from pathlib import Path
import struct

from look_materials import load,sha
from look_matrix_compact import COPY_VA,COPY_BYTES,SOURCE_VA
from look_matrix_embed import BASE,TABLE_VA,payload
from media_candidate import extract
from runtime_manifest import verified_inputs

NOR_SHA='08da9376e78cc1fd328a57211ab1089d3e460e33834eee30f790cb3ea29a3f4d'


def audit(cp,delta,nor,*,joint=None):
    if len(nor)!=417792 or sha(nor)!=NOR_SHA:raise ValueError('固定NOR加载器身份不符')
    if nor[:8]!=b'EXBL\xaaUU\xaa':raise ValueError('NOR描述符头不符')
    # 原0xfe056b80/0xfe056ba8/0xfe056b58对ID5读取本记录。
    page,count,flags,_version,destination=struct.unpack_from('<5I',nor,0x140)
    if nor[0x160:0x16c].rstrip(b'\0')!=b'cpapp-b.bin':raise ValueError('CP描述符路径不符')
    first_stage=5<<20;rounded=(len(cp)+511)&~511
    if destination!=BASE or count*512!=rounded or page*512!=0x200000:
        raise ValueError('CP长度、目标地址或源跨度变化')
    copier_sha=joint['bootcopy']['binary_sha256'] if joint else sha(COPY_BYTES)
    if len(cp)!=17617008 or sha(cp[COPY_VA-BASE:COPY_VA-BASE+len(COPY_BYTES)])!=copier_sha:
        raise ValueError('等长CP或引导复制器不符')
    table=payload(delta)
    if joint:
        from look_joint import TARGET_SHA,PARAMS_VA,STAGING_VA,PAYLOAD_BYTES,PAYLOAD_END
        if sha(cp)!=TARGET_SHA:raise ValueError('联合CP固定身份不符')
        stage=STAGING_VA-BASE;stage_end=stage+PAYLOAD_BYTES
        if sha(cp[stage:stage_end])!=joint['payload_sha256']:raise ValueError('联合暂存载荷不符')
        source=stage+TABLE_VA-PARAMS_VA
    else:stage=source=SOURCE_VA-BASE;stage_end=source+len(table)
    end=source+len(table)
    if cp[source:end]!=table or not first_stage<source<end<=len(cp)<=rounded:
        raise ValueError('矩阵暂存数据未被完整文件跨度覆盖')
    data=struct.unpack_from('<3I',cp,0x2013c);bss=struct.unpack_from('<3I',cp,0x20148)
    expected_bss=PAYLOAD_END-0x1197000 if joint else 0x8a3900
    if data!=(0xf57000,0x117f5c,0x107f000) or bss!=(0x106f000,expected_bss,0x1197000):
        raise ValueError('初始化data/BSS布局变化')
    if not data[2]+data[1]<=SOURCE_VA or not bss[2]<=TABLE_VA<TABLE_VA+len(table)<=0x1a3c000:
        raise ValueError('暂存区或目标矩阵碰到初始化data/栈')
    if joint and not first_stage<stage<stage_end<=len(cp):raise ValueError('联合暂存范围不在原厂完整文件加载内')
    # 固定原厂指令：预加载5MiB；余段的源、目标均加5MiB，长度减5MiB。
    instructions={0x189e8:'020aa052',0x188e8:'13015411',0x188f8:'14015451',0x18924:'15005491'}
    for offset,want in instructions.items():
        if nor[offset:offset+4].hex()!=want:raise ValueError('NOR分段加载指令身份不符')
    return dict(scope='static original NOR descriptor and split-read instruction audit; not loader execution',
        CP_sha256=sha(cp),CP_bytes=len(cp),NOR_loader_sha256=sha(nor),NOR_flags=flags,
        descriptor_offset=0x140,flash_offset=page*512,load_address=destination,
        rounded_load_bytes=rounded,padding_bytes=rounded-len(cp),first_read_bytes=first_stage,
        remaining_read_bytes=rounded-first_stage,staged_matrix_file_range=[source,end],
        staged_matrix_in_remaining_read=True,entire_file_span_covers_matrix=True,
        staged_joint_file_range=[stage,stage_end] if joint else None,
        data_descriptor_unchanged=True,no_data_BSS_overlap=True,original_stack_VA_unchanged=True,
        original_loader_executed=False,AP_PCIe_transfer_verified=False,
        full_CP_boot_verified=False,ISP_verified=False,camera_io=False)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--materials',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    files,record=load(args.materials)
    nor=extract(verified_inputs()['initrd'],['cp/nor_ldr.img'])['cp/nor_ldr.img']
    report=audit(files['cpapp-b.bin'],files['matrix-delta.bin'],nor,
        joint=json.loads(files['joint-layout.json']) if record['schema']==7 else None)
    with args.output.open('x') as stream:json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print(args.output)


if __name__=='__main__':main()
