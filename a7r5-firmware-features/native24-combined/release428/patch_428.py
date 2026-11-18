"""4.28 补丁：在 4.27 稳定基线上合入镜头 AF 兼容（lens-af-compat）与轻量防抖保护。"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from stability import replace_exact


def patch_unified_look_428(source: str) -> str:
    """在 4.27 unified-look.c 上合入无阻塞轻量防抖，严禁引入 4.23 延迟确认状态机。"""
    forbidden = ('confirm_target', 'sync_custom_tab', 'r5_filter_recovery_retry', 'r5_filter_e4_stalled')
    for token in forbidden:
        if token in source:
            raise ValueError(f'输入源码包含已剔除的 4.23 改动：{token}')
    if '[微调已满]' not in source:
        raise ValueError('输入源码缺少 4.27 微调容量提示补丁')

    old_apply = (
        '    if(flow.active && flow.slot==slot && flow.row==row && !r5_tune_pending_changed(slot)){\n'
        '        flow.queued=0;n12_last_status=1;return 0;\n'
        '    }\n'
        '    flow.queued=1;flow.next_slot=slot;flow.next_row=row;pump(1);'
    )
    new_apply = (
        '    if(flow.active && flow.slot==slot && flow.row==row && !r5_tune_pending_changed(slot)){\n'
        '        flow.queued=0;n12_last_status=1;return 0;\n'
        '    }\n'
        '    if(flow.queued && flow.next_slot==slot && flow.next_row==row && !r5_tune_pending_changed(slot))return 0;\n'
        '    flow.queued=1;flow.next_slot=slot;flow.next_row=row;\n'
        '    if(!flow.active && !busy())pump(1);'
    )
    source = replace_exact(source, old_apply, new_apply, 1)

    old_tune = (
        'static void tune_changed(void){\n'
        '    tune_refresh=1;flow.failed=0;tabs.browse=0;\n'
        '    if(custom())(void)apply(mid()-FIRST+1);\n'
        '}'
    )
    new_tune = (
        'static void tune_changed(void){\n'
        '    tune_refresh=1;flow.failed=0;tabs.browse=0;\n'
        '    if(custom()){\n'
        '        unsigned slot=mid()-FIRST+1;\n'
        '        if(flow.active || busy()){flow.queued=1;flow.next_slot=slot;flow.next_row=mid();return;}\n'
        '        (void)apply(slot);\n'
        '    }\n'
        '}'
    )
    source = replace_exact(source, old_tune, new_tune, 1)
    return source


def patch_runtime_builder_428(source: str) -> str:
    """在 4.27 build.py 基线上合入 lens-af-compat（仅 CP .text 安全区）。"""
    source = replace_exact(
        source,
        "    RAW_FL23 = HERE.parent / 'look-fl2-fl3/raw'\n",
        "    RAW_FL23 = HERE.parent / 'look-fl2-fl3/raw'\n"
        "    LENS_AF = HERE.parent / 'lens-af-compat/src'\n",
        1,
    )
    source = replace_exact(
        source,
        "    helpers += [RAW_FL23 / name for name in ('native.py', 'raw_alternatives.S')]\n",
        "    helpers += [RAW_FL23 / name for name in ('native.py', 'raw_alternatives.S')]\n"
        "    helpers += [LENS_AF / name for name in ('lens_af.py', 'lens_af.S')]\n",
        1,
    )
    old_cp = (
        "    raw_looks = load(RAW_FL23 / 'native.py', 'native24_raw_looks')\n"
        "    final_cp, record['raw_alternatives'] = raw_looks.apply(cp_base, output / 'raw-alternatives',\n"
        "                                                           source_sha256=patches.digest(cp_base))"
    )
    new_cp = (
        "    raw_looks = load(RAW_FL23 / 'native.py', 'native24_raw_looks')\n"
        "    cp_raw, record['raw_alternatives'] = raw_looks.apply(cp_base, output / 'raw-alternatives',\n"
        "                                                        source_sha256=patches.digest(cp_base))\n"
        "    lens = load(LENS_AF / 'lens_af.py', 'native24_lens_af')\n"
        "    final_cp, record['lens_AF'] = lens.apply_lens_af(cp_raw, patches, cp_folder, source_sha=patches.digest(cp_raw))"
    )
    source = replace_exact(source, old_cp, new_cp, 1)
    return source
