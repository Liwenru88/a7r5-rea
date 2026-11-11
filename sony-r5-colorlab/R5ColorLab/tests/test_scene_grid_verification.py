"""独立场景复验的输入隔离与采用门槛。"""
from hashlib import sha256
from types import SimpleNamespace

import pytest

from verify_scene_grid import adoption_check, new_photo_pairs


@pytest.mark.parametrize('used_kind', ['raw', 'target', None])
def test_new_scene_pairs_reject_reused_bytes_even_when_renamed(tmp_path, used_kind):
    raw_dir = tmp_path/'原始照片'
    folder = tmp_path/'柯达_ektar_100'
    targets = folder/'目标照片'
    raw_dir.mkdir()
    targets.mkdir(parents=True)
    for stem in ('renamed', 'second'):
        (raw_dir/(stem+'.arw')).write_bytes(f'{stem}-raw'.encode())
        (targets/(stem+'.tif')).write_bytes(f'{stem}-target'.encode())
    raw_sha = sha256(b'renamed-raw').hexdigest()
    target_sha = sha256(b'renamed-target').hexdigest()
    report = {'photo_inputs': [{'raw_sha256': raw_sha if used_kind == 'raw' else 'prior'}]}
    case = {'scene_inputs': {'old': {'sha256': target_sha if used_kind == 'target' else 'prior'}}}
    if used_kind:
        with pytest.raises(ValueError, match='已用于开发'):
            new_photo_pairs(tmp_path, folder, report, case)
    else:
        assert new_photo_pairs(tmp_path, folder, report, case)['renamed'] == (raw_sha, target_sha)


def test_adoption_requires_gain_beyond_noise_and_region_protection():
    baseline = {'delta_e00_mean': 5., 'rgb_rmse': 10.}
    limits = {'delta_e00_mean': 5.02, 'rgb_rmse': 10.03}
    scenes = [dict(name=key, guard=SimpleNamespace(
        baseline={'whole': baseline}, limits={'whole': limits},
        groups={'whole', 'skin', 'shadows', 'near-neutral', 'high-chroma'})) for key in ('a', 'b')]
    rows = {key: {'whole': {'delta_e00_mean': 4.9, 'rgb_rmse': 9.9}} for key in ('a', 'b')}
    assert adoption_check(scenes, rows, [])['status'] == 'pass'
    assert adoption_check(scenes, rows, ['a:skin:delta_e00_p95'])['status'] == 'retain-original'
    rows['a']['whole']['rgb_rmse'] = rows['b']['whole']['rgb_rmse'] = 9.99
    for scene in scenes:
        scene['guard'].groups.remove('skin')
    decision = adoption_check(scenes, rows, [])
    assert decision['status'] == 'retain-original'
    assert decision['failures'] == ['missing-region:skin', 'no-measurable-gain:rgb_rmse']
