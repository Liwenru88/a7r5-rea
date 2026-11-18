"""Capture/core与组件的宿主集成；原系统函数为端口，不执行ARM或模拟硬件。"""
from pathlib import Path
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1]/'native'
DRIVER = r'''
#include "af_cp_capture406.h"
#include "af_cp_capture_fields406.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static AfCpComponents406 component;
static AfCpCapture406 capture;
static AfCpCapture406Record records[AF_CP_CAPTURE406_COUNT];
static AfCpRuntimeAsset406 asset;
static AfCpJobs406View view;
static unsigned char prefix[0xe70],main_params[0x4e],g[8],d[0x3a],f[2][0x4e];
static unsigned char source_image[84],shadow_image[84],record[576],main_output[0x466],output[2][0x466];
static const uint32_t object=0x31000000;
static uint32_t thread_id=22;
static unsigned native_calls,private_calls,main_calls,source_calls,reset_calls,reset_notifications,post_calls;
static unsigned shadow_read_race,fail_record,formatter_race,during_core,channel;
static const uint8_t offsets[47]={0,4,5,6,7,8,9,10,11,12,13,14,16,17,18,19,20,21,22,
 24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,48,49,50,51,52,53,54,55,56,57};
static void put(void *p,uint32_t n){unsigned char *b=p;for(unsigned i=0;i<4;++i)b[i]=(unsigned char)(n>>(8*i));}
static uint32_t word(const void *p){const unsigned char *b=p;return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static uint32_t faddr(unsigned c){return c?0x1f6e390u:0x1f6dfdcu;}
static uint32_t oaddr(unsigned c){return c?0x1f709f4u:0x1f6ff74u;}
static int read_memory(void *context,uint32_t address,void *out,size_t n){
 (void)context;
 if(address==AF_CP_COMPONENTS406_SOURCE&&n==84){memcpy(out,source_image,n);return AF_OK;}
 if(address==AF_CP_COMPONENTS406_SHADOW&&n==84){
  memcpy(out,shadow_image,n);
  if(shadow_read_race){shadow_read_race=0;assert(af_cp_components406_gamma_reset(&component,main_params)==106);}
  return AF_OK;
 }
 if(address==object+AF_CP_CAPTURE406_G&&n==sizeof g){memcpy(out,g,n);return AF_OK;}
 if(address==object+AF_CP_CAPTURE406_D&&n==sizeof d){memcpy(out,d,n);return AF_OK;}
 if(address==object+AF_CP_CAPTURE406_G+0xb4&&n==9){memset(out,0,n);((uint8_t *)out)[0]=1;return AF_OK;}
 for(unsigned i=0;i<2;++i)if(address==faddr(i)&&n==sizeof f[i]){memcpy(out,f[i],n);return AF_OK;}
 if(address>=AF_CP_COMPONENTS406_GAMMA_TABLE&&address<AF_CP_COMPONENTS406_GAMMA_TABLE+51*28&&n==4){
  if(formatter_race){formatter_race=0;f[channel][0x39]^=1;}
  put(out,0xdcca0c);return AF_OK;
 }
 if(address==0xdcca0c&&n==sizeof record){if(fail_record)return AF_IO;memcpy(out,record,n);return AF_OK;}
 return AF_IO;
}
static int capture_thread(void *context,uint32_t *out){(void)context;assert(!capture.guard);*out=thread_id;return AF_OK;}
static int shadow(void *context,AfCpGamma406Tone *tone,uint8_t image[84]){
 (void)context;assert(!capture.guard);return af_cp_components406_gamma_snapshot(&component,tone,image);
}
/* 只替换实际target固定地址适配层；运行真实Capture核心和真实component C。 */
int af_cp_capture406_read_target(uint32_t formatter,uint32_t out,AfCpGamma406Tone *tone,
 AfCpCapture406Token *token,uint8_t image[0x4e]){
 return af_cp_capture406_scope_read(&capture,formatter,out,tone,token,image);
}
int af_cp_capture406_current_target(const AfCpCapture406Token *token){return af_cp_capture406_scope_current(&capture,token);}
void af_cp_capture406_reset_target(void){++reset_notifications;(void)af_cp_capture406_reset(&capture);}
/* 本驱动只授Gamma来源；Capture颜色另由真实colour core集成驱动验证。 */
int af_cp_capture406_color_view_target(AfCpCaptureColor406View *v){(void)v;return AF_EMPTY;}
int af_cp_capture406_color_current_target(const AfCpCaptureColor406View *v){(void)v;return AF_EMPTY;}
int af_cp_capture406_color_scope_target(uint32_t r){(void)r;return AF_EMPTY;}
static int current(void *context,const AfCpJobs406View *expected){(void)context;return expected->input.version==view.input.version?AF_OK:AF_STALE;}
static int snapshot(void *context,uint32_t identity,AfCpJobs406View *out){(void)context;*out=view;out->identity=identity;return AF_OK;}
static int worker(void *context,uint32_t identity){(void)context;return identity==2?AF_OK:AF_EMPTY;}
static int address(void *context,const void *p,size_t n,uint32_t *out){
 (void)context;if(n!=0x466)return AF_INVALID;
 if(p==main_output){*out=AF_CP_COMPONENTS406_GAMMA_PACKED0;return AF_OK;}
 for(unsigned i=0;i<2;++i)if(p==output[i]){*out=oaddr(i);return AF_OK;}
 return AF_INVALID;
}
static uint32_t matrix(void *c,void *o,uint32_t s,void *r,uint32_t p){(void)c;(void)o;(void)s;(void)r;(void)p;return 101;}
static uint32_t cc1(void *c,void *o,uint32_t p,void *r){(void)c;(void)o;(void)p;(void)r;return 102;}
static uint32_t native_gamma(void *context,uint32_t mode,const void *params,void *out){
 (void)context;(void)params;if(mode==1)++native_calls;else ++main_calls;
 memcpy((uint8_t *)out+0x24c,record,516);return 103;
}
static uint32_t private_gamma(void *context,uint32_t mode,const void *params,void *out,const void *adjusted){
 (void)context;assert(!memcmp((const uint8_t *)adjusted+0x204,record+0x204,0x1c));
 assert(word((const uint8_t *)adjusted+0x220)==word((const uint8_t *)adjusted+512));
 if(mode==1){
  assert(params==f[channel]&&out==output[channel]);++private_calls;
  if(during_core==1){during_core=0;assert(af_cp_components406_gamma_reset(&component,main_params)==106);}
  else if(during_core==2){AfCpCapture406Token competing;during_core=0;assert(af_cp_capture406_scope_begin(&capture,object+AF_CP_CAPTURE406_G,&competing)==AF_BUSY);}
 }else{assert(!mode&&params==main_params&&out==main_output);++main_calls;}
 memcpy((uint8_t *)out+0x24c,adjusted,516);return 104;
}
static uint32_t source_build(void *context,const void *params){
 (void)context;assert(params==main_params);++source_calls;memset(source_image,0,84);source_image[0]=1;return 105;
}
static uint32_t source_reset(void *context,const void *params){
 (void)context;assert(params==main_params);++reset_calls;memset(source_image,0,84);memset(shadow_image,0,84);return 106;
}
static void original_copy(void *context,void *out,const void *in,size_t n){(void)context;memcpy(out,in,n);}
static void publish(void){
 assert(af_cp_components406_gamma_source(&component,main_params)==105);
 assert(af_cp_components406_gamma(&component,0,main_params,AF_CP_COMPONENTS406_FORMATTER,main_output)==104);
 assert(!af_cp_components406_gamma_copy(&component,shadow_image,source_image,84,
  AF_CP_COMPONENTS406_SHADOW,AF_CP_COMPONENTS406_SOURCE,AF_CP_COMPONENTS406_SHADOW_LR));
}
static void setup(void){
 memset(&component,0,sizeof component);memset(&capture,0,sizeof capture);memset(records,0,sizeof records);
 memset(&view,0,sizeof view);memset(&asset,0,sizeof asset);memset(g,0,sizeof g);memset(d,0,sizeof d);
 memset(source_image,0,sizeof source_image);memset(shadow_image,0,sizeof shadow_image);memset(f,0,sizeof f);
 native_calls=private_calls=main_calls=source_calls=reset_calls=reset_notifications=post_calls=0;
 shadow_read_race=fail_record=formatter_race=during_core=0;thread_id=22;
 AfCpCapture406Ports cp={0,read_memory,capture_thread,shadow};
 assert(!af_cp_capture406_init(&capture,&cp,records,sizeof records));
 AfCpComponents406Ports p={.view=snapshot,.current=current,.read=read_memory,.matrix=matrix,.cc1=cc1,
  .gamma=native_gamma,.gamma_record=private_gamma,.address=address,.worker=worker,
  .gamma_source=source_build,.gamma_reset=source_reset,.copy=original_copy};
 assert(!af_cp_components406_init(&component,&p));
 asset.native_mode=1;asset.native_tone[0]=128;view.asset=&asset;view.lease.asset=&asset;
 view.input.version=view.lease.version=7;view.input.source=AF_CP_INPUT406_COPY_A;view.input.epoch=18;
 view.input.origin_snapshot_epoch=12;view.input.slot=7;view.ticket=37;view.prefix=prefix;
 memset(main_params,0,sizeof main_params);main_params[0x38]=6;
 for(unsigned i=0;i<129;++i)put(record+4*i,i*1000);
 memset(record+0x204,0x5a,0x1c);put(record+0x220,128000);
 publish();
 uint8_t normalized[47];assert(!af_cp_capture_fields406_shadow(shadow_image,normalized));
 for(unsigned i=0;i<47;++i)d[offsets[i]]=normalized[i];
 for(unsigned i=0;i<2;++i){f[i][0x38]=6;f[i][0x3a]=f[i][0x3b]=18;}
}
static void stamp(void){
 AfCpCapture406Token t;AfCpCapture406Reverse r;
 assert(!af_cp_capture406_birth(&capture,object));
 assert(!af_cp_capture406_write_begin(&capture,object,AF_CP_CAPTURE406_NORMAL,&t));
 assert(!af_cp_capture406_reverse_begin(&capture,object+AF_CP_CAPTURE406_D,&r));
 assert(!af_cp_capture406_reverse_end(&capture,object+AF_CP_CAPTURE406_D,&r));
 assert(!af_cp_capture406_write_end(&capture,&t,AF_CP_CAPTURE406_NORMAL));
}
static void construct(void){
 AfCpCapture406Token format;
 assert(!af_cp_capture406_format_begin(&capture,object+AF_CP_CAPTURE406_D,faddr(channel),&format));
 /* 显式原构造端口返回；原算法本身另有静态证据，不在这里执行目标。 */
 assert(!af_cp_capture406_format_end(&capture,object+AF_CP_CAPTURE406_D,faddr(channel),&format));
}
static uint32_t outer(uint32_t formatter,unsigned output_index){
 uint32_t result=af_cp_components406_gamma(&component,1,f[channel],formatter,output[output_index]);
 /* 原413DF0后处理调用位置的宿主端口；产品core返回之后不能反写覆盖它。 */
 ++post_calls;put(output[output_index]+0x450,0x1234abcd);return result;
}
static void snapshots(void){
 setup();AfCpGamma406Tone tone,old;uint8_t image[84],before[84];
 assert(!af_cp_components406_gamma_snapshot(&component,&tone,image));
 assert(tone.version==7&&tone.tone[0]==128&&!memcmp(image,shadow_image,84));
 asset.native_tone[0]=256;view.input.version=view.lease.version=9;
 assert(!af_cp_components406_gamma_snapshot(&component,&tone,image)&&tone.version==7&&tone.tone[0]==128);
 memset(&tone,0xa5,sizeof tone);old=tone;memset(image,0xa5,84);memcpy(before,image,84);
 shadow_image[19]^=1;assert(af_cp_components406_gamma_snapshot(&component,&tone,image)==AF_STALE);
 assert(!memcmp(&tone,&old,sizeof tone)&&!memcmp(image,before,84));shadow_image[19]^=1;
 component.gamma_handoff.shadow_busy=1;assert(af_cp_components406_gamma_snapshot(&component,&tone,image)==AF_EMPTY);
 component.gamma_handoff.shadow_busy=0;component.gamma_handoff.guard=1;
 assert(af_cp_components406_gamma_snapshot(&component,&tone,image)==AF_BUSY);component.gamma_handoff.guard=0;
 shadow_read_race=1;assert(af_cp_components406_gamma_snapshot(&component,&tone,image)==AF_STALE);
 assert(!memcmp(&tone,&old,sizeof tone)&&!memcmp(image,before,84)&&reset_calls==1&&reset_notifications==1);
}
static void success(unsigned chosen){
 channel=chosen;
 for(unsigned branch=0;branch<2;++branch){
  setup();g[0]=(uint8_t)channel;g[1]=(uint8_t)branch;stamp();
  /* 新的全局LUT已发布，旧Capture仍使用其自有按值tone/version。 */
  asset.native_tone[0]=256;view.input.version=view.lease.version=9;view.ticket=38;publish();
  AfCpCapture406Token scope;assert(!af_cp_capture406_scope_begin(&capture,object+AF_CP_CAPTURE406_G,&scope));construct();
  AfCpGamma406Tone saved;AfCpCapture406Token got;uint8_t image[0x4e];
  assert(!af_cp_capture406_scope_read(&capture,faddr(channel),oaddr(channel),&saved,&got,image));
  assert(saved.version==7&&saved.tone[0]==128);
  assert(outer(faddr(channel),channel)==104&&private_calls==1&&!native_calls&&post_calls==1);
  uint32_t expected[129];int16_t old_tone[3]={128,0,0};uint32_t seed[129];
  for(unsigned i=0;i<129;++i)seed[i]=word(record+4*i);
  assert(!af_joint_gamma(seed,old_tone,expected));
  assert(word(output[channel]+0x24c+256)==expected[64]&&expected[64]>seed[64]);
  assert(word(output[channel]+0x450)==0x1234abcd&&!component.gamma_busy);
  assert(!af_cp_capture406_scope_end(&capture,&scope));
 }
}
static void fallbacks(void){
 for(unsigned mode=0;mode<8;++mode){
  channel=0;setup();stamp();AfCpCapture406Token scope={0};
  if(mode){assert(!af_cp_capture406_scope_begin(&capture,object+AF_CP_CAPTURE406_G,&scope));if(mode!=1)construct();}
  uint32_t formatter=faddr(channel);unsigned selected=channel;
  if(mode==2)formatter=faddr(1);if(mode==3)selected=1;if(mode==4)thread_id=23;
  if(mode==5)fail_record=1;if(mode==6)component.gamma_busy=1;if(mode==7)put(f[0]+0x30,51);
  assert(outer(formatter,selected)==103&&native_calls==1&&!private_calls&&post_calls==1);
  assert(!memcmp(output[selected]+0x24c,record,516)&&word(output[selected]+0x450)==0x1234abcd);
  assert(component.gamma_busy==(mode==6?1u:0u));component.gamma_busy=0;thread_id=22;
  if(scope.serial)assert(!af_cp_capture406_scope_end(&capture,&scope));
 }
}
static void races(void){
 for(unsigned mode=0;mode<3;++mode){
  channel=0;setup();stamp();AfCpCapture406Token scope;
  assert(!af_cp_capture406_scope_begin(&capture,object+AF_CP_CAPTURE406_G,&scope));construct();
  if(mode==0)formatter_race=1;else during_core=mode;
  assert(outer(faddr(0),0)==103&&private_calls==1&&native_calls==1&&post_calls==1);
  assert(!memcmp(output[0]+0x24c,record,516)&&!component.gamma_busy);
  assert(word(output[0]+0x450)==0x1234abcd);
  int result=af_cp_capture406_scope_end(&capture,&scope);
  assert(mode==0?result==AF_OK:result==AF_IO);
  if(mode==1)assert(reset_notifications==1&&reset_calls==1);
 }
}
int main(int argc,char **argv){assert(argc>=2);
 if(!strcmp(argv[1],"snapshot"))snapshots();
 else if(!strcmp(argv[1],"success")){assert(argc==3);success((unsigned)atoi(argv[2]));}
 else if(!strcmp(argv[1],"fallback"))fallbacks();else races();return 0;
}
'''


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    folder = tmp_path_factory.mktemp('capture-components406')
    source, result = folder/'driver.c', folder/'driver'
    source.write_text(DRIVER)
    names = ('af_cp_components406.c','af_cp_capture406.c','af_cp_capture_fields406.c',
             'af_joint.c','af_color406.c','af_slots.c')
    command = ['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_CP_CAPTURE406=1',
               '-I'+str(NATIVE),str(source),*[str(NATIVE/name) for name in names],'-o',str(result)]
    run = subprocess.run(command,capture_output=True,text=True)
    assert run.returncode == 0, run.stderr
    return result


def run(binary,*arguments):
    result = subprocess.run([str(binary),*arguments],capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr


def test_actual_shadow_snapshot_requires_the_published_image_and_epoch(binary):
    run(binary,'snapshot')


@pytest.mark.parametrize('channel',[0,1])
def test_capture_tone_uses_original_core_and_returns_to_outer_postprocessing(binary,channel):
    run(binary,'success',str(channel))


def test_missing_constructor_wrong_domain_and_busy_keep_stock_result(binary):
    run(binary,'fallback')


def test_scope_reset_formatter_change_and_reentry_recompute_stock(binary):
    run(binary,'race')
