"""错误前像在执行/ELF解析前拒绝；真实原指令交错由同包集成审计验证。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters import cp_atomic,cp_release,cp_reply,cp_display


@pytest.mark.parametrize('module',[cp_atomic,cp_release,cp_reply,cp_display])
def test_changed_cp_never_reaches_elf_or_cpu(monkeypatch,module):
    def forbidden(*args,**kwargs):pytest.fail('错误CP在来源验证前执行')
    monkeypatch.setattr(module,'CpMachine',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        if module is cp_atomic:module.collect(b'changed CP',b'not ELF')
        else:module.collect(b'changed CP')
