"""只读普通镜像中的提取库，固定反汇编证据及来源摘要。"""
from pathlib import Path
import hashlib
import json
import subprocess
import argparse
import tempfile
from elftools.elf.elffile import ELFFile
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from build import HERE,WORK,EVIDENCE,save,sha
from references import loader_path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='新的本机证据目录；不覆盖封存包')
    args=parser.parse_args()
    image=WORK/'a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha15.img'
    reference=json.loads((EVIDENCE/'static-verdict.json').read_text())
    expected=reference['source_image_sha256']
    if str(image.relative_to(WORK))!=reference['source_image']:raise ValueError('参考镜像路径身份变化')
    if sha(image)!=expected:raise ValueError('原始明文镜像与验收记录不符')
    path=loader_path();raw=path.read_bytes()
    with path.open('rb') as f:
        elf=ELFFile(f);section=elf.get_section_by_name('.text');base=section['sh_addr'];code=section.data()
        symbols={s.name:(s['st_value'],s['st_size']) for s in elf.get_section_by_name('.dynsym').iter_symbols()}
    if symbols['adj_cmd_set_file2']!=(0x983c,0x460):raise ValueError('写入函数布局变化')
    ins={i.address:(i.mnemonic,i.op_str,i.bytes.hex()) for i in Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(code,base)}
    checks={0x9a78:('bl','#0x6920'),0x9a88:('bl','#0x5e70'),0x9aac:('sub','w0, w1, w0'),
            0x9b30:('mov','w2, #0x241'),0x9bac:('bl','#0x6b10'),0x9bb8:('bl','#0x6360'),
            0x9bc0:('bl','#0x6ad0'),0x9bf4:('bl','#0x6920'),0x9bf8:('cbnz','w0, #0x99f4'),
            0x9c18:('mov','w1, #1'),0x9c1c:('bl','#0x63c0'),0x9c3c:('bl','#0x6480')}
    for addr,wanted in checks.items():
        if ins[addr][:2]!=wanted:raise ValueError(f'指令变化：{addr:#x} {ins[addr]}')
    strings={hex(i):raw[i:raw.index(b'\0',i)].decode() for i in (0x32702,0x323dd,0x322ff,0x32311)}
    if strings['0x32702']!='/tmp/jiritsu/libJit.so' or strings['0x323dd']!='/tmp/jbusy':raise ValueError('固定路径变化')
    # 非符号文本也保留为原始机器字，避免只凭符号名断言加载入口。
    result=dict(schema='a7r5-libjit-static-1',model='ILCE-7RM5',firmware='4.00',
                source_image=str(image.relative_to(WORK)),source_image_sha256=expected,
                source_image_unchanged=True,library_path='/usr/lib/libJiritsu.so',library_bytes=len(raw),library_sha256=sha(path),
                function={'address':'0x983c','size':'0x460'},instructions={hex(a):dict(mnemonic=ins[a][0],operands=ins[a][1],bytes=ins[a][2]) for a in checks},
                strings=strings,same_loader_branch_confirmed=True,rtld_flags=1,dlsym_required=False,
                work_dir_limit_bytes=0x1800000,work_partition='/dev/nflasha6',
                write_open_flags='O_WRONLY|O_CREAT|O_TRUNC',stat_failure_code='0x10000006',absence_proven_by_error=False,
                camera_execution_verified=False,reference_commit='5ec277d8aa50704c1211a7c114730391fcd25a40')
    if args.output:
        output=args.output.absolute();output.mkdir(parents=True,exist_ok=False)
    else:
        (HERE/'verification').mkdir(exist_ok=True)
        output=Path(tempfile.mkdtemp(prefix='static-',dir=HERE/'verification'))
    save(output/'static-verdict.json',result)
    (output/'static-analysis.md').write_text('''# A7R5 4.00 libJit 加载入口静态核对

来源是用户已经校验的 cnflasha15.img，使用 debugfs 默认只读 dump 提取 /lib/libJiritsu.so；镜像未挂载、未修复、未改写。源镜像摘要与物理分类清单一致，库路径在运行系统为 /usr/lib/libJiritsu.so。摘要、字节数和机器指令见 static-verdict.json。

- adj_cmd_set_file2：0x983c，长度0x460。0x98c0–0x98d0将 /dev/nflasha6 挂到 /tmp/jiritsu，随后沿mode=0工作区路径分支处理。
- 0x9a68–0x9a90：strcmp精确匹配 /tmp/jiritsu/libJit.so，再检查 /tmp/jbusy；存在则返回0x10000011，不写文件。
- 0x9a9c–0x9ab4：目录占用加本次写入上限0x1800000，即24MiB。参考A7C2报告的25MiB不能直接套用。
- 0x9b30–0x9bc0：open(0x241)，write，fsync，close。0x9bc4核对写入字节数。fsync返回值本分支未独立校验，不能仅凭成功结果保证断电持久性。
- 0x9be4–0x9bf8：再次全串比较固定路径；不匹配跳过加载。
- 0x9c14–0x9c3c：dlopen(path,1)，非空则立即dlclose，没有dlsym。失败时文件已写，返回0x10000000；初始化未执行则不能依靠自删。
- 此分支不经过cmd_start、jmode或四个JIT导出符号；不要把USB认证START与该JIT运行命令混为一谈。
- adj_cmd_get_file2：0xa408 stat失败统一转到0xa574，返回0x10000006；其含义不是已证实ENOENT。新包对此不作不存在断言。

上述结论证明固件包含相同加载入口，不证明本机USB触发已经通过，也不证明其稳定性、服务退出或相机可刷回。载荷在原厂服务地址空间内初始化；初始化崩溃可能影响服务。

参考：https://github.com/chocotan/a7c2-re/tree/5ec277d8aa50704c1211a7c114730391fcd25a40/report/2026-10-18-libjit-exec 。新实现保留其入口思路，任务固定化、监督、回执和主机门禁独立实现；旧kit和旧包不改。
''')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
