"""封装八项相对偏移的固定4.17候选；仅访问本地普通文件。"""
import argparse
from functools import partial
from pathlib import Path

import container_package as packaging
from evidence_gate import verify_evidence

HERE = Path(__file__).resolve().parent
FEATURE = HERE.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--rebuild', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, default=FEATURE/'audits/relative-parameters')
    args = parser.parse_args()
    runtime, rebuild = args.runtime.absolute(), args.rebuild.absolute()
    if runtime.resolve() == rebuild.resolve():
        parser.error('主构建和独立重建必须使用不同目录')
    packaging.package(args.output.absolute(), baseline=args.baseline.absolute(),
        components_dir=runtime, components=packaging.COMPONENTS,
        patch_type=packaging.CandidatePatch, version='4.17', release_dir=HERE,
        evidence_check=partial(verify_evidence, runtime=runtime, rebuild=rebuild,
                               archive=args.evidence_dir.absolute()),
        reused=dict(reused_CPU_tests=31, reproduced_CPU_tests=0,
                    reused_QEMU_frames=0, QEMU_executed=False,
                    relative_parameters=True, tune_file_version=2,
                    upstream_native_E4_executions=48, upstream_native_packets_compared=432))


if __name__ == '__main__':
    main()
