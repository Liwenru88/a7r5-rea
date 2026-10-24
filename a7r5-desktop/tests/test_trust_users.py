"""实际进程检查核心的系统调用替身；不枚举主机或相机进程。"""
import json
import subprocess
import pytest
from conftest import ROOT
from test_native import native
from test_trust_force import force_native


@pytest.fixture(scope='module')
def users_core(force_native,tmp_path_factory):
    binary,_,_=force_native;folder=tmp_path_factory.mktemp('trust-users')
    (folder/'jit_config.h').write_bytes((binary.parent/'jit_config.h').read_bytes())
    header=(binary.parent/'trust_config.h').read_text()
    header+='\n#define TRUST_USER_CHECK_DIAGNOSTICS 1\n#define TARGET_PATH target_path\n#define RAM_DIR ram_path\n#define JOURNAL_PATH journal_path\n#define READBACK_PATH readback_path\n'
    header+='#define FORCE_PRELOAD_A '+json.dumps('\n'*512)+'\n#define FORCE_PRELOAD_B FORCE_PRELOAD_A\n#define OUTPUT_BEGIN "BEGIN\\n"\n#define OUTPUT_END "END\\n"\n'
    (folder/'trust_config.h').write_text(header)
    output=folder/'users-core'
    result=subprocess.run(['/usr/bin/clang','-DTRUST_SCAN_TEST=1','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-const-variable',
        '-I',str(folder),'-I',str(ROOT/'sources/trust'),str(ROOT/'tests/host_trust_force.c'),'-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return output


@pytest.mark.parametrize('fault,reason',[(0,0),(1,5),(2,3),(3,1),(4,6),(5,4),(6,0),(7,9),(8,0),(9,11),(10,12),(11,10)])
def test_users_check_distinguishes_real_occupancy_from_inspection_errors(users_core,tmp_path,fault,reason):
    source=tmp_path/'sentinel';source.write_bytes(b'preserve')
    result=subprocess.run([str(users_core),str(source),str(tmp_path),str(fault)],capture_output=True,text=True,check=True)
    assert f'clear={int(reason==0)} ' in result.stdout
    assert f'precheck_reason={reason} ' in result.stdout
    assert 'target_writes=0' in result.stdout and source.read_bytes()==b'preserve'
    if fault in (1,11):assert 'precheck_device=64641 ' in result.stdout
    if fault in (4,5,7):assert 'precheck_error=-13 ' in result.stdout


def test_readonly_compile_path_never_opens_or_writes_partition(users_core,tmp_path):
    output=tmp_path/'readonly-core'
    compiled=subprocess.run(['/usr/bin/clang','-DTRUST_PRECHECK_ONLY=1','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-const-variable',
        '-I',str(users_core.parent),'-I',str(ROOT/'sources/trust'),str(ROOT/'tests/host_trust_force.c'),'-o',str(output)],capture_output=True,text=True)
    assert compiled.returncode==0,compiled.stderr
    image=tmp_path/'image';image.write_bytes(b'keep')
    work=tmp_path/'work';work.mkdir()
    result=subprocess.run([str(output),str(image),str(work)],capture_output=True,text=True,check=True)
    assert 'code=0 target_writes=0' in result.stdout and image.read_bytes()==b'keep'
    assert not list((work/'ram').glob('partition*'))


@pytest.mark.parametrize('fault,reason,fd_scans',[
    (12,0,1),(13,4,0),(14,4,0),(15,0,1),(16,0,1),(17,0,1),
    (18,10,1),(19,4,0),(20,4,0),(21,4,0),(22,4,0),
    (23,14,0),(24,0,0),(25,4,0),(26,0,1),(27,4,0),(28,4,0),
    (29,6,1),(30,7,1),(31,11,0),(32,4,0),(33,11,0),
])
def test_einval_requires_lifecycle_proof_and_keeps_fd_check(users_core,tmp_path,fault,reason,fd_scans):
    source=tmp_path/'sentinel';source.write_bytes(b'keep')
    result=subprocess.run([str(users_core),str(source),str(tmp_path),str(fault)],capture_output=True,text=True,check=True)
    assert f'clear={int(reason==0)} ' in result.stdout
    assert f'precheck_reason={reason} ' in result.stdout
    assert f'fd_scans={fd_scans}' in result.stdout
    if reason==4:assert 'precheck_error=-22 ' in result.stdout
    if fault==18:assert 'precheck_device=64641 ' in result.stdout
    assert 'target_writes=0' in result.stdout and source.read_bytes()==b'keep'
