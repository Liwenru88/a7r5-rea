"""验证 4.28 补丁函数的确定性、防回归约束与 4.23 / C1-C6 风险代码隔离。"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import patch_428

B427_TREE = (
    HERE.parents[1]
    / 'builds/4.27-424-planA-20261116/build-tree/a7r5-firmware-features/native24-combined'
)


def test_patch_428_transforms_427_runtime_cleanly():
    unified_c = (B427_TREE / 'runtime/unified-look.c').read_text()
    build_py = (B427_TREE / 'build.py').read_text()

    patched_u = patch_428.patch_unified_look_428(unified_c)
    patched_b = patch_428.patch_runtime_builder_428(build_py)

    assert 'if(flow.queued && flow.next_slot==slot && flow.next_row==row && !r5_tune_pending_changed(slot))return 0;' in patched_u
    assert 'if(!flow.active && !busy())pump(1);' in patched_u
    assert 'if(flow.active || busy()){flow.queued=1;flow.next_slot=slot;flow.next_row=mid();return;}' in patched_u
    for forbidden in ('confirm_target', 'sync_custom_tab', 'r5_filter_recovery_retry', 'r5_filter_e4_stalled'):
        assert forbidden not in patched_u
    assert 'apply_lens_af' in patched_b
    assert 'six_apply_ap' not in patched_b
