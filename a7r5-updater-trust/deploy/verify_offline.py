#!/usr/bin/env python3
"""离线构建、普通文件故障注入、模拟USB调度和可选无网QEMU验证。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
import build


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--qemu-root',type=Path)
    args=parser.parse_args()
    output=build.HERE/'verification'/('offline-'+uuid.uuid4().hex)
    output.mkdir(parents=True,mode=0o700)
    production=build.prepare(args.source,build.HERE/'profile-historical.json','blank-512')
    fixture=build.prepare(args.source,build.HERE/'profile-historical.json','blank-512',fixture=True,output_root=output)
    print('PRODUCTION '+str(production),flush=True)
    print('FIXTURE '+str(fixture),flush=True)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',A7R5_TRUST_TEST_RUN=str(production),A7R5_TRUST_FIXTURE_RUN=str(fixture),A7R5_TRUST_ORIGINAL=str(args.source.resolve()))
    command=[sys.executable,'-B','-m','pytest','-q',str(build.HERE/'tests'),'--junitxml='+str(output/'tests.xml')]
    result=subprocess.run(command,capture_output=True,text=True,env=env,timeout=180)
    (output/'tests.log').write_text(result.stdout+result.stderr);print(result.stdout,flush=True)
    report=dict(status='passed' if result.returncode==0 else 'failed',camera_IO=False,SD_IO=False,
        production=str(production),fixture=str(fixture),tests_returncode=result.returncode,
        approval_created=False,manifest_sha256=build.digest(production/'manifest.json'))
    if result.returncode==0 and args.qemu_root:
        from guest_check import verify
        report['QEMU']=verify(args.qemu_root,production,fixture,args.source.resolve(),output/'guest')
        if report['QEMU']['status']!='passed':report['status']='failed'
    else:report['QEMU']='未运行；不宣称AArch64加载通过'
    build.save(output/'result.json',report)
    print(json.dumps(dict(report_directory=str(output),**report),ensure_ascii=False,indent=2))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
