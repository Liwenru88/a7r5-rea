"""最终离线验收与ZIP；不触及设备，拒绝封装已批准或已尝试目录。"""
from pathlib import Path
import ast
import hashlib
import json
import os
import stat
import sys
import xml.etree.ElementTree as ET
import zipfile
from build import HERE,WORK,sha,save

def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,required=True)
    p.add_argument('--proof',type=Path,required=True)
    p.add_argument('--candidate',type=Path,required=True)
    p.add_argument('--expected-tests',type=int,required=True)
    args=p.parse_args()
    package=args.package.absolute();proof=args.proof.absolute()
    if not 1<=args.expected_tests<=10000:raise ValueError('回归数量异常')
    if any((package/name).exists() for name in ('approval.json','ATTEMPT_LOCK','result')):raise ValueError('只封装未批准、未尝试包')
    op=json.loads((package/'operation.json').read_text());config=json.loads((package/'config.json').read_text())
    template=json.loads((package/'approval-template.json').read_text())
    if template['accepted'] or template['operation_sha256']!=sha(package/'operation.json'):raise ValueError('未批准模板不符')
    for name,digest in op['files'].items():
        if sha(package/name)!=digest:raise ValueError('封存材料变化：'+name)
    for line in (package/'checksums.sha256').read_text().splitlines():
        digest,name=line.split('  ',1)
        if sha(package/name)!=digest:raise ValueError('校验清单不符')
    for p in package.rglob('*.py'):ast.parse(p.read_text(),filename=str(p))
    xml=ET.parse(proof/'tests/package-final.xml').getroot()
    suites=[xml] if xml.tag=='testsuite' else list(xml.iter('testsuite'))
    tests=sum(int(s.attrib['tests']) for s in suites)
    if tests!=args.expected_tests or any(int(s.attrib.get(k,0)) for s in suites for k in ('errors','failures','skipped')):raise ValueError('相关回归未全部通过')
    guestroot=proof/'guest-01'
    guest=json.loads((guestroot/'result.json').read_text())
    if guest['status']!='passed' or len(guest['cases'])!=8 or guest['cleanup']!={'method':'qmp-quit','exit_code':0} or not guest['runtime_manifest_unchanged']:raise ValueError('QEMU验收不完整')
    if not guest['exact_production_payload_passed'] or config['run_id'].encode() not in (guestroot/'production.txt').read_bytes():raise ValueError('生产库会话未绑定到QEMU记录')
    if sha(package/'materials/libJit.so')!=sha(args.candidate/'materials/libJit.so'):raise ValueError('实际载荷不等于QEMU候选')
    rebuild=json.loads((proof/'rebuild-final.json').read_text())
    if not rebuild['rebuild_identical'] or rebuild['sha256']!=op['payload']['sha256']:raise ValueError('重建不一致')
    static=json.loads((package/'evidence/static-verdict.json').read_text())
    if sha(WORK/static['source_image'])!=static['source_image_sha256']:raise ValueError('源镜像发生变化')
    original=json.loads((proof/'preserved-before.json').read_text())
    for name,digest in original['files'].items():
        if sha(WORK/name)!=digest:raise ValueError('旧包或记录变化：'+name)
    for name,expected in original['locks'].items():
        s=(WORK/name).stat()
        if dict(inode=s.st_ino,mode=s.st_mode,mtime_ns=s.st_mtime_ns)!=expected:raise ValueError('旧锁变化')
    # 只给尚未批准的新包补入其自身验收记录，再重新计算本地封存摘要。
    import shutil
    for source,name in [(proof/'tests/package-final.log','verification/package-tests.log'),
                        (proof/'tests/package-final.xml','verification/package-tests.xml'),
                        (proof/'rebuild-final.json','verification/rebuild.json'),
                        (proof/'实机执行与恢复确认.md','实机执行与恢复确认.md')]:
        if (package/name).exists():raise FileExistsError('不覆盖已封入记录：'+name)
        shutil.copyfile(source,package/name)
    op['files']={str(path.relative_to(package)):sha(path) for path in sorted(package.rglob('*'))
                 if path.is_file() and path.name not in ('operation.json','approval-template.json','checksums.sha256')}
    save(package/'operation.json',op)
    save(package/'approval-template.json',dict(accepted=False,operation_sha256=sha(package/'operation.json'),risk=op['risk']))
    (package/'checksums.sha256').write_text(''.join(sha(path)+'  '+str(path.relative_to(package))+'\n'
        for path in sorted(package.rglob('*')) if path.is_file() and path.name!='checksums.sha256'))
    # 仅收紧本次新包的本地访问权限，不改旧包或外部文件。
    package.chmod(0o700)
    for p in package.rglob('*'):
        if p.is_symlink():raise ValueError('新包出现链接')
        p.chmod(0o700 if p.is_dir() or p.name.endswith('.command') else 0o600)
    archive=package.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(package.rglob('*')):
            if p.is_file():z.write(p,str(p.relative_to(package.parent)))
    archive.chmod(0o600)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC校验失败')
        if len(z.namelist())!=sum(p.is_file() for p in package.rglob('*')):raise ValueError('ZIP文件数不符')
        for name in z.namelist():
            rel=Path(name).relative_to(package.name)
            if hashlib.sha256(z.read(name)).hexdigest()!=sha(package/rel):raise ValueError('ZIP内容不一致')
    receipt=dict(schema='a7r5-libjit-offline-delivery-1',package=str(package.relative_to(WORK)),run_id=config['run_id'],
                 archive=str(archive.relative_to(WORK)),archive_bytes=archive.stat().st_size,archive_sha256=sha(archive),
                 archive_files=len(z.namelist()),zip_crc_and_all_file_hashes_verified=True,host_tests=tests,
                 host_test_xml_sha256=sha(proof/'tests/package-final.xml'),qemu_checks=9,qemu_cases=guest['cases'],
                 qemu_raw_evidence=guest['vm_evidence'],qemu_cleanup=guest['cleanup'],runtime_manifest_unchanged=True,
                 source_image_sha256_verified=static['source_image_sha256'],loader_sha256=static['library_sha256'],
                 payload=op['payload'],rebuild_identical=True,operation_sha256=sha(package/'operation.json'),
                 live_approved=False,camera_execution_verified=False,camera_io=False,sd_io=False,debug=0,
                 original_kit_unchanged=True,unknown_fixed_path_overwrite_risk_remains=True,
                 limitations=['A7R5真实USB触发未验证','QEMU仅RAM目录，无VFAT/真实多线程服务验收','错误码6不能证明固定路径不存在',
                              '写入即加载，不能先完整读回后触发','相机恢复、原配置还原、拍摄和刷回未验证'])
    receipt.update(source_and_recovery_packages_preserved=True,previous_locks_preserved=True,
                   bulk_response_bytes=233420,bulk_boundaries_expected=7)
    receipt_path=package.parent/(package.name+'-交付验收.json')
    if receipt_path.exists():raise FileExistsError('保留已有验收收据')
    save(receipt_path,receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
