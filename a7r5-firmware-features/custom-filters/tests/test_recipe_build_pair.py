"""同一完整配方能力不能混用旧端构建；只读解析，不运行目标。"""
import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / 'experiments/packaging406/candidate_preflight.py'


@pytest.fixture(scope='module')
def pairing():
    spec=importlib.util.spec_from_file_location('pairing_contract',PATH)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.recipe_pairing


def test_legacy_and_explicit_pairing(pairing):
    assert pairing({}, {'recipe_bridge_enabled':False}, {}) is False
    assert pairing(*[{'recipe_bridge_enabled':True} for _ in range(3)]) is True


@pytest.mark.parametrize('reports', [
    ({'recipe_bridge_enabled':True}, {}),
    ({'recipe_bridge_enabled':False}, {'recipe_bridge_enabled':True}),
    ({'recipe_bridge_enabled':1}, {'recipe_bridge_enabled':True}),
    ({'recipe_bridge_enabled':'true'},),
    (),
])
def test_mixed_or_malformed_pairing_is_rejected(pairing,reports):
    with pytest.raises(ValueError):
        pairing(*reports)
