"""Mac 本地检查、待审批脚本生成及普通镜像取回入口。"""

import argparse
import json
from pathlib import Path
import sys

from .core import build_dump_script, card_layout, parse_partitions, validate_inventory
from .images import extract_run, regular_file


def main(argv=None):
    parser = argparse.ArgumentParser(description="A7R5 离线准备、固定读取与单独批准的受限转存；不提供格式化入口")
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("offline-check", help="只检查本机依赖和参考 ELF，不枚举 USB")
    prepare = sub.add_parser("prepare-dump", help="离线构建固定任务载荷与未批准的候选包")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--capacity-bytes", type=int, required=True)
    prepare.add_argument("--run-id")
    dump = sub.add_parser("service-dump", help="仅在材料和实际卡已单独批准后执行一次受限转存")
    dump.add_argument("--bundle", type=Path, required=True)
    dump.add_argument("--approval", type=Path, required=True)
    dump.add_argument("--output", type=Path, required=True)
    live = sub.add_parser("service-readonly", help="实机第一阶段：认证、固定文件读取、请求退出")
    live.add_argument("--output", type=Path, required=True)
    live.add_argument("--approve-service-mode", action="store_true", required=True)
    live.add_argument("--transport", choices=("libusb", "native-host"), default="libusb")
    preflight = sub.add_parser("service-preflight", help="2A：仅认证、六个固定文件只读预检、请求退出")
    preflight.add_argument("--output", type=Path, required=True)
    preflight.add_argument("--approve-service-mode", action="store_true", required=True)
    supplement = sub.add_parser("service-supplement", help="五路径最小补证：三个固定对照通过后读取两个预加载路径")
    supplement.add_argument("--output", type=Path, required=True)
    supplement.add_argument("--approve-service-mode", action="store_true", required=True)
    inventory = sub.add_parser("inventory", help="解析已保存的 /proc/partitions 文本")
    inventory.add_argument("file", type=Path)
    inventory.add_argument("--views", choices=("both", "plaintext"), default="both")
    plan = sub.add_parser("plan", help="输出待审批的容量方案与相机脚本，不执行")
    plan.add_argument("inventory", type=Path)
    plan.add_argument("--capacity-bytes", type=int, required=True)
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--card-device", required=True)
    fetch = sub.add_parser("extract", help="从普通 ext2 分区镜像文件取回并校验，不读取设备节点")
    fetch.add_argument("image", type=Path)
    fetch.add_argument("destination", type=Path)
    fetch.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action in (None, "offline-check"):
            from .environment import offline_check
            result = offline_check()
        elif args.action == "prepare-dump":
            from .bundle import prepare_bundle
            result = prepare_bundle(args.output, args.capacity_bytes, args.run_id)
        elif args.action == "service-dump":
            from .restricted import run_dump_session
            result = run_dump_session(args.bundle, args.approval, args.output)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if (result.get("card_unmounted_verified") and result.get("ordinary_identity_restored")
                         and "failure" not in result) else 1
        elif args.action in ("service-readonly", "service-preflight", "service-supplement"):
            from .session import run_session
            if args.action in ("service-preflight", "service-supplement"):
                profile = "supplement" if args.action == "service-supplement" else "preflight"
                result = run_session(args.output, "libusb", profile=profile)
            else:
                result = run_session(args.output, args.transport)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.action == "service-supplement":
                collected = result["supplement"]
                return 0 if (collected["all_files_read"] and collected["controls_match_baseline"]
                             and result["ordinary_identity_restored"] and "failure" not in result) else 1
            if args.action == "service-preflight":
                collected = result["preflight"]
                return 0 if (collected["all_files_read"] and collected["version_matches_stage1"] is True
                             and result["ordinary_identity_restored"] and "failure" not in result) else 1
            return 0 if result["communication_verified"] else 1
        elif args.action == "inventory":
            result = parse_partitions(regular_file(args.file).read_text(), args.views)
        elif args.action == "plan":
            value = validate_inventory(json.loads(regular_file(args.inventory).read_text()))
            result = {"execution_enabled": False,
                      "card_layout": card_layout(args.capacity_bytes, value["total_bytes"]),
                      "camera_script_for_review": build_dump_script(value, args.run_id, args.card_device),
                      "pending": ["核对实际机型、固件、分区和卡映射",
                                  "审批预加载写入/DEBUG 的具体步骤及恢复边界",
                                  "确认备用卡物理设备后审批格式化；本工具不执行这些操作"]}
        else:
            result = extract_run(args.image, args.destination, args.run_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"准备/验证失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
