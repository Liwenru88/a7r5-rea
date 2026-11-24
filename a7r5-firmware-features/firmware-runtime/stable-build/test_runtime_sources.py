"""验证当前稳定版保留的运行时行为约束。"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME_TREE = HERE / 'source-tree/a7r5-firmware-features/firmware-runtime'


def test_stable_sources_preserve_debounce_and_lens_support():
    unified_text = (RUNTIME_TREE / 'runtime/unified-look.c').read_text()
    build_text = (RUNTIME_TREE / 'build.py').read_text()
    assert 'if(flow.queued && flow.next_slot==slot && flow.next_row==row && !r5_tune_pending_changed(slot))return 0;' in unified_text
    assert 'if(!flow.active && !busy())pump(1);' in unified_text
    assert 'if(flow.active || busy()){flow.queued=1;flow.next_slot=slot;flow.next_row=mid();return;}' in unified_text
    for forbidden in ('confirm_target', 'sync_custom_tab', 'r5_filter_recovery_retry', 'r5_filter_e4_stalled'):
        assert forbidden not in unified_text
    assert 'apply_lens_af' in build_text
    assert 'six_apply_ap' not in build_text
