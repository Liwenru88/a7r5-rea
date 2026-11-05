"""原Capture伴随状态的宿主失败回归；不执行目标指令、硬件或设备。"""
from pathlib import Path
import subprocess

import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'
DRIVER=r'''
#include "af_cp_capture406.h"
#include "af_cp_capture_fields406.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static AfCpCapture406 state;
static AfCpCapture406Record records[AF_CP_CAPTURE406_COUNT];
static uint8_t shadow_image[84],d[0x3a],e[9],g[8],f[0x4e];
static AfCpGamma406Tone shadow_tone;
static uint32_t thread_id=22,object=0x71000000;
static unsigned fail_read,fail_shadow,race,thread_fail;
static const uint8_t offsets[47]={0,4,5,6,7,8,9,10,11,12,13,14,16,17,18,19,20,21,22,
 24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,48,49,50,51,52,53,54,55,56,57};
static void put(void *p,uint32_t x){uint8_t *b=p;for(unsigned i=0;i<4;++i)b[i]=(uint8_t)(x>>(i*8));}
static int original_thread(void *context,uint32_t *out){assert(context==&state&&!state.guard);if(thread_fail)return AF_IO;*out=thread_id;return AF_OK;}
static int original_shadow(void *context,AfCpGamma406Tone *tone,uint8_t image[84]){
 assert(context==&state&&!state.guard);if(fail_shadow)return AF_EMPTY;
 *tone=shadow_tone;memcpy(image,shadow_image,84);return AF_OK;
}
static int original_read(void *context,uint32_t at,void *out,size_t n){
 assert(context==&state&&!state.guard);if(fail_read)return AF_IO;
 if(at==object+AF_CP_CAPTURE406_D&&n==sizeof d){
  memcpy(out,d,n);
  if(race){unsigned event=race;race=0;
   if(event==1){AfCpCapture406Token token;assert(!af_cp_capture406_write_begin(&state,object,AF_CP_CAPTURE406_RESTORE,&token));}
   else if(event==2)assert(!af_cp_capture406_release(&state,object));
   else (void)af_cp_capture406_reset(&state);
  }
  return AF_OK;
 }
 if(at==object+AF_CP_CAPTURE406_G&&n<=sizeof g){memcpy(out,g,n);return AF_OK;}
 if(at==object+AF_CP_CAPTURE406_G+0xb4&&n==sizeof e){memcpy(out,e,n);return AF_OK;}
 if((at==0x1f6dfdc||at==0x1f6e390)&&n==sizeof f){memcpy(out,f,n);return AF_OK;}
 if(n==4&&(at==0xdcc4e0||at==0x18d1c24||at==0x19864fc)){memset(out,0,n);return AF_OK;}
 if(n==1&&(at==0x18d1c25||at==0x18d1c35||at==0x18d1c34||at==0x19d1308)){*(uint8_t *)out=0;return AF_OK;}
 if(n==4&&((at>=0xdcc514&&at<0xdcc714)||(at>=0x107eefc&&at<0x107ef8c))){memset(out,0,n);return AF_OK;}
 return AF_IO;
}
static void setup(void){
 AfCpCapture406Ports ports={&state,original_read,original_thread,original_shadow};
 assert(af_cp_capture406_records_bytes()==sizeof records);
 assert(!af_cp_capture406_init(&state,&ports,records,sizeof records));
 assert(af_cp_capture406_ready(&state));
 shadow_tone=(AfCpGamma406Tone){.version=9,.input_source=0x1653c68,.input_epoch=18,
  .snapshot_epoch=12,.slot=7,.ticket=37,.source_epoch=20,.tone={128,-32,0}};
 shadow_image[0]=1;shadow_image[8]=1;shadow_image[11]=1;put(shadow_image+0x30,6);
 uint8_t fields[47];assert(!af_cp_capture_fields406_shadow(shadow_image,fields));
 memset(d,0xa5,sizeof d);for(unsigned i=0;i<47;++i)d[offsets[i]]=fields[i];
 d[0x2a]=0;put(d+0x2c,0);memset(e,0,sizeof e);e[0]=1;g[1]=1;
 memset(f,0,sizeof f);f[4]=1;f[7]=1;put(f+0x2c,6);f[0x38]=6;f[0x39]=1;f[0x3a]=f[0x3b]=18;f[0x46]=1;
 assert(!af_cp_capture_fields406_formatter(d,e,f,original_read,&state));
}
static void stamp(unsigned version){
 shadow_tone.version=version;
 AfCpCapture406Token write;AfCpCapture406Reverse reverse;
 assert(!af_cp_capture406_write_begin(&state,object,AF_CP_CAPTURE406_NORMAL,&write));
 assert(!af_cp_capture406_reverse_begin(&state,object+AF_CP_CAPTURE406_D,&reverse));
 assert(!af_cp_capture406_reverse_end(&state,object+AF_CP_CAPTURE406_D,&reverse));
 assert(!af_cp_capture406_write_end(&state,&write,AF_CP_CAPTURE406_NORMAL));
}
static int scope_read(unsigned channel,AfCpCapture406Token *token,AfCpGamma406Tone *tone){
 AfCpCapture406Token format;uint32_t fptr=channel?0x1f6e390:0x1f6dfdc;
 int status=af_cp_capture406_format_begin(&state,object+AF_CP_CAPTURE406_D,fptr,&format);
 if(status)return status;status=af_cp_capture406_format_end(&state,object+AF_CP_CAPTURE406_D,fptr,&format);
 if(status)return status;uint8_t image[0x4e];return af_cp_capture406_scope_read(&state,channel?0x1f6e390:0x1f6dfdc,
  channel?0x1f709f4:0x1f6ff74,tone,token,image);
}
static void success(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);
 /* shadow随后换代不改变已完成的B快照，不读取全局最新tone。 */
 shadow_tone.version=10;shadow_image[8]=0;
 for(unsigned channel=0;channel<2;++channel){
  AfCpCapture406Token scope,read;AfCpGamma406Tone tone;
  g[0]=(uint8_t)channel;thread_id=33+channel;
  assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope)&&scope.serial);
  g[1]=0; /* 原内部可以清enable，来源资格仍由开始时建立。 */
  assert(!scope_read(channel,&read,&tone)&&tone.version==9&&tone.tone[0]==128);
  assert(!memcmp(&read,&scope,sizeof read)&&!af_cp_capture406_scope_current(&state,&read));
  assert(!af_cp_capture406_scope_end(&state,&scope));g[1]=1;
 }
 assert(!af_cp_capture406_release(&state,object));
 assert(af_cp_capture406_release(&state,object)==AF_EMPTY);
 assert(!af_cp_capture406_birth(&state,object));
 AfCpCapture406Token scope;assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope)==AF_EMPTY&&scope.serial);
 assert(!af_cp_capture406_scope_end(&state,&scope));
}
static void invalidations(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);
 AfCpCapture406Token restore,scope;AfCpCapture406Reverse reverse;
 assert(!af_cp_capture406_write_begin(&state,object,AF_CP_CAPTURE406_RESTORE,&restore));
 assert(af_cp_capture406_reverse_begin(&state,object+AF_CP_CAPTURE406_D,&reverse)==AF_EMPTY);
 assert(af_cp_capture406_write_end(&state,&restore,AF_CP_CAPTURE406_RESTORE)==AF_EMPTY);
 assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope)==AF_EMPTY&&scope.serial);
 assert(!af_cp_capture406_scope_end(&state,&scope));stamp(10);
 assert(!af_cp_capture406_reset(&state));
 assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope)==AF_EMPTY);assert(!af_cp_capture406_scope_end(&state,&scope));
 stamp(11);assert(!af_cp_capture406_pool_begin(&state));assert(!af_cp_capture406_ready(&state));
 assert(af_cp_capture406_birth(&state,object)==AF_BUSY);assert(!af_cp_capture406_pool_end(&state));
 assert(!af_cp_capture406_birth(&state,object));
 assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope)==AF_EMPTY);assert(!af_cp_capture406_scope_end(&state,&scope));
 assert(af_cp_capture406_write_end(&state,&restore,AF_CP_CAPTURE406_RESTORE)==AF_STALE);
}
static void rejection(void){
 assert(!af_cp_capture406_birth(&state,object));
 AfCpCapture406Token write,scope,read;AfCpCapture406Reverse reverse;AfCpGamma406Tone tone;
 assert(!af_cp_capture406_write_begin(&state,object,AF_CP_CAPTURE406_NORMAL,&write));
 assert(!af_cp_capture406_reverse_begin(&state,object+AF_CP_CAPTURE406_D,&reverse));
 shadow_tone.version++;
 assert(af_cp_capture406_reverse_end(&state,object+AF_CP_CAPTURE406_D,&reverse)==AF_STALE);
 assert(af_cp_capture406_write_end(&state,&write,AF_CP_CAPTURE406_NORMAL)==AF_EMPTY);
 stamp(11);assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope));
 memset(&tone,0xa5,sizeof tone);AfCpGamma406Tone before=tone;memset(&read,0xa5,sizeof read);AfCpCapture406Token saved=read;
 uint8_t snapshot[0x4e];assert(af_cp_capture406_scope_read(&state,0x1f6dfdc,0x1f709f4,&tone,&read,snapshot)<0&&!memcmp(&before,&tone,sizeof tone)&&!memcmp(&saved,&read,sizeof read));
 thread_id++;assert(af_cp_capture406_scope_current(&state,&scope)<0);thread_id--;
 assert(!af_cp_capture406_scope_end(&state,&scope));
 assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope));
 d[8]^=1;assert(af_cp_capture406_scope_current(&state,&scope)==AF_STALE);d[8]^=1;
 assert(!af_cp_capture406_scope_end(&state,&scope));
}
static void diagnostic(void){
 assert(!af_cp_capture406_birth(&state,object));AfCpCapture406Token write;AfCpCapture406Reverse reverse;
 assert(!af_cp_capture406_write_begin(&state,object,AF_CP_CAPTURE406_NORMAL,&write));
 assert(!af_cp_capture406_reverse_begin(&state,object+AF_CP_CAPTURE406_D,&reverse));
 for(unsigned i=0;i<47;++i)d[offsets[i]]=offsets[i]==0?shadow_image[0]:offsets[i]==48?1:offsets[i]==52?3:0;
 assert(af_cp_capture406_reverse_end(&state,object+AF_CP_CAPTURE406_D,&reverse)==AF_EMPTY);
 assert(af_cp_capture406_write_end(&state,&write,AF_CP_CAPTURE406_NORMAL)==AF_EMPTY);
}
static void contention(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);AfCpCapture406Token first,second;
 assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&first));
 assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&second)==AF_BUSY);
 assert(!af_cp_capture406_ready(&state)&&af_cp_capture406_scope_current(&state,&first)==AF_IO);
 (void)af_cp_capture406_scope_end(&state,&first);
}
static void capacity(void){
 for(unsigned i=0;i<490;++i)assert(!af_cp_capture406_birth(&state,object+i*0x1000));
 assert(af_cp_capture406_birth(&state,object+490*0x1000)==AF_EXHAUSTED);
 uint64_t old=records[0].birth;assert(!af_cp_capture406_release(&state,object));
 assert(!af_cp_capture406_birth(&state,object)&&records[0].birth!=old);
 state.next_birth=UINT64_MAX;
 assert(!af_cp_capture406_release(&state,object));assert(af_cp_capture406_birth(&state,object)==AF_EXHAUSTED);
 assert(!af_cp_capture406_ready(&state));
}
static void race_read(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);AfCpCapture406Token scope,read;AfCpGamma406Tone tone;
 assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope));
 race=3;assert(scope_read(0,&read,&tone)<0&&!af_cp_capture406_ready(&state));
 (void)af_cp_capture406_scope_end(&state,&scope);
}

static void event_gate(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);g[1]=0;
 AfCpCapture406Token active,read,format;AfCpGamma406Tone tone;uint8_t image[0x4e];
 assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&active));
 assert(af_cp_capture406_scope_read(&state,0x1f6dfdc,0x1f6ff74,&tone,&read,image)==AF_EMPTY);
 assert(af_cp_capture406_format_begin(&state,object+AF_CP_CAPTURE406_D,0x1f6e390,&format)==AF_EMPTY);
 assert(!af_cp_capture406_format_begin(&state,object+AF_CP_CAPTURE406_D,0x1f6dfdc,&format));
 assert(af_cp_capture406_scope_read(&state,0x1f6dfdc,0x1f6ff74,&tone,&read,image)==AF_EMPTY);
 assert(!af_cp_capture406_format_end(&state,object+AF_CP_CAPTURE406_D,0x1f6dfdc,&format));
 assert(!af_cp_capture406_scope_read(&state,0x1f6dfdc,0x1f6ff74,&tone,&read,image));
 assert(!af_cp_capture406_scope_end(&state,&active));
 g[3]=1;put(g+4,1);
 assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&active)==AF_EMPTY&&active.serial);
 assert(!af_cp_capture406_scope_end(&state,&active));
 g[3]=0;g[0]=2;
 assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&active)==AF_EMPTY&&active.serial);
 assert(!af_cp_capture406_scope_end(&state,&active));
}
static void callback_failure(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);
 thread_fail=1;AfCpCapture406Token write,active;AfCpCapture406Reverse reverse;
 assert(af_cp_capture406_write_begin(&state,object,1,&write)==AF_IO);thread_fail=0;
 assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&active)==AF_EMPTY);
 assert(!af_cp_capture406_scope_end(&state,&active));
 assert(!af_cp_capture406_write_begin(&state,object,1,&write));fail_shadow=1;
 assert(af_cp_capture406_reverse_begin(&state,object+AF_CP_CAPTURE406_D,&reverse)==AF_EMPTY);
 fail_shadow=0;assert(af_cp_capture406_write_end(&state,&write,1)==AF_EMPTY);
 stamp(10);fail_read=1;assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&active)==AF_IO&&active.serial);
 fail_read=0;assert(!af_cp_capture406_scope_end(&state,&active));
 assert(af_cp_capture406_ready(&state));
}
static void foreign_format(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);AfCpCapture406Token active,format;
 assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&active));
 thread_id++;assert(af_cp_capture406_format_begin(&state,object+AF_CP_CAPTURE406_D,0x1f6dfdc,&format)==AF_BUSY);
 assert(!af_cp_capture406_ready(&state));thread_id--;assert(af_cp_capture406_scope_end(&state,&active)==AF_IO);
}
static void nested_format(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);AfCpCapture406Token active,format,next;
 assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&active));
 assert(!af_cp_capture406_format_begin(&state,object+AF_CP_CAPTURE406_D,0x1f6dfdc,&format));
 assert(af_cp_capture406_format_begin(&state,object+AF_CP_CAPTURE406_D,0x1f6dfdc,&next)==AF_BUSY);
 assert(!af_cp_capture406_ready(&state));
}
static void guard_contention(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);state.guard=1;
 assert(af_cp_capture406_release(&state,object)==AF_BUSY);state.guard=0;
 assert(!af_cp_capture406_ready(&state));
}
static void in_flight_write(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);AfCpCapture406Token write,nested;
 assert(!af_cp_capture406_write_begin(&state,object,1,&write));
 assert(af_cp_capture406_write_begin(&state,object,2,&nested)==AF_BUSY);
 assert(!af_cp_capture406_ready(&state));assert(af_cp_capture406_write_end(&state,&write,1)<0);
}
static void duplicate_birth(void){
 assert(!af_cp_capture406_birth(&state,object));stamp(9);
 assert(af_cp_capture406_birth(&state,object)==AF_STALE&&!af_cp_capture406_ready(&state));
}
static void unqualified_stock_then_private(void){
 /* 绑定前出生的未知A、以及已跟踪但未取得私有Bstamp的原厂A均应可正常构造。 */
 for(unsigned tracked=0;tracked<2;++tracked){
  if(tracked)assert(!af_cp_capture406_birth(&state,object));
  for(unsigned channel=0;channel<2;++channel){
   AfCpCapture406Token scope,format;g[0]=(uint8_t)channel;
   assert(af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope)==AF_EMPTY&&scope.serial);
   assert(af_cp_capture406_format_begin(&state,object+AF_CP_CAPTURE406_D,
      channel?0x1f6e390:0x1f6dfdc,&format)==AF_EMPTY&&!format.serial);
   assert(af_cp_capture406_ready(&state)&&!state.fault);
   assert(!af_cp_capture406_scope_end(&state,&scope));
  }
 }
 /* 原厂调用不能污染后续真实出生/来源登记，两份F/O均仍可取得按值资格。 */
 assert(!af_cp_capture406_release(&state,object));
 assert(!af_cp_capture406_birth(&state,object));stamp(12);
 for(unsigned channel=0;channel<2;++channel){
  AfCpCapture406Token scope,read;AfCpGamma406Tone tone;g[0]=(uint8_t)channel;
  assert(!af_cp_capture406_scope_begin(&state,object+AF_CP_CAPTURE406_G,&scope));
  assert(!scope_read(channel,&read,&tone)&&tone.version==12);
  assert(!af_cp_capture406_scope_end(&state,&scope));
 }
}

int main(int argc,char **argv){assert(argc==2);setup();
 if(!strcmp(argv[1],"success"))success();else if(!strcmp(argv[1],"invalidations"))invalidations();
 else if(!strcmp(argv[1],"rejection"))rejection();else if(!strcmp(argv[1],"diagnostic"))diagnostic();
 else if(!strcmp(argv[1],"contention"))contention();else if(!strcmp(argv[1],"capacity"))capacity();
 else if(!strcmp(argv[1],"event"))event_gate();else if(!strcmp(argv[1],"callback"))callback_failure();
 else if(!strcmp(argv[1],"foreign"))foreign_format();else if(!strcmp(argv[1],"nested"))nested_format();
 else if(!strcmp(argv[1],"guard"))guard_contention();else if(!strcmp(argv[1],"write"))in_flight_write();
 else if(!strcmp(argv[1],"duplicate"))duplicate_birth();
 else if(!strcmp(argv[1],"unqualified"))unqualified_stock_then_private();else race_read();
 return 0;
}
'''


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    directory=tmp_path_factory.mktemp('cp-capture406');source=directory/'capture.c';target=directory/'capture'
    source.write_text(DRIVER)
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),
             str(NATIVE/'af_cp_capture406.c'),str(NATIVE/'af_cp_capture_fields406.c'),'-o',str(target)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return target


@pytest.mark.parametrize('scenario',['success','invalidations','rejection','diagnostic','contention','capacity','race','event','callback','foreign','nested','guard','write','duplicate','unqualified'])
def test_capture_native_lifetime_and_second_domain_qualification(binary,scenario):
    result=subprocess.run([str(binary),scenario],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
