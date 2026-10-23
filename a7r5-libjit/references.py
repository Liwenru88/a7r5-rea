"""定位项目内已封存的参考材料；不回退到已删除的研究目录。"""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCE = HERE / 'packages/libjit-info-20261021-02'
LOADER_SHA256 = 'ea2d9ba9dbeb56fc11ad88be7b5c30b6b237f8ccc55ce9f24c02546eb0ba07b1'


def loader_path(root=None):
    root = HERE if root is None else Path(root)
    local = root / 'test-fixtures/libJiritsu.so'
    path = local if local.exists() else root / 'packages/libjit-info-20261021-02/test-fixtures/libJiritsu.so'
    if path.is_symlink() or not path.is_file():
        raise ValueError('缺少项目内的固定加载库夹具')
    raw = path.read_bytes()
    if len(raw) != 233416 or hashlib.sha256(raw).hexdigest() != LOADER_SHA256:
        raise ValueError('加载库夹具摘要或长度变化')
    return path
