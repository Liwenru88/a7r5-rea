"""普通共享声音也须保留本次构建符号，不能借历史组件跑回归。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import package


def test_native_build_evidence_without_variants(tmp_path):
    scratch = tmp_path / 'scratch'
    output = tmp_path / 'bundle'
    (scratch / 'native24/work').mkdir(parents=True)
    (scratch / 'native24/build.json').write_text('{}')
    (scratch / 'native24/work/symbols.json').write_text('{"fresh":true}')
    output.mkdir()
    package.preserve_build_evidence(scratch, output, {'native24': {}})
    assert (output / 'build-evidence/native24/work/symbols.json').read_text() == '{"fresh":true}'
    assert not (output / 'build-evidence/capture').exists()
