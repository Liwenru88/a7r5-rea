"""原Fsys软件运行暴露的长名／短别名契约，宿主回归不替代原卷运行。"""
from pathlib import Path
import subprocess

import pytest

HERE=Path(__file__).parent
NATIVE=HERE.parent/'native'


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    out=tmp_path_factory.mktemp('fsys-alias')/'contract'
    result=subprocess.run(['clang','-std=c11','-O2','-fno-builtin','-Wall','-Wextra','-Werror',
        '-I'+str(NATIVE),str(NATIVE/'af_fsys406.c'),str(NATIVE/'af_sha256.c'),
        str(HERE/'fsys406_alias_contract.c'),'-o',str(out)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return out


@pytest.mark.parametrize('case',[0,1,2,3],ids=['long-label-short-open','changed-alias','unsafe-alias','duplicate-alias'])
def test_short_volume_long_name_contract(driver,case):
    result=subprocess.run([str(driver),str(case)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
