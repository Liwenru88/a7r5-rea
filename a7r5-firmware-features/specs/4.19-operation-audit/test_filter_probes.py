"""4.19 异常恢复操作审计；仅执行解包组件及受控外部服务。"""
import json
import os
from pathlib import Path
import sys

ROOT = Path(os.environ['R5_AUDIT_ROOT'])
sys.path.insert(0, str(ROOT / 'a7r5-firmware-features/native24-combined/tests'))
from test_stability import selected13


def test_observe_same_group_retry_after_recovery_budget_exhausted():
    r = selected13()
    r.fail_refresh = True
    r.choose(24)
    r.service()
    for _ in range(32):
        r.ms += 1000
        r.service()
    assert r.ap.call('r5_filter_command_state') == 5
    assert r.ap.call('r5_filter_recovering') == 0
    r.fail_refresh = False
    calls = []
    r.ap.stub('n12_stock_dispatch', lambda a: calls.append(a.arg(2)) or 1)
    r.ap.call('n12_dispatch', r.controller, 0, 0x201000c)
    for _ in range(3):
        r.ms += 1000
        r.service()
    after_retry = r.ap.call('r5_filter_command_state')
    before_fallback = r.selected()
    assert after_retry == 5 and before_fallback[0] == 13 and not calls
    r.native_target(0x84d)
    r.service()
    r.service()
    assert r.selected() == (0, 0, 0) and r.native == 1
    r.choose(24)
    r.service()
    assert r.selected() == (24, 24, 24)
    print(json.dumps({'finding': 'FILTER-RECOVERY-RETRY',
                     'after_backend_recovers_and_center_retry': after_retry,
                     'selected_before_factory_roundtrip': before_fallback,
                     'factory_roundtrip_then_retry': r.selected()}, ensure_ascii=False))
