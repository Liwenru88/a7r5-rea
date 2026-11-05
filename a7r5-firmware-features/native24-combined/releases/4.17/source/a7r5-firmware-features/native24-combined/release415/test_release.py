"""4.15固定载荷、证据分层、版本及失败边界。"""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('native24_release415', Path(__file__).with_name('build.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
gate = m.load(Path(__file__).with_name('evidence_gate.py'), 'release415_gate_tests')


def candidate():
    return dict(spec='a7r5-firmware-features/specs/017-icon-page-boundary',status='NOT_VERIFIED',
        bundle_sha256=m.ARCHIVE_SHA,page_boundary_fix=dict(status='OFFLINE_REPAIR_VERIFIED_DEVICE_NOT_VERIFIED',
            components={k:dict(sha256=v) for k,v in m.COMPONENTS.items()},output_blocks=[4096,1504],hardware_LDEC_verified=False))


@pytest.mark.parametrize('key,bad', [('status','VERIFIED'),('output_blocks',[5600]),
                                    ('components',{}),('hardware_LDEC_verified',True)])
def test_unverified_or_wrong_page_candidate_is_rejected(key,bad):
    c=candidate();m.validate_candidate(c);c['page_boundary_fix'][key]=bad
    with pytest.raises(ValueError):m.validate_candidate(c)


@pytest.mark.parametrize('key,bad', [('spec','a7r5-firmware-features/specs/015-tabs-device-reboot'),
                                    ('bundle_sha256','0'*64),('status','VERIFIED')])
def test_old_or_unknown_candidate_is_rejected(key,bad):
    c=candidate();c[key]=bad
    with pytest.raises(ValueError):m.validate_candidate(c)


@pytest.mark.parametrize('resource,old', [
    ('image_00_23_IPSX.uxc','202a5aa8fb0e3a26b7d2018c56c2ea8ab048ed2dc622179c9f092467f52646f6'),
    ('image_00_32_IPSX.uxc','7adc49cf46a99802e8e68e06455d813730ff0f32c4efe96f76bd80161e442b2c')])
def test_414_resources_cannot_enter_415(resource,old):
    c=candidate();c['page_boundary_fix']['components'][resource]['sha256']=old
    with pytest.raises(ValueError):m.validate_candidate(c)


def cpu():
    return dict(status='PASS',full_related_suite=True,sources_unchanged=True,exit_code=0,
        tests=sorted(m.REQUIRED_TESTS)+[f'test_existing_{i}' for i in range(80)],
        AP_sha256=m.COMPONENTS['appFw.so'],CP_sha256=m.COMPONENTS['cpapp-b.bin'])


@pytest.mark.parametrize('key,bad', [('full_related_suite',False),('sources_unchanged',False),
    ('tests',['partial']),('AP_sha256','0'*64),('CP_sha256','0'*64)])
def test_partial_or_different_runtime_evidence_is_rejected(key,bad):
    c=cpu();m.validate_cpu(c);c[key]=bad
    with pytest.raises(ValueError):m.validate_cpu(c)


def test_same_count_without_regressions_is_rejected():
    c=cpu();c['tests']=[f'test_other_{i}' for i in range(82)]
    with pytest.raises(ValueError):m.validate_cpu(c)


def page_tests():
    return (gate.PAGE_TESTS-{'test_qemu_page_gate_rejects_both_released_long_blocks'})|{
        'test_qemu_page_gate_rejects_both_released_long_blocks[413]',
        'test_qemu_page_gate_rejects_both_released_long_blocks[414]'}


def test_same_count_cannot_replace_page_contract_or_both_old_releases():
    names=page_tests();gate.validate_page_tests(names)
    for key in names:
        changed=names-{key}|{'test_unrelated'}
        with pytest.raises(ValueError):gate.validate_page_tests(changed)


@pytest.mark.parametrize('kind', ['failure','error','skipped','duplicate'])
def test_xml_failure_skip_or_duplicate_is_rejected(tmp_path,kind):
    p=tmp_path/'bad.xml'
    p.write_text('<testsuite><testcase name="a">'+(f'<{kind}/>' if kind!='duplicate' else '')+
                 '</testcase><testcase name="'+('a' if kind=='duplicate' else 'b')+'"/></testsuite>')
    with pytest.raises(ValueError):gate.cases(p,2)


@pytest.mark.parametrize('name', ['/tmp/outside','../outside','a/../../outside'])
def test_archive_evidence_path_escape_is_rejected(tmp_path,name):
    with pytest.raises(ValueError):gate.inside(tmp_path,name)


def test_package_binds_415_and_page_split_components():
    assert m.VERSION=='4.15'
    assert m.CandidatePatch._bindings['/share/app/image_00_23_IPSX.uxc'].target_bytes==9611836
    assert m.CandidatePatch._bindings['/share/app/image_00_32_IPSX.uxc'].target_bytes==9963512
    assert m.CandidatePatch._bindings['/share/app/image_00_32_IPSX.uxc'].target_sha256=='7e598d75a997c37cea6204e8e35773e9b9ee5e4ce67b0c0ab569011563af3356'


def test_archive_metadata_or_unlisted_change_is_rejected():
    before=[dict(name='AP',size=10,sha256='old',crc32='old')]
    after=[dict(name='AP',size=10,sha256='new',crc32='new')]
    assert m.check_members(before,after,{'AP':'new'})==['AP']
    for changed,expected in [(dict(after[0],size=11),{'AP':'new'}),(after[0],{})]:
        with pytest.raises(ValueError):m.check_members(before,[changed],expected)
