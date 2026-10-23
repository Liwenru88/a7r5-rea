#!/usr/bin/env python3
"""A7R5两类实施材料入口；prepare/check/test不访问相机或原始卡。"""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True

from tools.common import BASE, approve, consent_phrase, execute, load


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare-dump', help='仅离线构建新一次性转存操作')
    p.add_argument('--operation', type=Path, required=True)
    p.add_argument('--profile', choices=('standard', 'extended'), default='standard',
                   help='standard默认19项明文/启动区；extended显式选择37项双视图')
    p = sub.add_parser('prepare-root', help='仅离线构建一次固定shell脚本任务')
    p.add_argument('--operation', type=Path, required=True)
    p.add_argument('--script', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=60)
    p = sub.add_parser('prepare-collect', help='仅离线绑定本包新转存会话的精简读取操作')
    p.add_argument('--dump-operation', type=Path, required=True)
    p.add_argument('--operation', type=Path, required=True)
    p.add_argument('--safety', required=True)
    p = sub.add_parser('confirm-recovery', help='仅观察主机元数据一次，并记录人工屏幕确认')
    p.add_argument('--operation', type=Path, required=True)
    p.add_argument('--screen-normal', action='store_true', required=True)
    p = sub.add_parser('classify-images', help='只读校验本机37原件，创建19+18分类链接和索引')
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    for command in ('check', 'approve', 'execute'):
        p = sub.add_parser(command)
        p.add_argument('--operation', type=Path, required=True)
        if command == 'approve':
            p.add_argument('--accept', required=True)
    args = parser.parse_args(argv)
    if args.action == 'prepare-dump':
        from tools.workflows import prepare_dump
        value = prepare_dump(args.operation, args.profile)
    elif args.action == 'prepare-root':
        from tools.root import prepare_root
        value = prepare_root(args.operation, args.script, args.timeout)
    elif args.action == 'prepare-collect':
        from tools.workflows import prepare_collect
        value = prepare_collect(args.dump_operation, args.operation, args.safety)
    elif args.action == 'approve':
        value = approve(args.operation, args.accept)
    elif args.action == 'confirm-recovery':
        from tools.workflows import confirm_recovery
        value = confirm_recovery(args.operation, args.screen_normal)
    elif args.action == 'classify-images':
        from tools.classify import verify_images, classify_verified
        report = args.output.parent / (args.output.name + '.precheck.json')
        proof = BASE / 'historical/all-37-final.json'
        verify_images(args.source, proof, report)
        value = classify_verified(args.source, proof, report, args.output)
    elif args.action == 'execute':
        value = execute(args.operation)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value.get('execution_succeeded') is True else 1
    else:
        value = load(args.operation)
    if args.action in ('check', 'prepare-root', 'prepare-dump', 'prepare-collect'):
        value = {key: value[key] for key in ('kind', 'run_id', 'output', 'risk_statement',
                                           'dump_profile', 'image_count', 'image_bytes') if key in value}
        value.update(offline_only=True, consent_phrase=consent_phrase(args.operation))
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print(f'停止：{type(exc).__name__}: {exc}；不要删除锁、自动重试或断电。', file=sys.stderr)
        raise SystemExit(2)
