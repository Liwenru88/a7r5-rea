"""补丁冲突、ASLR分支及未授权资源拒绝，不执行目标ELF。"""
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/packaging406'))
from candidate_preflight import compose,sha,branch,component_policy

def test_composite_is_one_source_and_never_overwrites_other_owner():
    original=b'abcdefgh';p=dict(offset=1,before=b'bc'.hex(),after=b'12'.hex())
    assert compose(original,sha(original),[p])==b'a12defgh' and original==b'abcdefgh'
    for expected,patches in [(sha(b'bad'),[p]),(sha(original),[p,p]),
        (sha(original),[dict(p,before='0000')]),(sha(original),[dict(p,after='01')]),
        (sha(original),[dict(p,offset=8)])]:
        with pytest.raises(ValueError):compose(original,expected,patches)

@pytest.mark.parametrize('base',[0x4000000000,0x7000000000])
def test_same_relative_branch_at_two_nonzero_layouts(base):
    assert branch(base+0x1000,base+0x2000)==bytes.fromhex('00040014')
    assert branch(base+0x1000,base+0x2000,True)==bytes.fromhex('00040094')
    assert branch(base+(1<<27),base)==bytes.fromhex('00000016')
    for a,b in [(base,base+(1<<27)),(base+1,base+4),(base,base-4-(1<<27))]:
        with pytest.raises(ValueError):branch(a,b)

def test_component_policy_preserves_existing_resources():
    assert component_policy('usr/lib/appFw.so')=='existing_fixed_ap'
    assert component_policy('usr/share/app/string_en_horizontal.uxc')=='existing_string'
    for layout in ('23','32'):
        assert component_policy(f'usr/share/app/image_00_{layout}_IPSX.uxc')=='required_icon_dat_tool_gap'
    for path in ['usr/lib/libaf_repository_media.so','usr/lib/libObj.so','usr/share/app/image_01_vertical_IPSX.uxc',
                 'usr/share/app/image_00_vertical_IPSX.uxc','usr/share/app/image_00_horizontal_IPSX.uxc',
                 '/usr/data/lut','usr/share/app/../lib/appFw.so','simulation/af-ui-dynamic.so']:
        with pytest.raises(ValueError):component_policy(path)
