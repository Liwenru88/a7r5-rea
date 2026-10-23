"""只执行原厂声音窗口和合成外部状态，不连接设备。"""
from pathlib import Path
import sys
import pytest

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
for folder in ('custom-features-20261021-02','custom-features-20261021-04',
    'shutter-mode-offline-20261022-01','shutter-observation-offline-20261021-01',
    'shutter-observation-offline-20261021-02'):
    sys.path.insert(0,str(ROOT/'analysis'/folder))
from sound_gate_probe import replay
from mute_probe import ap_controls,native_pin_acceptance
from mode_probe import encode_silent,resolve


@pytest.fixture(scope='module')
def programs():
    base=ROOT/'a7r5-qemu/build/look-materials-joint-oj2ed8ok'
    cp=(base/'cpapp-b.bin').read_bytes()
    source=bytearray((base/'cp-joint-source.bin').read_bytes());source[0x377601]=0x0f
    ap=(ROOT/'analysis/custom-features-20261021-03/research-materials-v3/candidate/appFw.so').read_bytes()
    return ap,bytes(source),cp


@pytest.mark.parametrize('descriptor',range(4))
def test_type1_requests_native_KASHA_without_changing_capture_type(programs,descriptor):
    result=replay(programs[2],after_type=1,descriptor_word=descriptor)
    assert result['PIN_requests']==[3]
    assert result['after_type_unchanged'] and result['mode_unchanged']
    assert '0x833ce2' in result['native_gate_edges']
    assert result['speaker_or_exposure_hardware_executed'] is False


@pytest.mark.parametrize('capture_type',(0,2,3))
@pytest.mark.parametrize('inhibit',(0,1))
def test_unselected_capture_types_are_identical_to_original_path(programs,capture_type,inhibit):
    options=dict(after_type=capture_type,inhibit=inhibit,descriptor_word=2)
    assert replay(programs[1],**options)==replay(programs[2],**options)


@pytest.mark.parametrize('options',[dict(frames=1),dict(mode=1)])
def test_native_first_frame_and_mode_gates_remain(programs,options):
    assert replay(programs[2],after_type=1,descriptor_word=2,**options)['PIN_requests']==[]


@pytest.mark.parametrize('audio',range(4))
@pytest.mark.parametrize('route',(0,1))
def test_native_audio_registration_and_output_gate(programs,audio,route):
    result=ap_controls(programs[0],audio,route)
    registered=next(t['enabled'] for t in result['tables'] if t['fixture_KindID']==3)
    accepted=native_pin_acceptance(programs[2],result['path'],registered=registered)
    assert (accepted==0)==(route==1 and audio in (0,1))


@pytest.mark.parametrize('values',[(0,0,0),(1,0,0),(0,1,1),(1,1,0)])
def test_silent_request_encoding_and_capture_type_resolution_unchanged(programs,values):
    packet=encode_silent(programs[0],still=values[0],interval=values[1],general=values[2])
    assert resolve(programs[1],packet)==resolve(programs[2],packet)
