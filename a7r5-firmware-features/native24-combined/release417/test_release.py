"""验证固定相对偏移载荷、证据复用和独立容器回读的失败边界。"""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parent))
import container_package as p
import evidence_gate as gate

ARCHIVE = p.FEATURE/'audits/relative-parameters'


@pytest.mark.parametrize('change', ['old_AP','source_drift','other_cases','missing_identity_case','wrong_build'])
def test_stale_or_incomplete_cpu_evidence_is_rejected(change):
    cpu=json.loads((ARCHIVE/'runtime-regression.json').read_text())
    names=gate.cases(ARCHIVE/'runtime-regression.xml',31)
    gate.validate_cpu(cpu,names,gate.PINNED['build.json'])
    if change=='old_AP':cpu['AP_sha256']='27bc6eb0a0d9996e96e3835205d06c1cf03c7ef73421e6781b6e96c4b6ed7962'
    elif change=='source_drift':cpu['sources_unchanged']=False
    elif change=='other_cases':cpu['tests']=['unrelated::test_other_'+str(i) for i in range(31)]
    elif change=='wrong_build':cpu['build_receipt_sha256']='0'*64
    else:
        cpu['tests']=[n.replace('[renamed]','[unrelated]') for n in cpu['tests']]
        names={n.rsplit('::',1)[-1] for n in cpu['tests']}
    with pytest.raises(ValueError):gate.validate_cpu(cpu,names,gate.PINNED['build.json'])


@pytest.mark.parametrize('change', ['old_AP','missing_slot','missing_packet','different_recipe'])
def test_incomplete_or_different_upstream_parity_is_rejected(change):
    proof=json.loads((ARCHIVE/'parity-proof.json').read_text())
    gate.validate_parity(proof)
    if change=='old_AP':proof['candidate_AP_sha256']='0'*64
    elif change=='missing_slot':proof['candidate_comparison'][0]['slots'].pop()
    elif change=='missing_packet':proof['native_packets']=431
    else:proof['formal_recipe_sha256']='0'*64
    with pytest.raises(ValueError):gate.validate_parity(proof)


@pytest.mark.parametrize('kind', ['failure','error','skipped','duplicate'])
def test_failed_or_duplicate_xml_is_rejected(tmp_path,kind):
    file=tmp_path/'bad.xml'
    file.write_text('<testsuite><testcase name="a">'+(f'<{kind}/>' if kind!='duplicate' else '')+
                    '</testcase><testcase name="'+('a' if kind=='duplicate' else 'b')+'"/></testsuite>')
    with pytest.raises(ValueError):gate.cases(file,2)


@pytest.mark.parametrize('name', ['/tmp/outside','../outside','a/../../outside'])
def test_evidence_cannot_escape_its_root(tmp_path,name):
    with pytest.raises(ValueError):gate.inside(tmp_path,name)


def test_fixed_417_uses_relative_AP_and_preserves_partition_bindings():
    assert p.VERSION=='4.17'
    assert p.CandidatePatch._bindings['/lib/appFw.so'].target_sha256=='eaf0b742745696f651dbe5ee75a813bb168ac41db81706743712ab8f6d0491bf'
    assert p.CandidatePatch._bindings['/lib/appFw.so'].target_bytes==97583104
    assert p.CandidatePatch._bindings['/share/app/image_00_23_IPSX.uxc'].target_bytes==9611836


def test_archive_metadata_or_unlisted_change_is_rejected():
    before=[dict(name='AP',size=10,sha256='old',crc32='old')]
    after=[dict(name='AP',size=10,sha256='new',crc32='new')]
    assert p.check_members(before,after,{'AP':'new'})==['AP']
    wrong=deepcopy(after);wrong[0]['size']=11
    for changed,expected in ((wrong,{'AP':'new'}),(after,{})):
        with pytest.raises(ValueError):p.check_members(before,changed,expected)
