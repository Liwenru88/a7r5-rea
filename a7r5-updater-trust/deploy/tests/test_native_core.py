"""实际编译同一扇区核心，在普通文件中验证成功、局部提交和拒绝路径。"""
from pathlib import Path
import os
import re
import subprocess
import pytest
from conftest import HERE


@pytest.fixture(scope='module')
def compiled(tmp_path_factory,sealed):
    path=tmp_path_factory.mktemp('host-core')/'core'
    result=subprocess.run(['/opt/homebrew/opt/llvm/bin/clang','-O2','-Wall','-Wextra','-Werror',
        '-Wno-unused-const-variable','-I',str(sealed/'materials'),'-I',str(HERE/'payload'),
        str(HERE/'tests/host_core.c'),'-o',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return path


@pytest.mark.parametrize('fault,expected',[(0,0),(1,14),(2,17),(3,17),(4,19),(5,20),(6,18),(7,15),(8,18)])
def test_fixed_sector_core_keeps_failure_evidence_without_retry(tmp_path,compiled,sealed,fault,expected):
    original=Path(os.environ['A7R5_TRUST_ORIGINAL']).read_bytes()
    target=tmp_path/'disk.img';target.write_bytes(original)
    journal=tmp_path/'journal'
    result=subprocess.run([str(compiled),str(target),str(journal),str(fault)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout.startswith(f'code={expected} ')
    raw=target.read_bytes();text=journal.read_text()
    if fault in (1,3,7):assert raw==original
    if fault in (0,5):assert raw==(sealed/'materials/candidate.logical.img').read_bytes()
    if fault in (2,6,8):
        # 第一扇区失败后没有再写第二项，也没有把已写部分回滚。
        import json
        rows=json.loads((sealed/'materials/write-plan.json').read_text())['rows']
        first=rows[0]['offset'];assert raw[:first]==original[:first] and raw[first+512:]==original[first+512:]
        assert raw!=original
        assert text.count('WRITE_BEGIN')==1
    if fault==4:
        import json
        row=json.loads((sealed/'materials/write-plan.json').read_text())['rows'][-1]
        assert raw[row['offset']:row['offset']+512]==original[row['offset']:row['offset']+512]
        assert text.count('WRITE_BEGIN')==257


def test_wrong_full_preimage_does_not_write(tmp_path,compiled):
    original=bytearray(Path(os.environ['A7R5_TRUST_ORIGINAL']).read_bytes());original[0]^=1
    target=tmp_path/'wrong.img';target.write_bytes(original)
    result=subprocess.run([str(compiled),str(target),str(tmp_path/'journal'),'0'],capture_output=True,text=True)
    assert result.returncode==0 and result.stdout.startswith('code=14 ')
    assert target.read_bytes()==bytes(original)
