"""逐字抽取provider/原refresh；宿主仅替换已知服务边界，不执行原AP。"""
from pathlib import Path
import subprocess
import pytest

HERE=Path(__file__).resolve().parents[1]
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'

def function(text,signature):
    start=text.index(signature);at=text.index('{',start);end=at+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]+'\n'

PREFIX=r'''
#include "af_ap_ui.h"
#include <assert.h>
#include <string.h>
typedef uintptr_t Word;
static Word ap_base=0x1000;
static uint32_t prepared,enabled,selected_valid,refresh_pending,refresh_menu;
static struct {AfApImagingBinding binding;uint32_t requested,busy;int result;} imaging;
static struct {AfApImagingProvider binding;uint32_t state,busy;int result;} imaging_provider;
static Word ap_address(Word offset){return ap_base+offset;}
static int ui_manage_poll(void *m){(void)m;return 0;}
static void ui_clear_before_pump(void){}
int af_ap_manage_service_poll(void){return 0;}
int af_ap_targets_refresh(void){return 0;}
int af_ap_browser_refresh(void){return 0;}
int af_ap_cards_refresh(void){return 0;}
int af_ap_media_refresh(void){return 0;}
int af_ap_manage_menu_refresh(void){return 0;}
static Word af_stock_refresh(void *m){(void)m;return 7;}
static void imaging_dispatch(void){}
static uint32_t current_menu(void){return 0;}
static int restricted_layout(void){return 0;}
static Word manager[0x3c0/sizeof(Word)];
static unsigned resolve_calls,sends,cap_calls;
static uint32_t caps;
static int fault;
static uint32_t capabilities(void *p){assert(p==&resolve_calls);++cap_calls;return caps;}
static int send_input(void *p,uint32_t s,const AfPreset *v){(void)p;(void)s;(void)v;++sends;return 0;}
static int factory(void *p,uint32_t s,AfPreset *v){(void)p;(void)s;(void)v;return 0;}
static int release_input(void *p){(void)p;return 0;}
Word af_ap_refresh(void *);
static int binding_resolve(void *p,AfApImagingBinding *out){
 assert(p==&resolve_calls);++resolve_calls;
 if(fault==1)return AF_IO;
 if(!caps)return AF_BUSY;
 /* 重入原刷新不得递归解析或发送。 */
 assert(af_ap_refresh(manager)==7);
 *out=(AfApImagingBinding){fault==2?99:AF_AP_IMAGING_VERSION,sizeof(*out),&resolve_calls,
     capabilities,send_input,factory,release_input};
 if(fault==3)selected_valid=1;
 return AF_OK;
}
'''

MAIN=r'''
int main(int argc,char **argv){
 assert(argc==2);manager[0]=ap_address(0x58d2fb8);
 assert(af_ap_imaging_provider_result()==AF_MANAGE_NOT_READY);
 AfApImagingProvider p={AF_AP_IMAGING_PROVIDER_VERSION,sizeof(p),&resolve_calls,binding_resolve};
 assert(af_ap_imaging_provider_bind(&p)==0 && !resolve_calls && !sends);
 assert(af_ap_imaging_provider_bind(&p)==AF_BUSY);
 assert(af_ap_imaging_provider_result()==AF_BUSY);
 assert(af_ap_refresh(manager)==7 && !resolve_calls);prepared=1;
 assert(af_ap_refresh(manager)==7 && !resolve_calls);enabled=1;
 Word wrong[0x3c0/sizeof(Word)]={0};assert(af_ap_refresh(wrong)==7&&!resolve_calls);
 selected_valid=1;assert(af_ap_refresh(manager)==7&&!resolve_calls);selected_valid=0;
 if(!strcmp(argv[1],"io"))fault=1;
 else if(!strcmp(argv[1],"malformed")){fault=2;caps=AF_AP_IMAGING_REQUIRED;}
 else if(!strcmp(argv[1],"selected")){fault=3;caps=AF_AP_IMAGING_REQUIRED;}
 else assert(!strcmp(argv[1],"ready"));
 assert(af_ap_refresh(manager)==7 && resolve_calls==1 && !sends);
 if(fault==1 || fault==2){
  assert(af_ap_imaging_provider_result()==(fault==1?AF_IO:AF_INVALID));
  fault=0;caps=AF_AP_IMAGING_REQUIRED;
  assert(af_ap_refresh(manager)==7&&resolve_calls==1&&!imaging.binding.send&&!sends);return 0;
 }
 if(fault==3){
  assert(selected_valid&&af_ap_imaging_provider_result()==AF_BUSY&&!imaging.binding.send);
  assert(af_ap_refresh(manager)==7&&resolve_calls==1);selected_valid=0;fault=0;
 }else{
  assert(af_ap_imaging_provider_result()==AF_BUSY&&!imaging.binding.send);
  assert(af_ap_refresh(manager)==7&&resolve_calls==2);caps=AF_AP_IMAGING_REQUIRED;
 }
 unsigned before=resolve_calls;
 assert(af_ap_refresh(manager)==7 && resolve_calls==before+1 && !sends);
 assert(af_ap_imaging_provider_result()==AF_OK&&imaging.binding.send);
 before=resolve_calls;assert(af_ap_refresh(manager)==7&&resolve_calls==before&&!sends);
 return 0;
}
'''

