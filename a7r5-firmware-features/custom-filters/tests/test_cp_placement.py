"""放置门槛仅做宿主只读验证，不执行CP或生成固件。"""
import pytest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/packaging406'))
import check_placement as check

@pytest.fixture(scope='module')
def cp():
    source=check.ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    return check.read_cpio(source,{'cp/cpapp-b.bin'})['cp/cpapp-b.bin']

def test_explicit_reclaimed_region_accepts_only_its_owned_bounds(cp):
    assert check.checked_span(cp,0xbef9e8,408)['bytes']==408
    # 零/BSS、旧helper、研究地址和越过原曲线回收边界均不能获得放置许可。
    for address,size,kind in ((0x92000000,8,'RX'),(0xbef620,8,'RX'),
                              (0x119c8c8,8,'RX'),(0xbef9e8,409,'RX'),
                              (0x1a3ab40,180,'RW')):
        with pytest.raises(ValueError):check.checked_span(cp,address,size,kind)

def test_wrong_source_rejected_before_range_claim(cp):
    changed=bytearray(cp);changed[0]^=1
    with pytest.raises(ValueError,match='身份'):check.checked_span(changed,0xbef9e8,8)

def test_existing_modules_exceed_owned_rx_without_using_file_size_as_code(cp):
    result=check.inspect(cp)
    assert result['verified_reclaimed_tail']['bytes']==408
    assert result['known_bss_expansion']['numeric_extra_bytes']==1216
    assert len(result['modules'])==1
    assert 'continuation33-software/cp-requests/' in result['modules'][0]['path']
    assert [m['initialized_readonly_bytes'] for m in result['modules']]==[4348]
    assert [m['writable_bytes'] for m in result['modules']]==[264]
    assert [m['writable_load_bytes'] for m in result['modules']]==[268]
    assert not any(m['fits_verified_rx_tail'] for m in result['modules'])
    assert not result['firmware_written'] and not result['signature_created']

def test_cli_module_and_new_output_are_explicit_without_overwriting_history(cp,tmp_path):
    path=check.DEFAULT_MODULE
    output=tmp_path/'fresh'
    check.main(['--module',str(path),'--output',str(output)])
    report=__import__('json').loads((output/'placement.json').read_text())
    assert report['modules'][0]['sha256']==check.sha(path.read_bytes())
    with pytest.raises(ValueError,match='输出目录已存在'):
        check.main(['--module',str(path),'--output',str(output)])
