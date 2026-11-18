"""验证 4.28 补丁函数的确定性、防回归约束与 4.23 / C1-C6 风险代码隔离。"""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import patch_428

B427_TREE = (
    HERE.parents[1]
    / 'builds/4.27-424-planA-20261116/build-tree/a7r5-firmware-features/native24-combined'
)
ARCHIVE_428_TREE = (
    HERE / 'source-tree/build-tree/a7r5-firmware-features/native24-combined'
)
PATCH_RECEIPT = HERE / 'source-tree/patch-428.json'


def _assert_428_invariants(unified_text: str, build_text: str) -> None:
    assert 'if(flow.queued && flow.next_slot==slot && flow.next_row==row && !r5_tune_pending_changed(slot))return 0;' in unified_text
    assert 'if(!flow.active && !busy())pump(1);' in unified_text
    assert 'if(flow.active || busy()){flow.queued=1;flow.next_slot=slot;flow.next_row=mid();return;}' in unified_text
    for forbidden in ('confirm_target', 'sync_custom_tab', 'r5_filter_recovery_retry', 'r5_filter_e4_stalled'):
        assert forbidden not in unified_text
    assert 'apply_lens_af' in build_text
    assert 'six_apply_ap' not in build_text


def test_patch_428_archive_matches_receipt_and_invariants():
    receipt = json.loads(PATCH_RECEIPT.read_text())
    unified_c = (ARCHIVE_428_TREE / 'runtime/unified-look.c').read_text()
    build_py = (ARCHIVE_428_TREE / 'build.py').read_text()

    assert hashlib.sha256(unified_c.encode()).hexdigest() == receipt['patched_files']['runtime/unified-look.c']['after_sha256']
    assert hashlib.sha256(build_py.encode()).hexdigest() == receipt['patched_files']['build.py']['after_sha256']
    _assert_428_invariants(unified_c, build_py)

    if B427_TREE.is_dir():
        old_u = (B427_TREE / 'runtime/unified-look.c').read_text()
        old_b = (B427_TREE / 'build.py').read_text()
        assert patch_428.patch_unified_look_428(old_u) == unified_c
        assert patch_428.patch_runtime_builder_428(old_b) == build_py
