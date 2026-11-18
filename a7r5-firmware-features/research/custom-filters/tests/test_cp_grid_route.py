"""原控制器入口的前像和候选门槛；原指令行为由同包集成审计验证。"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7filters import cp_grid_route


def test_controller_source_checked_before_machine_or_candidate(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('错误前像在身份核对前进入原CP')
    monkeypatch.setattr(cp_grid_route, 'CpMachine', forbidden)
    with pytest.raises(ValueError, match='CP不是已锁定4.06'):
        cp_grid_route.collect(b'changed CP', b'')


@pytest.mark.parametrize('candidate', [b'\0'*1214, b'\0'*1216, b'\x40'*1215, b'\xbf'*1215])
def test_controller_rejects_invalid_grid_before_execution(monkeypatch, candidate):
    # 只替换摘要门槛以覆盖候选拒绝顺序；不执行合成CP。
    monkeypatch.setattr(cp_grid_route, 'require_source', lambda *args: None)
    def forbidden(*args, **kwargs):
        pytest.fail('非法候选进入原CP执行器')
    monkeypatch.setattr(cp_grid_route, 'CpMachine', forbidden)
    with pytest.raises(ValueError, match='1215字节七位网格'):
        cp_grid_route.collect(b'not firmware', candidate)
