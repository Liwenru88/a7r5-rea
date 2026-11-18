"""逐字抽取loader媒体绑定，宿主仅替换动态装载/原服务边界。"""
from pathlib import Path
import ctypes as C, hashlib, subprocess, sys
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
N=ROOT/'a7r5-firmware-features/custom-filters/native'
SOURCE=ROOT/'a7r5-firmware-features/custom-filters/experiments/packaging406/loader/af_bootstrap406.c'
FSYS=N
PREFIX=r'''
#include <string.h>
#include <stdint.h>
#include "af_ap_media.h"
#include "af_fsys406.h"
#include "af_media_snapshot406.h"
#define AF_AP_IMAGE_SPAN 0x8e84000u
#define COUNT(a) (sizeof(a)/sizeof((a)[0]))
typedef struct {const char *path;size_t bytes;} BootFile;
typedef struct {const char *name;uintptr_t at;} BootSymbol;
typedef struct {uintptr_t at;uint32_t before;} BootCheck;
typedef struct {void *dli_fbase;} DlInfo;
static const BootFile boot_fsys={"TEST_NO_FILE_IO",708568};
static const BootSymbol boot_fsys_exports[]={
 {"Fsys_Open",0x35e90},{"Fsys_Read",0x36120},{"Fsys_Close",0x36004},
 {"Fsys_FindFirst",0x371d4},{"Fsys_FindNext",0x37390}};
static const BootCheck boot_fsys_checks[20]={{0}};
static unsigned installed,native_media_bound,native_media_importer_bound,native_media_cards_bound;
int af_bootstrap406_bind_native_media(unsigned slot);
static int native_media_result;
static void *repository_context,*repository_handle,*fsys_handle,*native_media_source;
static AfFsys406 native_media[2];
static uintptr_t ap_base,fsys_base;
static unsigned io,init_calls,map_calls,bind_calls,import_calls,rebind_calls,snapshot_calls,word_calls;
static unsigned codec_calls,policy_calls,maps_calls;
static int mode;
static AfApMediaProviderBinding current;
static AfApMediaCardService cards;
static unsigned char work[AF_MEDIA_SOURCE_MAX];
static void bytes(void *a,const void *b,size_t n){memcpy(a,b,n);}
static int prepared(void *a,const AfMediaProvider *b,const AfMediaList *d,const AfApMediaInfo *i){(void)a;(void)b;(void)d;(void)i;return 0;}
static int requested(void *a,AfApManageRequest *b){(void)a;(void)b;return 0;}
static int cancelled(void *a){(void)a;return 0;}
static int importer(void *a,AfApMediaProviderImporter *b){(void)a;
 *b=(AfApMediaProviderImporter){AF_AP_MEDIA_VERSION,sizeof(*b),(void *)0x9999,prepared,requested,cancelled};return 0;}
static int bind_provider(const AfApMediaProviderBinding *b){bind_calls++;
 if(mode==4)return AF_BUSY;current=*b;return AF_OK;}
static int rebind_provider(const AfApMediaProviderBinding *b){rebind_calls++;
 if(mode==6)return AF_BUSY;current=*b;return AF_OK;}
static int bind_importer(const AfApMediaProviderImporter *b){(void)b;import_calls++;return mode==5?AF_STALE:AF_OK;}
static int bind_cards(const AfApMediaCardService *b){if(mode==7)return AF_STALE;cards=*b;return AF_OK;}
static void *ui_symbol(const char *n){
 if(!strcmp(n,"af_ap_media_provider_bind"))return (void *)bind_provider;
 if(!strcmp(n,"af_ap_media_provider_rebind"))return (void *)rebind_provider;
 if(!strcmp(n,"af_ap_media_provider_importer_bind"))return (void *)bind_importer;
 if(!strcmp(n,"af_ap_media_card_service_bind"))return (void *)bind_cards;
 return 0;}
#define UF(name,type) ((type)ui_symbol(name))
static void *file_map(const BootFile *f,int writable){(void)f;(void)writable;io++;return (void *)1;}
static int munmap(void *p,size_t n){(void)p;(void)n;return 0;}
static void *dlopen(const char *p,int flags){(void)p;(void)flags;return (void *)1;}
static void *dlsym(void *h,const char *n){(void)h;
 if(!strcmp(n,"af_repository_service_media_provider_importer"))return (void *)importer;
 for(unsigned i=0;i<5;++i)if(!strcmp(n,boot_fsys_exports[i].name))return (void *)(0x50000000u+boot_fsys_exports[i].at+(mode==1&&i==4?4:0)+(mode==10?4096u:0));
 return 0;}
static int dladdr(const void *p,DlInfo *d){d->dli_fbase=(void *)(uintptr_t)(0x50000000u+(mode==10||(mode==2&&(uintptr_t)p==0x50037390u)?4096u:0));return 1;}
static int maps(void){maps_calls++;return mode!=9;}
static int fsys_codec_mapping(uintptr_t base){codec_calls++;return base&&mode!=8;}
int af_fsys406_utf8_policy(uintptr_t base,size_t span){policy_calls++;
 return base==fsys_base&&span==AF_FSYS406_LIBRARY_SPAN&&mode!=11?AF_OK:AF_STALE;}
static int word(uintptr_t at,uint32_t before,int flags){(void)at;(void)before;word_calls++;return flags==5&&!(mode==3&&word_calls==20);}
static void *mmap(void *p,size_t n,int prot,int flags,int fd,long offset){
 (void)p;(void)prot;(void)flags;(void)fd;(void)offset;
 if(n!=AF_MEDIA_SOURCE_MAX)return (void *)-1;map_calls++;return work;}
int af_ap_media_snapshot406(uintptr_t base,size_t span,AfMediaSnapshot406 *out){(void)base;(void)span;(void)out;snapshot_calls++;return AF_STALE;}
int af_fsys406_init(AfFsys406 *s,const AfFsys406Binding *b){
 init_calls++;if(b->slot>1||s!=&native_media[b->slot]||b->snapshot_context!=&ap_base||
 b->encoding_context!=&fsys_base||!b->utf8_policy)return AF_INVALID;
 s->binding=*b;s->initialized=1;return AF_OK;}
int af_fsys406_provider(AfFsys406 *s,AfMediaProvider *p){
 if(!s->initialized)return AF_INVALID;*p=(AfMediaProvider){AF_MEDIA_PROVIDER_VERSION,sizeof(*p),s,0,0};return AF_OK;}
'''
SUFFIX=r'''
void reset(int ready,int fault){
 installed=(unsigned)ready;mode=fault;repository_context=(void *)0x1234;repository_handle=(void *)1;
 fsys_handle=native_media_source=0;fsys_base=0;native_media_bound=native_media_importer_bound=native_media_cards_bound=0;
 codec_calls=policy_calls=maps_calls=0;
 memset(&cards,0,sizeof(cards));
 native_media_result=AF_EMPTY;io=init_calls=map_calls=bind_calls=import_calls=rebind_calls=snapshot_calls=word_calls=0;
 memset(native_media,0,sizeof(native_media));memset(&current,0,sizeof(current));}
void fault(int value){mode=value;word_calls=0;}
int call(unsigned slot){return af_bootstrap406_bind_native_media(slot);}
int choose(unsigned slot){return cards.select?cards.select(cards.context,slot):AF_MANAGE_NOT_READY;}
int cards_bound(void){return (int)native_media_cards_bound;}
int encoding(int bad_context){AfFsys406 *s=current.provider.context;
 return s?s->binding.utf8_policy(bad_context?&ap_base:s->binding.encoding_context):AF_MANAGE_NOT_READY;}
unsigned encoding_calls(unsigned what){return what==0?maps_calls:what==1?codec_calls:policy_calls;}
unsigned state(unsigned what){switch(what){case 0:return io;case 1:return init_calls;case 2:return map_calls;
 case 3:return bind_calls;case 4:return import_calls;case 5:return rebind_calls;case 6:return snapshot_calls;
 case 7:return native_media_bound;case 8:return native_media_importer_bound;case 9:return current.provider.context==&native_media[0];
 case 10:return current.provider.context==&native_media[1];case 11:return current.source==work;default:return 0;}}
'''

