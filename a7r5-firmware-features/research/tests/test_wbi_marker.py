"""WBI 标记契约：仅接受固定原厂前像，不清空首扇区。"""
import hashlib
import importlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def transform(source, output, source_hash, target_hash):
    # 导入现存生产模块，先用可观察结果保护封包路径。
    native = importlib.import_module('core.native24')
    native.prepare_wbi_marker(source, output, source_sha256=source_hash,
                              target_sha256=target_hash)


def fixture(tmp_path):
    raw = b'WBI2' + bytes(range(256)) * 4
    target = b'WBI3' + raw[4:]
    source = tmp_path / 'stock.img'
    source.write_bytes(raw)
    return source, tmp_path / 'result.img', raw, target


def test_marker_changes_only_one_byte(tmp_path):
    source, output, raw, target = fixture(tmp_path)
    transform(source, output, hashlib.sha256(raw).hexdigest(), hashlib.sha256(target).hexdigest())
    result = output.read_bytes()
    assert result == target
    assert source.read_bytes() == raw
    assert [i for i, (a, b) in enumerate(zip(raw, result)) if a != b] == [3]
    assert result[4:] == raw[4:]


@pytest.mark.parametrize('bad', [bytes(1028), b'WBI3' + bytes(1024), b'WBI2'])
def test_bad_preimage_never_publishes(tmp_path, bad):
    source = tmp_path / 'bad.img'
    source.write_bytes(bad)
    output = tmp_path / 'result.img'
    with pytest.raises(ValueError):
        transform(source, output, hashlib.sha256(bad).hexdigest(), '0' * 64)
    assert not output.exists()


def test_wrong_target_hash_never_publishes(tmp_path):
    source, output, raw, _ = fixture(tmp_path)
    with pytest.raises(ValueError):
        transform(source, output, hashlib.sha256(raw).hexdigest(), '0' * 64)
    assert not output.exists()


def test_wbi_recipe_is_in_every_native_source_snapshot():
    native = importlib.import_module('core.native24')
    plan = {'native24': {'companion': None}}
    assert native.MATERIALS / 'recipes.json' in native.resources(plan)


def test_refuses_overwriting_output(tmp_path):
    source, output, raw, target = fixture(tmp_path)
    output.write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        transform(source, output, hashlib.sha256(raw).hexdigest(), hashlib.sha256(target).hexdigest())
    assert output.read_bytes() == b'keep'
