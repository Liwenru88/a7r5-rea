#!/usr/bin/env python3
"""新目录运行整套离线回归及当前4.10签名/逐帧/独立解包审计。无设备入口。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parents[1]
ROOT=HERE.parents[3]
sys.path.insert(0,str(HERE))
import build
import patches


def save(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2,ensure_ascii=False);stream.write('\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.absolute();baseline=args.baseline.absolute()
    build.require(not out.exists() and out.parent.is_dir(),'输出必须是已有父目录下的新目录')
    build.require(not any(out.is_relative_to(p) for p in map(Path,('/dev','/Volumes','/proc','/sys'))),'禁止设备路径')
    out.mkdir(mode=0o700)
    source_before=build.implementation_sources()
    build.check_upstream(HERE/'upstream')
    release=HERE/'releases/4.10';frozen=json.loads((release/'verification.json').read_text())
    candidate=build.regular(release/'BODYDATA.DAT');public=build.regular(release/'research-public.pem')
    build.require(build.sha(candidate)==frozen['sha256'] and build.sha(public)==build.PUBLIC_SHA,'交付身份不符')
    print('运行当前全部宿主和CPU回归',flush=True)
    command=[sys.executable,'-B','-m','pytest','-p','no:cacheprovider',str(HERE/'tests'),'-q','--tb=short',
             '--junitxml='+str(out/'regression.xml')]
    env=dict(os.environ,A7R5_NATIVE12_BASELINE=str(baseline),A7R5_NATIVE12_UPSTREAM=str(HERE/'upstream'))
    result=subprocess.run(command,env=env,capture_output=True,text=True)
    (out/'regression.log').write_text(result.stdout+result.stderr)
    build.require(result.returncode==0,'回归失败，查看regression.log；不继续解包')
    suites=ET.parse(out/'regression.xml').getroot().findall('.//testsuite')
    stats={key:sum(int(s.attrib.get(key,0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    build.require(stats['failures']==stats['errors']==stats['skipped']==0,'存在失败或跳过')
    print('核对当前DAT签名、所有帧、清单并重新独立解包',flush=True)
    sys.path.insert(0,str(ROOT/'a7r5-dat-tool'))
    from a7r5dat import tool
    tool.unpack(candidate,out/'readback',public)
    manifest=json.loads((out/'readback/manifest.json').read_text())
    build.require(manifest['decryption']['plaintext_sha256']==frozen['plaintext_sha256'],'明文与冻结包不同')
    header=(out/'readback/format/header.bin').read_bytes()
    build.require(header[32:34]==b'\x10\x04','版本不是BCD 4.10')
    build.require(build.sha(out/'readback/format/updater.bin')==build.sha(baseline/'inputs/updater.img'),'原updater改变')
    sys.path.insert(0,str(HERE/'upstream/firmware/r5/src/lib'))
    from image_io import geometry
    ap,ap_report=patches.ap_patch((baseline/'patched/appFw.so').read_bytes())
    cp,cp_report=patches.cp_patch((baseline/'patched/cpapp-b.bin').read_bytes(),out)
    for partition,component,expected in [('nflasha15','appFw.so',ap),('nflasha8','cpapp-b.bin',cp)]:
        raw,*_=geometry(out/'readback/archive/0700_part_image/dev'/partition,component)
        build.require(raw==expected,'当前被测组件与DAT回读不同：'+component)
    # 按原始固件模板和冻结的原版字段契约重新生成12份地区参数，逐字节核对。
    source=HERE/'upstream/firmware/r5/src/templates/prepare_templates.py'
    templates=build.load_module(source,'runtime_template_audit')
    expected_templates,template_report=templates.build_templates(baseline/'inputs/firmware.tar',out/'templates',
        expected_archive_sha256=build.sha(baseline/'inputs/firmware.tar'))
    for member,path in expected_templates.items():
        build.require((out/'readback/archive'/member).read_bytes()==path.read_bytes(),'模板/清单不符：'+member)
    save(out/'templates.json',template_report)
    # 与封包器不同实现的OpenSSL验签。
    from signature import inspect,hashes_and_signature,openssl_verify
    signed,_,_,signature=hashes_and_signature(candidate,inspect(candidate))
    (out/'signed.sha256.bin').write_bytes(signed.digest());(out/'signature.bin').write_bytes(signature)
    openssl=openssl_verify(public,out/'signed.sha256.bin',out/'signature.bin')
    fsck=subprocess.run(['/opt/homebrew/opt/e2fsprogs/sbin/e2fsck','-fn',str(out/'readback/archive/0700_part_image/dev/nflasha15')],capture_output=True,text=True)
    (out/'e2fsck.log').write_text(fsck.stdout+fsck.stderr)
    build.require(fsck.returncode==0,'AP文件系统审计失败')
    build.require(build.implementation_sources()==source_before,'验证期间实施源发生变化')
    build.check_upstream(HERE/'upstream')
    receipt=dict(schema='native12-offline-runtime/1',status='OFFLINE_RUNTIME_VERIFIED_DEVICE_UNTESTED',version='4.10',
        upstream_commit=build.UPSTREAM_COMMIT,regression=stats,
        dat_sha256=build.sha(candidate),dat_bytes=candidate.stat().st_size,
        AP_sha256=patches.digest(ap),CP_sha256=patches.digest(cp),
        filter_sha256=build.sha(release/'R5NATIVE.BIN'),public_key_sha256=build.sha(public),
        sources=source_before,upstream_snapshot_sha256=build.sha(HERE/'upstream/UPSTREAM_SNAPSHOT.json'),
        source_lock_sha256=build.sha(HERE/'upstream/firmware/r5/sources.lock.json'),
        full_frame_validation=manifest['decryption'],signature_verified=manifest['signature_verified'],
        openssl_verification=openssl,independent_unpack_verified=True,tested_components_match_DAT=True,
        templates_rebuilt_and_compared=True,e2fsck_exit=fsck.returncode,
        firmware_changed=False,camera_io=False,hardware_model_used=False,device_tested=False,
        limitations=['原厂文件/线程/OSAL/堆/UI服务由显式替身提供','未证明真实内存并发/ISP/DMA/掉电',
                     '完整系统启动、成像、声音、画面标记及升级恢复仍需实机验收'])
    save(out/'verification.json',receipt)
    print(json.dumps({k:receipt[k] for k in ('status','regression','dat_sha256','firmware_changed','camera_io')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