@pytest.fixture(scope='module')
def api(tmp_path_factory):
    raw=SOURCE.read_text();begin=raw.index('static int native_media_snapshot(')
    body=raw[begin:raw.index('#ifdef AF_BOOTSTRAP_HOST_TEST',begin)]
    output=tmp_path_factory.mktemp('native-media-loader-review')
    source=output/'review.c';source.write_text(PREFIX+body+SUFFIX)
    lib=output/'review.dylib'
    cmd=['clang','-dynamiclib' if sys.platform=='darwin' else '-shared','-fPIC','-O1','-Wall','-Wextra','-Werror',
         '-I'+str(N),'-I'+str(FSYS),str(source),'-o',str(lib)]
    run=subprocess.run(cmd,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=C.CDLL(str(lib));result.reset.argtypes=[C.c_int,C.c_int]
    result.call.argtypes=[C.c_uint];result.state.argtypes=[C.c_uint];result.fault.argtypes=[C.c_int]
    result.choose.argtypes=[C.c_uint]
    result.source_sha256=hashlib.sha256(raw.encode()).hexdigest()
    return result

def state(api):return tuple(api.state(i) for i in range(12))

def test_default_closed_and_fifth_export_qualifiers(api):
    api.reset(0,0);assert api.call(0)==-4 and state(api)==(0,)*12
    for fault in (1,2,3,8):
        api.reset(1,fault);assert api.call(0)==-5
        assert state(api)[1:9]==(0,)*8

@pytest.mark.parametrize('failure',[5,7])
def test_partial_importer_or_card_service_failure_never_reports_bound(api,failure):
    api.reset(1,failure);assert api.call(0)==-5
    before=state(api);assert before[2:5]==(1,1,1) and before[7:9]==(1,int(failure==7))
    assert api.cards_bound()==0 and api.choose(1)==-21
    api.fault(0);assert api.call(1)==-21
    assert state(api)==before

def test_rebind_busy_keeps_prior_resident_provider(api):
    api.reset(1,0);assert api.call(0)==0
    assert api.cards_bound()==1
    first=state(api);assert first[6]==0 and first[9:12]==(1,0,1)
    api.fault(6);assert api.call(1)==-4
    busy=state(api);assert busy[9:12]==(1,0,1) and busy[2]==1 and busy[6]==0
    api.fault(0);assert api.choose(1)==0
    final=state(api);assert final[9:12]==(0,1,1) and final[1]==2 and final[2]==1 and final[6]==0

def test_utf8_qualification_is_deferred_and_refreshed(api):
    api.reset(1,0);assert api.call(0)==0
    assert api.encoding_calls(2)==0  # init只复制驻留策略，不读编码状态。
    before=api.encoding_calls(0)
    assert api.encoding(1)==-21 and api.encoding_calls(0)==before
    assert api.encoding(0)==0 and api.encoding_calls(0)==before+1
    assert api.encoding_calls(2)==1
    for failure in (8,9):
        api.fault(failure);assert api.encoding(0)==-5
        assert api.encoding_calls(2)==1  # 映射不合格时绝不先解引用原库。
    api.fault(11);assert api.encoding(0)==-5 and api.encoding_calls(2)==2
    api.fault(10);assert api.call(1)==-5
    assert state(api)[9:12]==(1,0,1)  # 一致但改变的模块基址也不能替换驻留身份。
