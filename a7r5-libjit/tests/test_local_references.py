"""本地夹具必须存在、同摘要；不使用删除的目录或设备读取补齐。"""
from pathlib import Path
import pytest
from references import loader_path, LOADER_SHA256


def test_reference_library_is_local_and_exact():
    path = loader_path()
    assert path.is_file() and len(path.read_bytes()) == 233416
    assert 'analysis' not in path.relative_to(Path(__file__).resolve().parents[2]).parts


def test_wrong_fixture_rejected_without_fallback(tmp_path):
    fixture = tmp_path/'test-fixtures/libJiritsu.so'
    fixture.parent.mkdir()
    fixture.write_bytes(b'not the fixed library')
    with pytest.raises(ValueError, match='摘要或长度'):
        loader_path(tmp_path)
