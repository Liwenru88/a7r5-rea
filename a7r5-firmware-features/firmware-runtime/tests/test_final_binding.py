"""最终包回放绑定契约。"""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / 'dependencies/native12-combined'))
from final_binding import validate_final_binding

MODULES = {
    'look24', 'look-fl2-fl3', 'photo-framing-markers', 'video-ntsc-prompt',
    'photo-electronic-shutter-sound', 'color-r6-st', 'color-awb-priority',
}


def lock():
    return {
        'dat': 'stock-dat-sha', 'version': '4.23',
        'plan': {'requested': sorted(MODULES),
                 'native24': {'sound_layout': 'relocated-fl23'}},
        'expected': {'components': {
            'usr/lib/appFw.so': {'sha256': 'ap-sha'},
            'cpapp-b.bin': {'sha256': 'cp-sha'},
        }},
    }


def test_423_final_binding_accepts_exact_scope_and_component_hashes():
    validate_final_binding({'source': 'stock-dat-sha'}, lock(),
                           {'usr/lib/appFw.so': 'ap-sha', 'cpapp-b.bin': 'cp-sha'})


def test_423_final_binding_rejects_module_or_layout_drift():
    with pytest.raises(AssertionError):
        validate_final_binding({'source': 'stock-dat-sha'},
                               dict(lock(), plan={'requested': sorted(MODULES - {'color-r6-st'}),
                                                  'native24': {'sound_layout': 'custom-dual-full'}}),
                               {'usr/lib/appFw.so': 'ap-sha', 'cpapp-b.bin': 'cp-sha'})
