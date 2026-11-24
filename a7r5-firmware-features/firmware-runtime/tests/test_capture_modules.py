"""从阶段四组合包的实际组件回放 24 槽和纵横比的共享运行时。"""
import hashlib
import json
import os
from pathlib import Path
import struct

import pytest
from unicorn import arm_const as ARM

import replay
from test_runtime import assert_color


def test_capture_and_native24_share_boot_pages_and_keep_independent_selections(monkeypatch):
    path = os.environ.get('A7R5_PHASE4_WORK')
    if not path:
        pytest.skip('需要阶段四组合包回读与捕获组件回执')
    phase = Path(path)
    folder = phase / 'look24-af-aspect-readback/components'
    ap = (folder / 'usr/lib/appFw.so').read_bytes()
    cp = (folder / 'cpapp-b.bin').read_bytes()
    proof = json.loads((phase / 'combined-runtime/build.json').read_text())
    assert hashlib.sha256(ap).hexdigest() == proof['AP']['target_sha256']
    assert hashlib.sha256(cp).hexdigest() == proof['CP_sha256']
    def start(raw):
        core = replay.CP(raw).cpu
        core.mem_map(0x3e42000, 4096)
        core.reg_write(ARM.UC_ARM_REG_SP, 0x3218000)
        core.emu_start(0x108398, 0x108728, count=5000000)
        assert core.reg_read(ARM.UC_ARM_REG_PC) == 0x108728
        root, = struct.unpack('<I', core.mem_read(0x108f1c, 4))
        return core, root

    _, original_root = start(replay.cp_raw)
    boot, root = start(cp)
    assert root == original_root
    for page in (0x118000, 0x1195000, 0x1196000):
        first, = struct.unpack('<I', boot.mem_read(root + (page >> 20) * 4, 4))
        pte, = struct.unpack('<I', boot.mem_read((first & ~1023) + ((page >> 12) & 255) * 4, 4))
        assert first & 3 == 1 and pte & 3 == 2 and pte & ~4095 == page

    monkeypatch.setattr(replay, 'candidate', (ap, *replay.candidate[1:]))
    monkeypatch.setattr(replay, 'cp_raw', cp)
    monkeypatch.setitem(replay.namespace, 'AP_SHA', proof['AP']['target_sha256'])
    monkeypatch.setitem(replay.namespace, 'CP_SHA', proof['CP_sha256'])
    recipe = replay.recipe()
    run = replay.Replay(cards={'A:/R5NATIVE.BIN': recipe})
    run.boot()
    assert run.ap.call('r5_filter_available_mask') & 0xffffff == 0xffffff
    run.ap.stub(0x1c61d14, lambda _ap: 0)
    set_ratio = proof['AP']['symbols']['r5_aspect_set']
    selection = proof['AP']['selection']
    for slot in range(1, 25):
        ratio = 9 if slot % 2 else 0
        run.ap.call(set_ratio, ratio)
        run.choose(slot)
        run.service()
        assert run.selected() == (slot, slot, slot)
        assert run.ap.read(selection, 1) == bytes([ratio])
        assert_color(run, slot)
    assert run.files['R5NATIVE.BIN'] == recipe
