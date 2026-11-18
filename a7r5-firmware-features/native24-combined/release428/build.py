"""封装 4.27 稳定基线加 lens-af-compat 与轻量防抖的 4.28 候选。"""
import argparse
from functools import partial
from pathlib import Path

import container_package as packaging
from evidence_gate import verify_evidence

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--rebuild', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, default=HERE.parent / 'audits/relative-parameters')
    parser.add_argument('--base-tree', type=Path)
    parser.add_argument('--build-tree', type=Path)
    parser.add_argument('--patch-receipt', type=Path)
    args = parser.parse_args()

    provenance = None
    given = (args.base_tree, args.build_tree, args.patch_receipt)
    if any(given):
        if not all(given):
            parser.error('--base-tree／--build-tree／--patch-receipt 必须同时提供')
        provenance = dict(
            base_tree=args.base_tree.absolute(),
            build_tree=args.build_tree.absolute(),
            patch_receipt=args.patch_receipt.absolute(),
        )

    packaging.package(
        args.output.absolute(),
        baseline=args.baseline.absolute(),
        components_dir=args.runtime.absolute(),
        components=packaging.COMPONENTS,
        version='4.28',
        release_dir=HERE,
        evidence_check=partial(
            verify_evidence,
            runtime=args.runtime.absolute(),
            rebuild=args.rebuild.absolute(),
            archive=args.evidence_dir.absolute(),
        ),
        reused=dict(
            base_version='4.27',
            scope_patch=True,
            factory_six=False,
            lens_af_compat=True,
            lightweight_debounce=True,
            fl23_raw_12=True,
            tune_slot_full_and_reset_lock=True,
            avcam_unchanged=True,
            wbi_marker='WBI3',
            usr_modified_files=3,
            QEMU_executed=False,
        ),
        provenance=provenance,
    )


if __name__ == '__main__':
    main()
