"""只读检查封包、已有重建副本和目标ABI；不读取原始镜像或访问设备。"""
import json
from pathlib import Path
from elftools.elf.elffile import ELFFile
import candidate_once as tool

ROOT=Path(__file__).resolve().parent


def verify(package,rebuild,evidence):
    m=tool.check(package)
    if tool.sha(package/'config.h')!=tool.sha(rebuild/'config.h'):raise ValueError('重建配置不一致')
    binaries={}
    for name in ['ssh-original.arm64','session.arm64','anchor.arm64']:
        if tool.sha(package/name)!=tool.sha(rebuild/name):raise ValueError('重建字节不一致：'+name)
        binaries[name]=dict(sha256=tool.sha(package/name),bytes=(package/name).stat().st_size)
    libc=next((package/'rebuild').rglob('libc-2.25.so'))
    loader=tool.project()/'a7r5-qemu/sdk/lib/ld-2.25.so'
    exports={};inputs={}
    for path in [libc,loader]:
        with path.open('rb') as f:
            for sym in ELFFile(f).get_section_by_name('.dynsym').iter_symbols():
                if sym['st_shndx']!='SHN_UNDEF':exports.setdefault(sym.name,path.name)
        inputs[path.name]=tool.sha(path)
    with (package/'sftp-server.arm64').open('rb') as f:
        elf=ELFFile(f)
        undefined={s.name for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name and s['st_shndx']=='SHN_UNDEF' and s['st_info']['bind']!='STB_WEAK'}
        missing=sorted(undefined-exports.keys())
        if missing:raise ValueError('SFTP尚有未提供符号：'+str(missing))
        abi=dict(machine=elf['e_machine'],needed=[t.needed for t in elf.get_section_by_name('.dynamic').iter_tags() if t.entry.d_tag=='DT_NEEDED'],
            load_alignment=sorted({s['p_align'] for s in elf.iter_segments() if s['p_type']=='PT_LOAD'}),strong_undefined_missing=missing,
            stack_guard_provider=exports.get('__stack_chk_guard'),target_library_sha256=inputs)
    qemu=json.loads((evidence/'result.json').read_text())
    if qemu['status']!='passed' or not qemu['runtime_inputs_unchanged'] or qemu['cleanup']!={'method':'qmp-quit','exit_code':0}:raise ValueError('QEMU验收或关闭未通过')
    return dict(status='passed',camera_io=False,run_id=m['run_id'],rebuild=binaries,sftp_abi=abi,
        qemu_evidence=str(evidence),qemu_result_sha256=tool.sha(evidence/'result.json'),
        caveat='QEMU使用稳定夹具持有者和临时口令；真机bootin锚点、网络与正常运行未在本轮验证')


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('package',type=Path);p.add_argument('rebuild',type=Path);p.add_argument('evidence',type=Path)
    a=p.parse_args();print(json.dumps(verify(a.package,a.rebuild,a.evidence),ensure_ascii=False,indent=2))