@pytest.fixture(scope='module')
def provider(tmp_path_factory):
    folder=tmp_path_factory.mktemp('imaging-provider');source=folder/'provider.c';binary=folder/'provider'
    ui=(HERE/'native/af_ap_ui.c').read_text()
    signatures=('int af_ap_imaging_bind(', 'int af_ap_imaging_provider_bind(',
                'int af_ap_imaging_provider_result(', 'static void imaging_provider_poll(', 'Word af_ap_refresh(')
    signatures=signatures[:-1]+('static void imaging_pending_poll(',signatures[-1])
    source.write_text(PREFIX+''.join(function(ui,s) for s in signatures)+MAIN)
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-I'+str(HERE/'native'),'-I'+str(NATIVE),str(source),'-o',str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    return binary

@pytest.mark.parametrize('case',['ready','io','malformed','selected'])
def test_ui_owner_resolves_once_without_automatic_send(provider,case):
    run=subprocess.run([str(provider),case],capture_output=True,text=True)
    assert run.returncode==0,run.stderr

def test_loader_resolver_keeps_admission_and_installed_gates(tmp_path):
    text=(HERE/'experiments/packaging406/loader/af_bootstrap406.c').read_text()
    selected=function(text,'static int native_imaging_resolve(')
    source=tmp_path/'loader.c';binary=tmp_path/'loader'
    source.write_text(r'''
#include "af_ap_ui.h"
#include <assert.h>
#include <string.h>
typedef struct {unsigned tag;} Loaded;
static Loaded requests;
static uintptr_t ap_base=0x70000000;
static unsigned installed,admission_ready,lookups,resolves;
static int ready;
static int resolve(uintptr_t base,AfApImagingBinding *out){
 assert(base==ap_base);++resolves;if(!ready)return AF_BUSY;memset(out,0,sizeof(*out));return AF_OK;
}
static void *symbol(const Loaded *module,const char *name){
 assert(module==&requests&&!strcmp(name,"af_imaging406_binding"));++lookups;return (void *)resolve;
}
'''+selected+r'''
int main(void){
 AfApImagingBinding out;
 assert(native_imaging_resolve(&requests,&out)==AF_INVALID&&!lookups);
 assert(native_imaging_resolve(&ap_base,&out)==AF_BUSY&&!lookups);
 __atomic_store_n(&installed,1,__ATOMIC_RELEASE);
 assert(native_imaging_resolve(&ap_base,&out)==AF_BUSY&&!lookups);
 admission_ready=1;assert(native_imaging_resolve(&ap_base,&out)==AF_BUSY&&lookups==1&&resolves==1);
 ready=1;assert(native_imaging_resolve(&ap_base,&out)==AF_OK&&lookups==2&&resolves==2);return 0;
}
''')
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-I'+str(HERE/'native'),'-I'+str(NATIVE),str(source),'-o',str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
