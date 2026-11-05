"""真实包装器的宿主端口联验；替换固定地址，不执行ARM或硬件。"""
from pathlib import Path
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'
PORTS = r'''
#include "af_cp_capture406.h"
#include "af_cp_capture_fields406.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static uint32_t test_heap=0x10000,object=0x71000000;
static uint8_t shadow_image[84],d[0x3a],g[8],f[0x4e];
static AfCpGamma406Tone shadow_tone;
static uint32_t test_request_id=77;
static uint32_t a_request_id=77,request_race;
static AfCpInput406Token request_token;
static AfCpRuntimeAsset406 race_asset;
static uint8_t r_image[0x200],root_image[8],operation_image[12];
static uint32_t root_address=0x72000000,operation_address=0x72001000,pipe_address=0x72002000;
static unsigned request_valid,color_seen,color_calls,r_calls;
static unsigned allocations,frees,births,rebuilds,reverses,formats,gammas,releases,pools,restores;
static unsigned scenario,seen,allocation_failure,heap_race;
static void *allocation;
static void *test_alloc(uint32_t);
static void test_free(void *);
static const uint8_t *test_address(uint32_t);
static int test_thread(uint32_t *);
static uint32_t test_birth(uint32_t),test_release(uint32_t),test_pool(uint32_t),test_rebuild(uint32_t);
static uint32_t test_restore(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t);
static uint32_t test_reverse(uint32_t),test_gamma(uint32_t),test_format(uint32_t,uint32_t);
static uint32_t test_rsource(uint32_t,uint32_t,uint32_t,uint32_t),test_color(uint32_t,uint32_t,uint32_t,uint32_t);
'''
DRIVER = r'''
static const uint8_t offsets[47]={0,4,5,6,7,8,9,10,11,12,13,14,16,17,18,19,20,21,22,
 24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,48,49,50,51,52,53,54,55,56,57};
static void put(void *p,uint32_t x){memcpy(p,&x,4);}
static void *test_alloc(uint32_t n){
 assert(!capture.guard&&n==490u*112u+af_cp_capture_color406_bytes()&&n<65536u);++allocations;
 if(allocation_failure)return 0;
 allocation=malloc(n);assert(allocation);memset(allocation,scenario==9?0xa5:0,n);
 if(heap_race)test_heap++;return allocation;
}
static void test_free(void *p){assert(!capture.guard&&p==allocation);++frees;free(p);allocation=0;}
static const uint8_t *test_address(uint32_t address){
 assert(!capture.guard);
 if(address==root_address)return root_image;
 if(address==operation_address)return operation_image;
 if(address==object+AF_CP_CAPTURE406_D)return d;
 if(address==object+AF_CP_CAPTURE406_G)return g;
 if(address==0x1f6dfdc||address==0x1f6e390)return f;
 if(address==object+0x5ae8)return (const uint8_t *)&a_request_id;
 if(address>=object+0x20&&address<object+0x220)return r_image+address-object-0x20;
 assert(!"未知原地址");return 0;
}
static int test_thread(uint32_t *out){
 assert(!capture.guard);*out=22;
 if(request_race){request_race=0;af_cp_capture406_request_invalidate_target();
  test_request_id=78;request_token.version=42;request_token.epoch=request_token.origin_snapshot_epoch=4;
  assert(!af_cp_capture406_request_publish_target(&request_token,78,&race_asset));}
 return 0;
}
int af_cp_override406_read_input(uint32_t at,AfCpInput406Token *out){
 assert(at==AF_CP_INPUT406_REQUEST&&!capture.guard);if(!request_valid)return AF_EMPTY;
 *out=request_token;return AF_OK;
}
int af_cp_components406_shadow_target(AfCpGamma406Tone *tone,uint8_t image[84]){
 assert(!capture.guard);*tone=shadow_tone;memcpy(image,shadow_image,84);return AF_OK;
}
static uint32_t test_birth(uint32_t pool){assert(pool==15&&!capture.guard);++births;return object;}
static uint32_t test_reverse(uint32_t address){
 assert(address==object+AF_CP_CAPTURE406_D&&!capture.guard);++reverses;
 uint8_t fields[47];assert(!af_cp_capture_fields406_shadow(shadow_image,fields));
 for(unsigned i=0;i<47;++i)d[offsets[i]]=fields[i];return 43;
}
static uint32_t test_rebuild(uint32_t a){
 assert(a==object&&!capture.guard);++rebuilds;
 assert(af_cp_capture406_reverse_target(a+AF_CP_CAPTURE406_D)==43);return 44;
}
static uint32_t test_format(uint32_t address,uint32_t formatter){
 assert(address==object+AF_CP_CAPTURE406_D&&!capture.guard);
 assert(formatter==(g[0]?0x1f6e390u:0x1f6dfdcu));++formats;memset(f,0,sizeof f);put(f+0x30,6);f[0x38]=6;return 45;
}
static uint32_t test_gamma(uint32_t address){
 assert(address==object+AF_CP_CAPTURE406_G&&!capture.guard);++gammas;
 uint32_t formatter=g[0]?0x1f6e390u:0x1f6dfdcu,output=g[0]?0x1f709f4u:0x1f6ff74u;
 assert(af_cp_capture406_format_target(object+AF_CP_CAPTURE406_D,formatter)==45);
 if(scenario==3)af_cp_capture406_reset_target();
 AfCpGamma406Tone tone;AfCpCapture406Token token;uint8_t image[0x4e];
 int status=af_cp_capture406_read_target(formatter,output,&tone,&token,image);
 if(seen){assert(status==AF_OK&&tone.version==9&&tone.tone[0]==128);assert(!af_cp_capture406_current_target(&token));}
 else assert(status!=AF_OK);
 return 46;
}
static uint32_t test_restore(uint32_t b,uint32_t r,uint32_t p,uint32_t mode,uint32_t extra){
 assert(b==object+AF_CP_CAPTURE406_B&&r==11&&p==12&&mode==13&&extra==0x12345678&&!capture.guard);
 ++restores;return 47;
}
static uint32_t test_release(uint32_t a){
 assert(a==object&&!capture.guard);++releases;
 /* 原最终归还必须在伴随身份撤销之后执行。 */
 if(af_cp_capture406_target_ready())assert(capture.records[0].a==0);return 48;
}
static uint32_t test_pool(uint32_t force){
 assert(force<=1&&!capture.guard);++pools;
 if(capture.magic&&!capture.fault){assert(capture.pool_busy);for(unsigned i=0;i<490;++i)assert(!capture.records[i].a);}
 return 49;
}
static uint32_t test_rsource(uint32_t r,uint32_t src,uint32_t a,uint32_t b){
 assert(r==object+0x20&&(src==AF_CP_INPUT406_REQUEST||src==AF_CP_INPUT406_REQUEST+4)&&a==11&&b==12);
 ++r_calls;put(r_image+0x150,scenario==13?249u:scenario==14?1u:0u);put(r_image+0x104,0);r_image[0x108]=(uint8_t)request_token.actual.params[0];
 r_image[0x109]=(uint8_t)request_token.actual.params[4];
 for(unsigned i=0;i<3;++i)r_image[0x1c9+i]=(uint8_t)request_token.actual.params[5+i];return 50;
}
static uint32_t test_color(uint32_t root,uint32_t pipe,uint32_t arg2,uint32_t arg3){
 assert(root==root_address&&pipe==pipe_address&&arg2==0&&arg3==13);++color_calls;
 int status=af_cp_capture406_color_scope_target(object+0x20);
 if(scenario==11||scenario==12)assert(status!=AF_OK);else assert(status==AF_OK);
 AfCpCaptureColor406View view;int result=af_cp_capture406_color_view_target(&view);
 if(color_seen){assert(result==AF_OK&&view.version==41&&view.asset->recipe.matrix[0]==33);
  assert(!af_cp_capture406_color_current_target(&view));}
 else assert(result!=AF_OK);
 return 51;
}
static void color_scenario(void){
 request_valid=1;request_token=(AfCpInput406Token){.version=41,.source=AF_CP_INPUT406_REQUEST,
  .epoch=2,.origin_snapshot_epoch=2,.slot=7,.mode=AF_CP_OVERRIDE_USER,.flags=AF_CP_INPUT406_USER_VERSION,
  .actual={.base=0,.params={1,-2,3,4,5,6,3,8}}};
 AfCpRuntimeAsset406 asset={.base=0,.native_mode=1};asset.model_sha256[0]=1;asset.recipe.matrix[0]=33;
 af_cp_capture406_request_invalidate_target();assert(!af_cp_capture406_request_publish_target(&request_token,77,&asset));
 race_asset=asset;if(scenario==10)request_race=1;
 assert(af_cp_capture406_rsource_target(object+0x20,AF_CP_INPUT406_REQUEST+(scenario==7?4:0),11,12)==50&&r_calls==1);
 color_seen=scenario!=7&&scenario!=10&&scenario!=11&&scenario!=12&&scenario!=13&&scenario!=14;
 if(scenario==8){
  af_cp_capture406_request_invalidate_target();request_token.version=42;request_token.epoch=request_token.origin_snapshot_epoch=4;
  asset.recipe.matrix[0]=77;assert(!af_cp_capture406_request_publish_target(&request_token,77,&asset));
 }
 memset(&asset,0,sizeof asset); /* 原调用栈销毁，旧A仍必须拥有版本41的独立深副本。 */
 put(root_image,operation_address);operation_image[1]=scenario==11?0:1;
 put(operation_image+4,scenario==12?1:0);put(operation_image+8,object+0x20);
 assert(af_cp_capture406_color_target(root_address,pipe_address,0,13)==51&&color_calls==1);
 AfCpCaptureColor406View view;assert(af_cp_capture406_color_view_target(&view)==AF_EMPTY);
 assert(af_cp_capture406_target_ready());
}
int main(int argc,char **argv){
 assert(argc==2);scenario=(unsigned)atoi(argv[1]);
 shadow_tone=(AfCpGamma406Tone){.version=9,.input_source=0x1653c68,.input_epoch=18,
 .snapshot_epoch=12,.slot=7,.ticket=37,.source_epoch=20,.tone={128,-32,0}};
 shadow_image[0]=shadow_image[8]=shadow_image[11]=1;put(shadow_image+0x30,6);
 if(scenario==4||scenario==5){
  allocation_failure=scenario==4;heap_race=scenario==5;assert(af_cp_capture406_bind_target()!=AF_OK);
  assert(!af_cp_capture406_target_ready()&&allocations==1&&!frees);
  assert(af_cp_capture406_birth_target(15)==object&&births==1);free(allocation);return 0;
 }
 assert(!af_cp_capture406_bind_target()&&af_cp_capture406_target_ready());
 assert(!af_cp_capture406_bind_target()&&allocations==1&&!frees);
 assert(af_cp_capture406_birth_target(15)==object&&births==1);
 assert(af_cp_capture406_rebuild_target(object)==44&&rebuilds==1&&reverses==1);
 if(scenario>=6)color_scenario();
 if(scenario==1){assert(af_cp_capture406_restore_target(object+AF_CP_CAPTURE406_B,11,12,13,0x12345678)==47&&restores==1);}
 if(scenario==2)test_heap++;
 seen=scenario==0||scenario>=6;
 /* 已发布shadow换代不能覆盖Capture自有的按值版本。 */
 shadow_tone.version=10;
 for(unsigned i=0;i<2;++i){g[0]=(uint8_t)i;assert(af_cp_capture406_gamma_target(object+AF_CP_CAPTURE406_G)==46);}
 assert(formats==2&&gammas==2);
 if(scenario<=1)assert(af_cp_capture406_target_ready());
 if(scenario==2||scenario==3)assert(!af_cp_capture406_target_ready());
 assert(af_cp_capture406_release_target(object)==48&&releases==1);
 assert(af_cp_capture406_pool_target(1)==49&&pools==1);
 assert(allocations==1&&!frees);free(allocation);return 0;
}
'''


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('capture-target406')
    product = (NATIVE / 'af_cp_capture_target406.c').read_text()
    replacements = {
        '#if defined(__arm__) && defined(AF_CP_CAPTURE406)': '#if 1',
        '*(const volatile uint32_t *)(uintptr_t)0x195e254u': 'test_heap',
        '*(const volatile uint32_t *)(uintptr_t)0x163f3c8u': 'test_request_id',
        '(const volatile uint8_t *)(uintptr_t)address': 'test_address(address)',
        '((int(*)(uint32_t *))(uintptr_t)0x5c88dcu)': 'test_thread',
        '((void *(*)(uint32_t))(uintptr_t)0x5ef69cu)': 'test_alloc',
        '((void(*)(void *))(uintptr_t)0x5ef73cu)': 'test_free',
        '((uint32_t(*)(uint32_t))(uintptr_t)0xae0317u)': 'test_birth',
        '((uint32_t(*)(uint32_t))(uintptr_t)0xae0361u)': 'test_release',
        '((uint32_t(*)(uint32_t))(uintptr_t)0xae07e1u)': 'test_pool',
        '((uint32_t(*)(uint32_t))(uintptr_t)0xaebdc3u)': 'test_rebuild',
        '((uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t))(uintptr_t)0x833cb5u)': 'test_restore',
        '((uint32_t(*)(uint32_t))(uintptr_t)0x845cf5u)': 'test_reverse',
        '((uint32_t(*)(uint32_t))(uintptr_t)0x845db9u)': 'test_gamma',
        '((uint32_t(*)(uint32_t,uint32_t))(uintptr_t)0xaa81cbu)': 'test_format',
        '((uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t))(uintptr_t)0x4596f5u)': 'test_rsource',
        '((uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t))(uintptr_t)0x719ef7u)': 'test_color',
    }
    for before, after in replacements.items():
        assert product.count(before) == (3 if after=='test_request_id' else 1), before
        product = product.replace(before, after)
    source = directory / 'driver.c'
    source.write_text(PORTS + product + DRIVER)
    target = directory / 'driver'
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                             '-DAF_CP_CAPTURE406=1','-DAF_CP_CAPTURE_INPUT406=1',
                             '-I'+str(NATIVE), str(source), str(NATIVE/'af_cp_capture406.c'),
                             str(NATIVE/'af_cp_capture_fields406.c'),str(NATIVE/'af_cp_capture_color406.c'),
                             str(NATIVE/'af_slots.c'), '-o', str(target)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return target


@pytest.mark.parametrize('scenario', range(15))
def test_real_target_wrappers_keep_original_calls_and_lifetime(binary, scenario):
    result = subprocess.run([str(binary), str(scenario)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
