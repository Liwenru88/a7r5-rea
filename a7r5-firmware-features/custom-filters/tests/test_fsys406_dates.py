"""访问日期可变化，其他原元数据仍拒绝变化；不执行真实Fsys。"""
from pathlib import Path
import subprocess

import pytest

HERE=Path(__file__).resolve().parent
NATIVE=HERE.parent/'native'


@pytest.fixture(scope='module')
def contract(tmp_path_factory):
    target=tmp_path_factory.mktemp('fsys-stable-dates')/'contract'
    command=['clang','-std=c11','-O2','-fno-builtin','-Wall','-Wextra','-Werror',
             '-I'+str(NATIVE),str(NATIVE/'af_fsys406.c'),str(NATIVE/'af_sha256.c'),
             str(HERE/'fsys406_dates_contract.c'),'-o',str(target)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return target


def test_access_only_changes_do_not_invalidate_exact_double_read(contract):
    result=subprocess.run([str(contract),'-1'],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_other_sixteen_date_bytes_still_reject_without_publishing(contract):
    access={0x18,0x19,0x22,0x23,0x24,0x25}
    for offset in range(0x10,0x26):
        if offset in access:
            continue
        result=subprocess.run([str(contract),str(offset)],capture_output=True,text=True)
        assert result.returncode==0,(hex(offset),result.stderr)
