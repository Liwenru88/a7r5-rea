"""严格绑定最终 DAT 回读与其构建锁。"""
import hashlib

SCOPE_423 = frozenset({
    'look24', 'look-fl2-fl3', 'photo-framing-markers', 'video-ntsc-prompt',
    'photo-electronic-shutter-sound', 'color-r6-st', 'color-awb-priority',
})


def validate_final_binding(manifest, lock, component_hashes):
    assert manifest['source'] == lock['dat']
    version = lock['version']
    plan = lock['plan']
    if version == '4.19':
        assert plan['native24']['sound_layout'] == 'custom-dual-full'
    elif version == '4.23':
        assert frozenset(plan['requested']) == SCOPE_423
        assert plan['native24']['sound_layout'] == 'relocated-fl23'
        assert 'variants' not in plan
        assert 'capture_modules' not in plan
    else:
        raise AssertionError('不支持的最终包版本')
    expected = lock['expected']['components']
    assert set(component_hashes) == set(expected)
    for name, digest in component_hashes.items():
        assert digest == expected[name]['sha256']
