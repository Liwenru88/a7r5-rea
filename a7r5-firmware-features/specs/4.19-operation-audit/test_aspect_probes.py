"""4.19 最终组件只读审计；断言用于记录现状，不表示缺陷已修复。"""
import json
import os
from pathlib import Path
import struct
import sys

ROOT = Path(os.environ['R5_AUDIT_ROOT'])
sys.path.insert(0, str(ROOT / 'a7r5-firmware-features/photo-aspect-ratios/src'))
from test_ap_state import ap_image, menu, disk  # noqa: F401
from test_ap import SELECTION
from test_geometry import DATA


def test_observe_transient_restore_failure_never_retries(disk):
    fixture, files, _, restart = disk
    cpu, base, call, get, _, _, callback, word, _ = fixture
    saved = struct.pack('<4I', 0x41533552, 1, 9, 0xfffffff6)
    files['r5_aspect10_v1.dat'] = saved
    restart()
    attempts = []
    ready = [False]
    callback(DATA + 0x8000, lambda: attempts.append(ready[0]) or (100 if ready[0] else -1))
    first = call(get)
    ready[0] = True
    later = [call(get) for _ in range(3)]
    status = struct.unpack('<i', cpu.mem_read(base + SELECTION + 0x1ac, 4))[0]
    assert first == 0 and later == [0, 0, 0] and attempts == [False]
    assert status == -2 and files['r5_aspect10_v1.dat'] == saved
    print(json.dumps({'finding': 'ASPECT-RESTORE-RETRY', 'initial': first,
                     'after_storage_recovers': later, 'open_attempts': len(attempts),
                     'persist_status': status}, ensure_ascii=False))


def test_observe_aspect_save_failure_is_invisible_to_selection(disk):
    fixture, files, fault, restart = disk
    cpu, base, call, get, set_, commit, _, _, _ = fixture
    call(commit, 0x1605)
    saved = files['r5_aspect10_v1.dat']
    fault['write'] = True
    call(set_, 8)
    call(commit, 0x1604)
    current = call(get)
    status = struct.unpack('<i', cpu.mem_read(base + SELECTION + 0x1ac, 4))[0]
    assert current == 8 and status == -6 and files['r5_aspect10_v1.dat'] == saved
    fault.clear()
    restart()
    after_restart = call(get)
    assert after_restart == 9
    print(json.dumps({'finding': 'ASPECT-SAVE-FEEDBACK', 'menu_choice': current,
                     'persist_status': status, 'after_restart': after_restart}, ensure_ascii=False))
