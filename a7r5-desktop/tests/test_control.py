"""控制文件仅允许位于同一原始命名空间、同一可写tmpfs，不退回持久工作区。"""
from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope='module')
def control_core(tmp_path_factory):
    folder=tmp_path_factory.mktemp('control-core')
    root=Path(__file__).resolve().parents[1]
    binary=folder/'control-core'
    result=subprocess.run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror',
        '-I',str(root/'sources/trust'),str(root/'tests/host_control.c'),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary


@pytest.mark.parametrize('fault', [0,1,2,3,4,5,6,7,8,9,13], ids=[
    'valid','parent-vfat','child-vfat','different-device','symlink','stat-error',
    'close-error','foreign-owner','different-namespace','read-only','public-control'])
def test_control_metadata_requires_verified_tmpfs(control_core,tmp_path,fault):
    parent=tmp_path/'parent';parent.mkdir()
    child=parent/'control'
    if fault==4:
        foreign=tmp_path/'foreign';foreign.mkdir();child.symlink_to(foreign)
    else:child.mkdir(mode=0o755 if fault==13 else 0o700)
    result=subprocess.run([str(control_core),str(parent),str(child),str(fault)],capture_output=True,text=True,check=True)
    assert result.stdout.startswith(f'ready={int(fault==0)} ')
    assert set(parent.iterdir())=={child}
    assert not list(child.iterdir())


@pytest.mark.parametrize('fault',[10,11,12],ids=['exclusive-create','existing-directory','invalid-parent'])
def test_native_creates_private_directory_without_service_mkdir(control_core,tmp_path,fault):
    parent=tmp_path/'parent';parent.mkdir();child=parent/'control'
    if fault==11:
        child.mkdir(mode=0o700);(child/'sentinel').write_bytes(b'keep')
    result=subprocess.run([str(control_core),str(parent),str(child),str(fault)],capture_output=True,text=True,check=True)
    assert result.stdout.startswith(f'ready={int(fault==10)} ')
    if fault==10:assert child.is_dir() and child.stat().st_mode&0o777==0o700 and not list(child.iterdir())
    elif fault==11:assert (child/'sentinel').read_bytes()==b'keep'
    else:assert not child.exists()
