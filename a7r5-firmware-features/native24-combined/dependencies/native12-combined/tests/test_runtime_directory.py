"""生产目录锚定与原选择sidecar，完整短读短写和失败路径。"""
import ctypes as C
from pathlib import Path
import pytest
from runtime_support import SOURCE,library

MOUNT=b'42 1 31:30 / /usr/data/lut rw,relatime - vfat /dev/nflasha30 rw\n'
FD=b'pos:\t0\nflags:\t0300000\nmnt_id:\t42\n'


@pytest.fixture
def directory(tmp_path):
    lib=library(tmp_path,'directory',[Path(__file__).with_name('runtime_directory.c'),*[
        SOURCE/'import'/s for s in ('r5_lut_directory.c','r5_lut_mount_guard.c','r5_filter_selection423.c')]])
    lib.test_acquire.argtypes=[C.c_char_p,C.c_char_p]
    return lib


@pytest.mark.parametrize('case',['valid','id','readonly','device','filesystem','root','duplicate','truncated','fd_duplicate'])
def test_anchoring_only_accepts_exact_complete_writable_mount(directory,case):
    m,f=MOUNT,FD
    if case=='id': f=FD.replace(b'42',b'43')
    if case=='readonly': m=MOUNT.replace(b'rw,',b'ro,')
    if case=='device': m=MOUNT.replace(b'nflasha30',b'nflasha6')
    if case=='filesystem': m=MOUNT.replace(b'vfat',b'ext2')
    if case=='root': m=MOUNT.replace(b'31:30 / ',b'31:30 /sub ')
    if case=='duplicate': m=MOUNT+MOUNT
    if case=='truncated': m=MOUNT[:-1]
    if case=='fd_duplicate': f=FD+b'mnt_id:\t42\n'
    rc=directory.test_acquire(m,f)
    assert (rc==0)==(case=='valid')
    assert directory.test_stat(0)==(1<<10 if case=='valid' else 0)
    if case=='valid':
        for n in (0,1,7,12):
            assert directory.test_save(n)==0
            loaded=C.c_uint(999)
            assert directory.test_load(C.byref(loaded))==0 and loaded.value==n
        assert directory.test_save(13)==1
        directory.test_corrupt_active(20)
        loaded=C.c_uint(999)
        assert directory.test_load(C.byref(loaded))==2 and loaded.value==999
        assert directory.test_release()==0 and directory.test_stat(0)==0


@pytest.mark.parametrize('fault,expected,visible',[(1,2,False),(2,2,False),(4,2,False),(8,2,False),(16,3,False),(32,3,True),(64,2,False)])
def test_selection_sidecar_failure_never_claims_durable_success(directory,fault,expected,visible):
    assert directory.test_acquire(MOUNT,FD)==0
    assert directory.test_save(1)==0
    directory.test_fault(fault)
    assert directory.test_save(7)==expected
    loaded=C.c_uint(999)
    assert directory.test_load(C.byref(loaded))==0 and loaded.value==(7 if visible else 1)
    assert directory.test_stat(0)==1<<10
    assert directory.test_release()==0 and directory.test_stat(0)==0
