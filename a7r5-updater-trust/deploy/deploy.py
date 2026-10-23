#!/usr/bin/env python3
"""默认仅离线准备／检查；实机必须另行批准并显式执行。"""
import argparse
import json
from pathlib import Path
import sys
import build


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare')
    prepare.add_argument('--source',required=True,type=Path)
    prepare.add_argument('--profile',required=True,type=Path)
    prepare.add_argument('--preload-baseline',required=True,choices=['blank-512','installed-boot-hook'])
    for name in ('check','authorize','terminal','execute','status','confirm-screen'):
        sub=commands.add_parser(name);sub.add_argument('--run',required=True,type=Path)
        if name=='authorize':sub.add_argument('--accept',required=True)
        if name=='execute':sub.add_argument('--device-io',action='store_true')
        if name=='confirm-screen':sub.add_argument('--screen-normal',action='store_true')
    args=parser.parse_args()
    try:
        if args.command=='prepare':
            directory=build.prepare(args.source,args.profile,args.preload_baseline)
            result=dict(directory=str(directory),manifest_sha256=build.digest(directory/'manifest.json'),
                approval_phrase='APPROVE-'+build.digest(directory/'manifest.json')[:20],camera_IO=False,
                current_device_binding_verified=False,warning='未创建批准，尚不允许实机执行')
        elif args.command=='check':
            manifest=build.check(args.run);result=dict(verified=True,run_id=manifest['run_id'],camera_IO=False)
        elif args.command=='status':
            result=json.loads(build.regular(args.run/'result/result.json').read_text())
        else:
            import controller
            if args.command=='authorize':result=controller.authorize(args.run,args.accept)
            elif args.command=='terminal':result=controller.terminal(args.run)
            elif args.command=='confirm-screen':result=controller.confirm_screen(args.run,args.screen_normal)
            else:
                result=controller.execute(args.run,args.device_io)
                print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['execution_succeeded'] else 3
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (Exception,KeyboardInterrupt) as error:
        print('停止：'+type(error).__name__+': '+str(error),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
