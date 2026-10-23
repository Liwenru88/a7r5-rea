"""独立重建16种补丁并对比既有交付物；不导入USB或执行设备动作。"""
import hashlib
import json
from pathlib import Path
import tempfile
import prepare

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify():
    baseline = json.loads((ROOT/'verification/feature-build.json').read_text())['combinations']
    shipped = ROOT/'dist/final/A7R5 Studio.app/Contents/Resources/engine/feature-patches'
    assert baseline == json.loads((shipped/'manifest.json').read_text())
    with tempfile.TemporaryDirectory(prefix='a7r5-builder-check-') as folder:
        temporary = Path(folder).resolve()
        prepare.feature_patches(engine=temporary/'engine', receipt=temporary/'receipt.json')
        rebuilt = json.loads((temporary/'receipt.json').read_text())['combinations']
        assert rebuilt == baseline, '组合摘要或AP/CP目标变化'
        for key, row in baseline.items():
            path = temporary/'engine/feature-patches'/(key+'.json.gz')
            assert sha(path) == row['sha256'] == sha(shipped/path.name), key
    return dict(combinations_verified=16, AP_CP_targets_verified=32,
                compressed_patches_identical=True, camera_IO=False, qemu_used=False)


if __name__ == '__main__':
    print(json.dumps(verify(), ensure_ascii=False), flush=True)
