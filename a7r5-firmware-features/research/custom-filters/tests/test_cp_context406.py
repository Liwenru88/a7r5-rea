"""身份同值不能替代原别名，错误来源必须在分配执行器前拒绝。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters import cp_context406


def test_changed_source_is_rejected_before_constructing_context(monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail('来源不符时构造了CP上下文')
    monkeypatch.setattr(cp_context406,'_prepare',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        cp_context406.execute(b'changed CP',19)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        cp_context406.collect(b'changed CP')


def test_equal_profiles_in_separate_objects_do_not_satisfy_original_context():
    bank=cp_context406.BANKS[0]
    root,aggregate,state=0x9010dc00,0x9010da00,0x9010dc20
    pipe=aggregate+0x50
    fields={root:state,root+4:bank+0x624,
        pipe:state+0x38c,state+0x38c:bank+0xe3c,
        pipe+8:bank+0x648,pipe+12:0x1ef5ef4,pipe+16:bank+0xbd0,
        pipe+20:0x1ef7900,pipe+24:0x1efeb88,pipe+28:0x1eff4d8}
    class ReadOnlyContext:
        def word(self,address):return fields[address]
    machine=ReadOnlyContext()
    assert cp_context406.layout(machine,root,aggregate,bank)==pipe
    # 此前的夹具可以让两个profile值相等，但地址不同仍必须拒绝。
    fields[pipe+8]=0x9000a000
    with pytest.raises(ValueError,match='别名或所属对象被拆散'):
        cp_context406.layout(machine,root,aggregate,bank)
