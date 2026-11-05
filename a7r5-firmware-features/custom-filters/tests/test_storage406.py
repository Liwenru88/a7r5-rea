"""固定入口仅测试编译替换为临时目录；不访问实际/setting、/dev或运行期/proc。"""
import ctypes as C
import os
from pathlib import Path
import subprocess
import sys
import pytest

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
SHIM=r'''
#define _DARWIN_C_SOURCE 1
#define _POSIX_C_SOURCE 200809L
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static char root[4096];static uint64_t blocks,unit,flags;
static int wrong_device,regular_node,change_id,fdinfo_reads,unknown_paths;
void test_configure(const char *p,uint64_t b,uint64_t u,uint64_t f,int wrong,int regular,int change){
 snprintf(root,sizeof(root),"%s",p);blocks=b;unit=u;flags=f;
 wrong_device=wrong;regular_node=regular;change_id=change;fdinfo_reads=unknown_paths=0;
}
int test_unknown_paths(void){return unknown_paths;}
int af_storage406_test_open(const char *p,int f){
 char target[8192];const char *name=0;
 if(!strcmp(p,"/"))return open(root,f);
 if(!strcmp(p,"/proc/self/mountinfo"))name="mountinfo";
 else if(!strncmp(p,"/proc/self/fdinfo/",18)){
  fdinfo_reads++;name=change_id&&fdinfo_reads>1?"fdinfo2":"fdinfo";
 }
 if(!name){unknown_paths++;errno=EINVAL;return -1;}
 snprintf(target,sizeof(target),"%s/%s",root,name);return open(target,f);
}
int af_storage406_test_openat(int d,const char *n,int f){return openat(d,n,f);}
int af_storage406_test_fstatat(int d,const char *p,struct stat *s,int f){
 int result=fstatat(d,p,s,f);if(result)return result;
 if(!strcmp(p,"nflasha2")){
  s->st_rdev=s->st_dev+(dev_t)wrong_device;
  s->st_mode=(regular_node?S_IFREG:S_IFBLK)|0600;
 }return 0;
}
int af_storage406_test_fstatvfs(int d,struct statvfs *s){
 if(fstatvfs(d,s))return -1;s->f_bavail=blocks;s->f_frsize=unit;s->f_flag=flags;return 0;
}
'''

@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    build=tmp_path_factory.mktemp('storage406-build');shim=build/'test.c';shim.write_text(SHIM)
    output=build/'storage406.dylib'
    mode=['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',*mode,
        '-DAF_STORAGE406_TEST','-I'+str(NATIVE),str(NATIVE/'af_storage406.c'),str(shim),'-o',str(output)],check=True)
    x=C.CDLL(str(output));x.af_storage406_open.argtypes=[C.POINTER(C.c_int)]
    x.test_configure.argtypes=[C.c_char_p]+[C.c_uint64]*3+[C.c_int]*3
    return x

def fixture(tmp_path):
    root=tmp_path/'root';root.mkdir(mode=0o700);(root/'setting').mkdir(mode=0o700)
    (root/'dev').mkdir(mode=0o700);(root/'dev/nflasha2').write_bytes(b'HOST_TEST_NODE_METADATA_ONLY')
    (root/'fdinfo').write_text('pos:\t0\nflags:\t02000000\nmnt_id:\t41\n')
    (root/'fdinfo2').write_text('mnt_id:\t42\n')
    dev=os.stat(root/'setting').st_dev
    text=f'41 1 {os.major(dev)}:{os.minor(dev)} / /setting rw,sync - vfat /dev/nflasha2 rw,sync,posix_attr\n'
    (root/'mountinfo').write_text(text)
    return root,text

def configure(lib,root,blocks=4096,unit=4096,flags=0,wrong=0,regular=0,change=0):
    lib.test_configure(os.fsencode(root),blocks,unit,flags,wrong,regular,change)

def failure(lib,expected,label):
    out=C.c_int(0x12345678)
    status=lib.af_storage406_open(C.byref(out))
    if status==0:os.close(out.value)
    assert status==expected,label
    assert out.value==0x12345678,label
    assert lib.test_unknown_paths()==0,label

def test_fixed_private_parent_without_writes(lib,tmp_path):
    root,_=fixture(tmp_path);configure(lib,root)
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    out=C.c_int(-1)
    assert lib.af_storage406_open(C.byref(out))==0
    try:
        assert os.fstat(out.value).st_ino==os.stat(root/'setting').st_ino
        assert os.get_inheritable(out.value) is False
    finally:os.close(out.value)
    assert list((root/'setting').iterdir())==[]
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert lib.test_unknown_paths()==0

def test_wrong_mount_ro_missing_and_truncated_rejected(lib,tmp_path):
    root,text=fixture(tmp_path)
    cases=[('source',text.replace('/dev/nflasha2','/dev/nflasha3'),-3),
           ('type',text.replace(' - vfat ',' - tmpfs '),-3),
           ('bind-root',text.replace(' / /setting ',' /other /setting '),-3),
           ('point',text.replace(' /setting ',' /system '),-3),
           ('mount-ro',text.replace(' rw,sync -',' ro,sync -'),-4),
           ('super-ro',text.replace('rw,sync,posix_attr','ro,sync,posix_attr'),-4),
           ('ambiguous-rw-ro',text.replace('rw,sync -','rw,ro,sync -'),-4),
           ('missing-id',text.replace('41 1 ','42 1 '),-3),
           ('duplicate',text+text,-6),
           ('truncated',text[:-1],-6),
           ('overflow-id',text.replace('41 1 ','4294967296 1 '),-6)]
    for label,changed,status in cases:
        (root/'mountinfo').write_text(changed);configure(lib,root);failure(lib,status,label)
    (root/'mountinfo').write_text(text)
    for invalid in ['pos:\t0\n','mnt_id:\t41\nmnt_id:\t41\n','mnt_id:\t4294967296\n']:
        (root/'fdinfo').write_text(invalid);configure(lib,root);failure(lib,-6,invalid)

def test_directory_node_readonly_and_space_rejected(lib,tmp_path):
    root,_=fixture(tmp_path)
    for label,args,status in [('wrong-device',{'wrong':1},-3),('regular-device',{'regular':1},-3),
        ('readonly',{'flags':1},-4),('capacity',{'blocks':320},-5),
        ('zero-unit',{'unit':0},-1),('overflow',{'blocks':4096,'unit':2**64-1},-1)]:
        configure(lib,root,**args);failure(lib,status,label)
    (root/'setting').chmod(0o722);configure(lib,root);failure(lib,-3,'nonprivate-mode')
    (root/'setting').chmod(0o700);(root/'setting').rename(root/'other')
    (root/'setting').symlink_to('other',target_is_directory=True)
    configure(lib,root);failure(lib,-2,'symlink-parent')

def test_recheck_mount_changed_does_not_publish_fd(lib,tmp_path):
    root,_=fixture(tmp_path);configure(lib,root,change=1)
    failure(lib,-3,'mnt_id changed between validation reads')
    assert list((root/'setting').iterdir())==[]
