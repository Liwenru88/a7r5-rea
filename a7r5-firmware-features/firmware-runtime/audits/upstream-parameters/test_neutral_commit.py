"""检查首次原生基准发布失败，以及发布时收到新调参输入的独立风险。"""
from pathlib import Path
import struct
import sys

FEATURE = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(FEATURE/'tests'))

from test_native_e4_parameters import NativeE4Replay
from test_parameters import display_custom, parameters
from replay import recipe


def test_native_baseline_rename_failure_and_concurrent_edit_preserve_committed_state():
    r=NativeE4Replay()
    r.native_source_values=(2,-1,3,1,-2,6,2,4)
    r.boot()
    display_custom(r,1)
    r.fail_tune_publish=True
    r.choose(1)
    r.service()
    assert r.selected()==(0,0,0)
    assert 'R5TUNE.BIN' not in r.files
    r.choose(1)
    r.service()
    assert r.selected()==(1,1,1)
    assert parameters(r,1)==r.native_source_values
    assert r.files['R5NATIVE.BIN']==recipe()

    display_custom(r,2)
    injected=[]
    original=r.native_transport

    def edit_during_transport(ap):
        packet=ap.read(ap.arg(1),12)
        result=original(ap)
        if not injected and struct.unpack_from('<H',packet,2)[0]==0x4030:
            injected.append(True)
            context=ap.cpu.context_save()
            try:
                assert ap.call('r5_tune_edit',2,0,-3)==0
            finally:
                ap.cpu.context_restore(context)
        return result

    r.ap.stub(0x16dafc0,edit_during_transport)
    r.choose(2)
    r.service()
    assert injected and r.selected()==(2,2,2)
    assert r.cp_values()==r.native_source_values
    desired=(-3,*r.native_source_values[1:])
    assert parameters(r,2)==desired, '发布原生基准不能覆盖事务中收到的新工作值'
    r.choose(2)
    r.service()
    assert r.cp_values()==desired
    assert 'R5RECOV.BIN' not in r.files and 'R5TREC.BIN' not in r.files
    r.record('native-baseline-failure-and-concurrent-edit')
