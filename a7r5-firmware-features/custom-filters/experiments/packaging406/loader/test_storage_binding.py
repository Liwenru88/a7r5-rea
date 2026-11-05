"""原绑定函数的宿主所有权契约；不执行目标或访问真实系统路径。"""
from pathlib import Path
import ctypes as c
import hashlib
import re
import subprocess
import sys
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
SOURCE=ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406/loader/af_bootstrap406.c'

PREFIX=r'''
#include <string.h>
#include "af_ap_manage.h"
#include "af_labels.h"
#include "af_storage406.h"
typedef struct {const char *path;size_t bytes;} BootFile;
static const BootFile boot_repository={"TEST_NO_FILE_ACCESS",4};
static int installed,mode,qualified,opened,attached,closed;
static int native_media_result;
int af_bootstrap406_bind_native_media(unsigned slot){(void)slot;return AF_IO;}
static void *repository_context,*repository_handle;
static AfCatalog *catalog;static AfLabels *labels;
static void *file_map(const BootFile *f,int w){(void)f;(void)w;return mode==4?0:(void *)1;}
static int test_munmap(void *p,size_t n){(void)p;(void)n;return 0;}
static void *test_dlopen(const char *p,int f){(void)p;(void)f;return (void *)1;}
static void *test_open_service(int fd,AfCatalog *a,AfLabels *l,int *status){
 (void)fd;(void)a;(void)l;opened++;*status=mode==5?AF_IO:AF_OK;
 return mode==5?0:(void *)0x1234;
}
static int test_bind_library(void *ctx,int fd){(void)ctx;(void)fd;return mode==1?AF_IO:AF_OK;}
static uint32_t test_caps(void *ctx){(void)ctx;return AF_MANAGE_CAP_PERSIST;}
static int test_pump(void *ctx,AfApManage *m){(void)ctx;(void)m;return AF_OK;}
static int test_service_bind(const AfApManageService *s){(void)s;if(mode==2)return AF_STALE;attached++;return AF_OK;}
static void *test_dlsym(void *h,const char *n){(void)h;
 if(!strcmp(n,"af_repository_service_open"))return (void *)test_open_service;
 if(!strcmp(n,"af_repository_service_bind_library"))return (void *)test_bind_library;
 if(!strcmp(n,"af_repository_service_capabilities"))return (void *)test_caps;
 if(!strcmp(n,"af_repository_service_pump"))return (void *)test_pump;
 return 0;
}
static int test_storage_open(int *out){qualified++;*out=42;return AF_STORAGE406_OK;}
static int test_close(int fd){(void)fd;closed++;return mode==3||mode==5?-1:0;}
#define munmap test_munmap
#define dlopen test_dlopen
#define dlsym test_dlsym
#define af_storage406_open test_storage_open
#define close test_close
#define UF(name,type) ((type)test_service_bind)
'''

@pytest.fixture(scope='module')
def api(tmp_path_factory):
    raw=SOURCE.read_text()
    begin=raw.index('int af_bootstrap406_bind_storage(')
    body=raw[begin:raw.index('static int native_media_snapshot(',begin)]
    # 新所有权状态从真实源码抽取；旧实现没有该状态，测试观察为“未持有”。
    declaration=re.search(r'static\s+int\s+native_storage_parent\s*=\s*-1\s*;',raw)
    declared=declaration.group(0) if declaration else ''
    reference=re.search(r'static\s+int\s+reference_import_result\s*=\s*AF_EMPTY\s*;',raw)
    if reference:declared+='\n'+reference.group(0)
    retained='native_storage_parent' if declaration else '(-1)'
    reset='native_storage_parent=-1;' if declaration else ''
    suffix='''
void test_reset(int install,int fault){installed=install;mode=fault;
 repository_context=repository_handle=0;qualified=opened=attached=closed=0;RESET}
int test_call(int library){return af_bootstrap406_bind_native_storage(library);}
int test_owned(void){return RETAINED;}
int test_context(void){return repository_context!=0;}
int test_qualified(void){return qualified;}
int test_opened(void){return opened;}
int test_attached(void){return attached;}
int test_closed(void){return closed;}
int test_media_result(void){return native_media_result;}
'''.replace('RESET',reset).replace('RETAINED',retained)
    build=tmp_path_factory.mktemp('binding-owner')
    source=build/'binding.c';target=build/'binding.dylib'
    source.write_text(PREFIX+declared+'\n'+body+suffix)
    # 单元只替换原服务边界；两个原绑定函数逐字保留，不复制其状态逻辑。
    assert body in source.read_text()
    mode=['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']
    command=['clang',*mode,'-std=c11','-O2','-Wall','-Wextra','-Werror',
             '-I'+str(NATIVE),str(source),'-o',str(target)]
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    library=c.CDLL(str(target));library.test_reset.argtypes=[c.c_int,c.c_int]
    library.test_call.argtypes=[c.c_int]
    library.source_sha256=hashlib.sha256(raw.encode()).hexdigest()
    return library

def snapshot(api):
    return tuple(getattr(api,'test_'+name)() for name in ('owned','context','qualified','opened','attached','closed'))

def test_default_closed_has_no_io(api):
    for installed,argument in [(0,-1),(1,-2)]:
        api.test_reset(installed,0)
        assert api.test_call(argument)==-4
        assert snapshot(api)==(-1,0,0,0,0,0)

def test_success_retains_qualification_fd_before_publishing(api):
    # 若旧实现仍在绑定后close，则该服务边界会返回IO并暴露“失败却已attached”。
    api.test_reset(1,3)
    assert api.test_call(-1)==0
    assert api.test_media_result()==-6
    assert snapshot(api)==(42,1,1,1,1,0)
    assert api.test_call(-1)==-4
    assert snapshot(api)==(42,1,1,1,1,0)

@pytest.mark.parametrize('mode,result',[(1,-6),(2,-5)])
def test_partial_binding_keeps_context_and_parent_together(api,mode,result):
    api.test_reset(1,mode)
    assert api.test_call(42)==result
    assert snapshot(api)==(42,1,1,1,0,0)
    assert api.test_call(-1)==-4
    assert snapshot(api)==(42,1,1,1,0,0)

def test_failure_before_context_closes_qualification_fd(api):
    api.test_reset(1,4)
    assert api.test_call(-1)==-5
    assert snapshot(api)==(-1,0,1,0,0,1)

def test_close_failure_without_context_blocks_retry_and_never_attaches(api):
    api.test_reset(1,5)
    assert api.test_call(-1)==-6
    assert snapshot(api)==(42,0,1,1,0,1)
    assert api.test_call(-1)==-4
    assert snapshot(api)==(42,0,1,1,0,1)
