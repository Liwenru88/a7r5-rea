"""抽取真实loader存储胶合；仅显式替换文件映射和驻留服务边界。"""
from pathlib import Path
import re
import subprocess

import pytest

from test_ap_imaging_provider import function


HOME = Path(__file__).resolve().parents[1]
NATIVE = HOME / 'native'
LOADER = HOME / 'experiments/packaging406/loader/af_bootstrap406.c'


PREFIX = r'''
#include "af_ap_manage.h"
#include "af_labels.h"
#include <assert.h>
#include <string.h>
typedef struct {const char *path;size_t bytes;} BootFile;
static const BootFile boot_repository={"TEST_NO_FILE_ACCESS",4};
static AfCatalog real_catalog;static AfLabels real_labels;
static AfCatalog *catalog=&real_catalog;static AfLabels *labels=&real_labels;
static unsigned installed,mode,io_calls,lookups,reference_calls,event_count;
static unsigned events[8];static uint8_t mapped[4],handle_token,service_token;
static void *repository_handle,*repository_context;
static uint32_t live_caps=AF_MANAGE_CAP_PERSIST,published_caps;
static void event(unsigned value){assert(event_count<8);events[event_count++]=value;}
static void *file_map(const BootFile *file,int writable){
 assert(file==&boot_repository&&!writable);++io_calls;return mapped;
}
static int fake_munmap(void *pointer,size_t bytes){assert(pointer==mapped&&bytes==4);++io_calls;return 0;}
static void *fake_dlopen(const char *path,int flags){
 assert(!strcmp(path,"TEST_NO_FILE_ACCESS")&&flags==2);++io_calls;return &handle_token;
}
static void *open_service(int fd,AfCatalog *actual_catalog,AfLabels *actual_labels,int *status){
 assert(fd==44&&actual_catalog==catalog&&actual_labels==labels);event(1);*status=AF_OK;return &service_token;
}
static int bind_library(void *context,int fd){
 assert(context==&service_token&&fd==73);event(2);live_caps|=AF_MANAGE_CAP(AF_MANAGE_EXPORT);return AF_OK;
}
static int bind_reference(void *context){
 assert(context==&service_token);event(3);++reference_calls;
 if(mode==2)return AF_IO;
 if(mode==0)live_caps|=AF_MANAGE_CAP(AF_MANAGE_IMPORT);
 return AF_OK;
}
static uint32_t capabilities(void *context){assert(context==&service_token);event(4);return live_caps;}
static int pump(void *context,AfApManage *manager){assert(context==&service_token);(void)manager;return AF_OK;}
static int service_bind(const AfApManageService *service){
 assert(service->version==1&&service->bytes==sizeof(*service)&&!service->reserved);
 assert(service->context==&service_token&&service->pump==pump);
 assert(service->capabilities==live_caps);event(5);published_caps=service->capabilities;return AF_OK;
}
static void *fake_dlsym(void *handle,const char *name){
 assert(handle==&handle_token);++lookups;
 if(!strcmp(name,"af_repository_service_open"))return (void *)open_service;
 if(!strcmp(name,"af_repository_service_bind_library"))return (void *)bind_library;
 if(!strcmp(name,"af_repository_service_capabilities"))return (void *)capabilities;
 if(!strcmp(name,"af_repository_service_pump"))return (void *)pump;
 if(!strcmp(name,"af_reference_import_bind"))return mode==3?0:(void *)bind_reference;
 assert(0);return 0;
}
static void *ui_symbol(const char *name){assert(!strcmp(name,"af_ap_manage_service_bind"));return (void *)service_bind;}
#define munmap fake_munmap
#define dlopen fake_dlopen
#define dlsym fake_dlsym
#define UF(name,type) ((type)ui_symbol(name))
'''


MAIN = r'''
int main(int argc,char **argv){
 assert(argc==2);assert(af_bootstrap406_reference_status()!=AF_OK);
 if(!strcmp(argv[1],"closed")){
  assert(af_bootstrap406_bind_storage(44,73)==AF_BUSY);
  installed=1;
  assert(af_bootstrap406_bind_storage(-1,73)==AF_BUSY);
  assert(af_bootstrap406_bind_storage(44,-2)==AF_BUSY);
  assert(!event_count&&!io_calls&&!lookups&&!reference_calls&&!repository_context);
  assert(af_bootstrap406_reference_status()!=AF_OK);return 0;
 }
 if(!strcmp(argv[1],"success"))mode=0;
 else if(!strcmp(argv[1],"caps-closed"))mode=1;
 else if(!strcmp(argv[1],"reference-failed"))mode=2;
 else{assert(!strcmp(argv[1],"missing-symbol"));mode=3;}
 installed=1;assert(af_bootstrap406_bind_storage(44,73)==AF_OK);
 const unsigned present[]={1,2,3,4,5},missing[]={1,2,4,5};
 const unsigned *expected=mode==3?missing:present;
 assert(event_count==(mode==3?4u:5u)&&!memcmp(events,expected,event_count*sizeof(events[0])));
 assert(reference_calls==(mode==3?0u:1u));
 assert(published_caps==(AF_MANAGE_CAP_PERSIST|AF_MANAGE_CAP(AF_MANAGE_EXPORT)|
  (mode==0?AF_MANAGE_CAP(AF_MANAGE_IMPORT):0)));
 if(mode<2)assert(af_bootstrap406_reference_status()==AF_OK);
 else if(mode==2)assert(af_bootstrap406_reference_status()==AF_IO);
 else assert(af_bootstrap406_reference_status()!=AF_OK);
 unsigned old_io=io_calls,old_lookups=lookups;
 assert(af_bootstrap406_bind_storage(44,73)==AF_BUSY);
 assert(old_io==io_calls&&old_lookups==lookups);return 0;
}
'''


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    raw = LOADER.read_text()
    declaration = re.search(r'static\s+int\s+reference_import_result\s*=\s*[^;]+;', raw)
    assert declaration, '真实loader缺少独立参考转换绑定结果'
    body = function(raw, 'int af_bootstrap406_bind_storage(')
    status = function(raw, 'int af_bootstrap406_reference_status(')
    folder = tmp_path_factory.mktemp('loader-reference-binding')
    source, binary = folder / 'driver.c', folder / 'driver'
    source.write_text(PREFIX + '\n' + declaration.group(0) + '\n' + body + status + MAIN)
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-I' + str(NATIVE), str(source), '-o', str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return binary


@pytest.mark.parametrize('case', ['success', 'caps-closed'])
def test_reference_binding_precedes_real_capability_and_ui_publication(driver, case):
    run = subprocess.run([str(driver), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize('case', ['reference-failed', 'missing-symbol'])
def test_optional_reference_failure_preserves_persistence_without_import_claim(driver, case):
    run = subprocess.run([str(driver), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_uninstalled_or_invalid_storage_has_no_service_side_effects(driver):
    run = subprocess.run([str(driver), 'closed'], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
