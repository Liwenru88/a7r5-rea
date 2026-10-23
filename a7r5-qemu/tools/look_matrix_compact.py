"""等长CP内嵌：原厂引导中复制矩阵，保持文件系统和初始化data长度。"""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tempfile

from look_matrix_embed import CP_SHA,HELPER_BYTES,HELPER_VA,BASE,TABLE_VA,payload,branch,sha,compile_helper

COPY_VA=0x108f40
SOURCE_VA=0x11d4000
COPY_BYTES=bytes.fromhex('f0b581b0184c194d40f600162046314600f01df8164a904208d02846314600f016f8134a90420dd030bffde72046294640f24022036841f8043b002340f8043b013af7d10198d0f8480101b0f0bd094a094b10f801cb82ea0c0203fb02f20139f7d110467047000000401d0100a0a3017e9b8dc0c59d1c8193010001')
COPY_SHA='fc5b03f44989ba87163f3a0f4078fffca755e4da777058bcbc4c6986e5b5cc50'
CALL_BYTES=bytes.fromhex('850200fa')


def build(original,delta):
    if len(original)!=17617008 or sha(original)!=CP_SHA:raise ValueError('等长内嵌CP前像不符')
    matrix=payload(delta);bss=struct.unpack_from('<3I',original,0x20148)
    data=struct.unpack_from('<3I',original,0x2013c)
    if (bss,data)!=((0x106f000,0x8a2448,0x1197000),(0xf57000,0x117f5c,0x107f000)):
        raise ValueError('CP初始化与BSS布局不符')
    # 0x108da0..0x108f1c为头部影子，0x108f1c为页表指针；栈从0x109000向上保留。
    # 新复制器位于同一已映射前缀页的未使用尾部，不覆盖影子、变量或栈。
    if not 0x108f20<=COPY_VA<COPY_VA+len(COPY_BYTES)<=0x109000:
        raise ValueError('复制器会碰到引导变量或栈')
    source=SOURCE_VA-BASE
    if not data[2]+data[1]<=SOURCE_VA or source+len(matrix)>len(original):
        raise ValueError('暂存区不在原文件尾部零区')
    if (any(original[COPY_VA-BASE:COPY_VA-BASE+len(COPY_BYTES)]) or
        any(original[source:source+len(matrix)]) or
        any(original[HELPER_VA-BASE:HELPER_VA-BASE+80])):
        raise ValueError('前缀尾部、暂存区或原helper保留区已占用')
    if original[0x524:0x528]!=bytes.fromhex('480194e5') or original[0x61643e:0x616442]!=branch(0x71e43e,0xbef3b4):
        raise ValueError('原厂引导或矩阵入口前像不符')
    end=TABLE_VA+len(matrix);size=end-bss[2]
    translation=data[2]-data[0]
    old_root=((bss[0]+bss[1]+0x4fff)&~0x3fff)+translation
    new_root=((bss[0]+size+0x4fff)&~0x3fff)+translation
    if old_root!=new_root or ((end+4095)&~4095)>0x1a3c000:
        raise ValueError('扩展BSS会移动原页表或栈')
    output=bytearray(original);rows=[]
    for at,raw,reason in (
        (0x524,CALL_BYTES,'MMU启用前进入复制器，并重放原LDR'),
        (COPY_VA-BASE,COPY_BYTES,'原前缀页内带FNV校验/重复调用保护的复制器'),
        (0x2014c,struct.pack('<I',size),'只扩展BSS映射一页，不扩展data、不移动全局变量或栈'),
        (source,matrix,'暂存2304字节，复制后恢复原BSS零区'),
        (0x61643e,branch(0x71e43e,HELPER_VA),'54～57改用内嵌矩阵'),
        (HELPER_VA-BASE,HELPER_BYTES,'保留原厂矩阵展开与校准')):
        before=bytes(output[at:at+len(raw)]);output[at:at+len(raw)]=raw
        rows.append(dict(offset=at,bytes=len(raw),before=before.hex(),after=raw.hex(),reason=reason))
    return bytes(output),dict(schema=2,layout='boot-copy-compact',patches=rows,
        source_sha256=sha(original),target_sha256=sha(output),source_bytes=len(original),target_bytes=len(output),
        file_size_unchanged=True,initialized_data_descriptor_unchanged=True,
        initialized_data_span_overlaps_existing_BSS=False,BSS_globals_VA_unchanged=True,
        BSS_size_before=bss[1],BSS_size_after=size,page_table_root=old_root,page_table_root_unchanged=True,
        stack_begin=0x1a3c000,table_VA=TABLE_VA,table_bytes=len(matrix),source_VA=SOURCE_VA,
        source_file=source,boot_copy_VA=COPY_VA,boot_copy_sha256=COPY_SHA,
        profiles=[54,55,56,57],donor_banks=[22,24,23,25],
        full_CP_boot_verified=False,external_loader_verified=False,device_deployment_ready=False,
        camera_io=False,ISP_pixels_verified=False)


def compile_copy(out):
    from runtime_manifest import LAB
    records=[]
    for name,address,entry,extra,expected in (
        ('bootcopy',COPY_VA,'matrix_boot_copy','',COPY_BYTES),
        ('bootcall',0x108524,'matrix_boot_call','matrix_boot_copy_entry = 0x108f41;',CALL_BYTES)):
        layout=out/(name+'.ld');layout.write_text(f'ENTRY({entry})\n{extra}\nSECTIONS {{ . = {address:#x}; .text : {{ *(.text*) }} /DISCARD/ : {{ *(.ARM.attributes*) }} }}\n')
        source=LAB/f'source/guest/look-matrix-{name}.S'
        command=['/opt/homebrew/opt/llvm/bin/clang','--target=armv7a-none-eabi','-nostdlib',
            '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-Wl,-T,'+str(layout),'-Wl,--build-id=none',
            str(source),'-o',str(out/(name+'.elf'))]
        subprocess.run(command,check=True,capture_output=True,timeout=30)
        subprocess.run(['/opt/homebrew/opt/llvm/bin/llvm-objcopy','-O','binary',str(out/(name+'.elf')),
            str(out/(name+'.bin'))],check=True,timeout=30)
        if (out/(name+'.bin')).read_bytes()!=expected:raise ValueError('复制器重建与固定指令不符')
        records.append(dict(command=command,source_sha256=sha(source.read_bytes()),bytes=len(expected),sha256=sha(expected)))
    (out/'bootcopy-build.json').write_text(json.dumps(records,indent=2)+'\n')


def prepare(folder):
    from look_materials import load
    from runtime_manifest import LAB
    files,record=load(folder)
    if record['schema']!=2:raise ValueError('只接受原参数材料，拒绝叠加未知候选')
    out=Path(tempfile.mkdtemp(prefix='look-materials-compact-',dir=LAB/'build'))
    compile_copy(out);compile_helper(out)
    cp,report=build(files['cpapp-b.bin'],files['matrix-delta.bin'])
    files['cp-matrix-source.bin']=files['cpapp-b.bin'];files['cpapp-b.bin']=cp
    files['matrix-inline.json']=(json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()
    for name,raw in files.items():(out/name).write_bytes(raw)
    record.update(schema=5,files={n:dict(bytes=len(r),sha256=sha(r)) for n,r in files.items()},
        CP_scope='equal-size CP with verified bootstrap copy candidate; full startup not accepted',
        device_deployment_ready=False)
    (out/'receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    load(out);return out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--materials',type=Path,required=True)
    print(prepare(p.parse_args().materials))
