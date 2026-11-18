"""原生Fsys适配的宿主边界契约；不执行固件指令或设备访问。"""
from pathlib import Path
import subprocess
import pytest
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
LOCAL=HERE.parent/'native'
@pytest.fixture(scope='module')
def contract(tmp_path_factory):
 out=tmp_path_factory.mktemp('fsys406')/'contract'
 command=['clang','-std=c11','-O2','-fno-builtin','-Wall','-Wextra','-Werror',f'-I{LOCAL}',f'-I{NATIVE}',str(LOCAL/'af_fsys406.c'),str(NATIVE/'af_sha256.c'),str(HERE/'fsys406_contract.c'),'-o',str(out)]
 r=subprocess.run(command,capture_output=True,text=True)
 assert r.returncode==0,r.stderr
 return out
@pytest.mark.parametrize('case',[0,1])
def test_slots_keep_full_token_and_publish_exact_double_read(contract,case):
 r=subprocess.run([str(contract),str(case)],capture_output=True,text=True);assert r.returncode==0,r.stderr
@pytest.mark.parametrize('case',[2,3,4,5,8,9,10,17,18])
def test_failed_changed_or_cancelled_reads_never_publish(contract,case):
 r=subprocess.run([str(contract),str(case)],capture_output=True,text=True);assert r.returncode==0,r.stderr
@pytest.mark.parametrize('case',[6,7,11,12,13,14,15])
def test_bounded_scan_rejects_unsafe_names_or_invalid_native_result(contract,case):
 r=subprocess.run([str(contract),str(case)],capture_output=True,text=True);assert r.returncode==0,r.stderr

def test_old_selection_or_alias_cannot_read(contract):
 r=subprocess.run([str(contract),'16'],capture_output=True,text=True);assert r.returncode==0,r.stderr

def test_mixed_cube_and_prepared_file_scan_and_stable_read(contract):
 r=subprocess.run([str(contract),'19'],capture_output=True,text=True);assert r.returncode==0,r.stderr
