"""真实分支的编码边界；当前AP/模块联验由完整DAT审计执行。"""
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters.ap_ui_hooks import branch, HOOKS


@pytest.mark.parametrize('delta,link',[(-(1<<27),False),(-4,True),(0,False),((1<<27)-4,True)])
def test_direct_branch_reconstructs_target_at_signed_boundaries(delta,link):
    origin=0x10000000
    word=struct.unpack('<I',branch(origin,origin+delta,link))[0]
    assert word>>26 == (0b100101 if link else 0b000101)
    displacement=word&0x3ffffff
    if displacement&(1<<25):displacement-=1<<26
    assert origin+displacement*4 == origin+delta


@pytest.mark.parametrize('origin,target',[(1,4),(0,5),(0,1<<27),(1<<28,(1<<28)-(1<<27)-4)])
def test_unsafe_branch_is_rejected(origin,target):
    with pytest.raises(ValueError):branch(origin,target)


def test_hook_set_has_verified_native_calls_and_all_eight_callbacks():
    assert len({h[0] for h in HOOKS}) == 41
    assert [h[0] for h in HOOKS if h[2]] == [0x16f6610,0x220a898,0x220a8c4,0x220c87c,0x220c8dc,0x2208e8c,0x220c8a0,0x1885b38,0x21f3a4c,0x21f99a4]
    assert [h[0] for h in HOOKS[16:24]] == [0x2209918+p*0x154 for p in range(8)]
    assert [h[0] for h in HOOKS[24:]] == [0x1bd18e8,0x1bd19e8,0x1bdb0b0,0x220b620,0x220b51c,0x220b708,0x220b89c,0x2209464,0x220c87c,0x220c8dc,0x2208e8c,0x220c8a0,0x1885b38,0x263d558,0x21f3608,0x21f3a4c,0x21f99a4]
