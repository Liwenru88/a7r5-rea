"""从 ILCE-7RM5 原厂升级包选择模块，离线构建与回读。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

from core.plan import make_plan, read_json, require_base


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('plan', 'build'):
        command = commands.add_parser(name)
        command.add_argument('--config', type=Path, required=True)
        command.add_argument('--base', type=Path, required=name == 'build')
        if name == 'build':
            command.add_argument('--output', type=Path, required=True)
            command.add_argument('--version', required=True)
    check = commands.add_parser('verify')
    check.add_argument('--base', type=Path, required=True)
    check.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == 'verify':
            from core.package import verify
            result = verify(args.base, args.bundle)
        else:
            plan = make_plan(read_json(args.config))
            if args.command == 'build':
                from core.package import build
                result = build(args.base, plan, args.output, args.version)
            else:
                if args.base:
                    require_base(args.base, plan)
                result = plan
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'构建工程校验失败：{error}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
