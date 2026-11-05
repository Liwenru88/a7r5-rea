"""抽取真实启动接线，验证完整配方源先于菜单服务发布；不执行目标文件。"""
import re
import subprocess

import pytest

from test_ap_imaging_provider import function
from test_loader_reference_binding import PREFIX, LOADER, NATIVE

PORTS = r'''
#include "af_imaging406.h"
static unsigned requests;
static int capture_recipe(void *c,uint32_t s,const AfPreset *p,uint64_t a,uint64_t b,AfRecipeTx *out){
 (void)c;(void)s;(void)p;(void)a;(void)b;(void)out;return AF_STALE;
}
static int bind_recipe(const AfImaging406RecipeSource *s){
 assert(s&&s->version==1&&s->bytes==sizeof(*s)&&s->context==&service_token&&s->capture==capture_recipe);
 event(6);return mode==5?AF_IO:AF_OK;
}
static void *symbol(void *module,const char *name){
 assert(module==&requests&&!strcmp(name,"af_imaging406_bind_recipe_source"));return (void *)bind_recipe;
}
'''

MAIN = r'''
int main(int argc,char **argv){
 assert(argc==2);mode=(unsigned)(argv[1][0]-'0');installed=1;
 int result=af_bootstrap406_bind_storage(44,73);
 if(mode==4||mode==5){
  assert(result==AF_STALE&&repository_context==&service_token&&!published_caps);
  assert(events[0]==1&&events[1]==2&&events[2]==3&&event_count==(mode==5?4u:3u));return 0;
 }
 assert(result==AF_OK&&published_caps);
 const unsigned expected[]={1,2,3,6,4,5};
 assert(event_count==6&&!memcmp(events,expected,sizeof expected));return 0;
}
'''


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    raw = LOADER.read_text()
    declaration = re.search(r'static\s+int\s+reference_import_result\s*=\s*AF_EMPTY\s*;', raw)
    assert declaration
    prefix = PREFIX.replace('static void *fake_dlsym(', PORTS + '\nstatic void *fake_dlsym(', 1)
    point = ' if(!strcmp(name,"af_repository_service_open"))'
    assert point in prefix
    prefix = prefix.replace(point,
        ' if(!strcmp(name,"af_repository_service_recipe_capture"))return mode==4?0:(void *)capture_recipe;\n' + point, 1)
    source = tmp_path_factory.mktemp('loader-recipe-source') / 'driver.c'
    source.write_text(prefix + '\n' + declaration.group(0) + '\n' +
                      function(raw, 'int af_bootstrap406_bind_storage(') + MAIN)
    binary = source.with_suffix('')
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-DAF_RECIPE_BRIDGE406', '-I' + str(NATIVE), str(source), '-o', str(binary)],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return binary


@pytest.mark.parametrize('mode', [0, 4, 5], ids=['source-before-menu', 'missing-source-refused', 'binding-failure-refused'])
def test_loader_source_is_real_and_published_once(driver, mode):
    run = subprocess.run([str(driver), str(mode)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
