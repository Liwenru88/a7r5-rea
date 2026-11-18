"""原登记委派次数、post-original计数、陈旧与重入；仅宿主C，无目标模拟。"""
from pathlib import Path
import subprocess
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=Path(__file__).resolve().parents[1]/'native'
def test_original_once_post_receipt_and_refusal_preserve_native(tmp_path):
    source=tmp_path/'main.c';source.write_text(r'''
#include "af_ap_lifecycle.h"
#include <assert.h>
#include <string.h>
static uintptr_t tree[6];static AfApLifecycle state;static unsigned count,reenter;static int wrong_count;
static uintptr_t seen[3];
static void original(void *r,const void *b,const void *e){
 count++;seen[0]=(uintptr_t)r;seen[1]=(uintptr_t)b;seen[2]=(uintptr_t)e;
 if(reenter){reenter=0;af_ap_lifecycle_dispatch(&state,original,r,b,e);}
 if(r==tree)tree[5]=wrong_count?5590:5591;
}
static void reset(void){memset(&state,0,sizeof state);memset(tree,0,sizeof tree);count=0;wrong_count=0;reenter=0;}
int main(void){
 const uintptr_t base=0x7000000000ull;void *b=(void *)(base+0x5030590),*e=(void *)(base+0x5046300);
 AfApRegistration out,before;memset(&out,0xa5,sizeof out);before=out;
 reset();assert(af_ap_lifecycle_arm(&state,0,tree)==AF_INVALID && !state.phase);
 assert(af_ap_lifecycle_arm(&state,base,tree)==AF_OK);
 assert(af_ap_lifecycle_take(&state,&out)==AF_STALE && !memcmp(&out,&before,sizeof out));
 af_ap_lifecycle_dispatch(&state,original,tree,b,e);
 assert(count==1 && seen[0]==(uintptr_t)tree && seen[1]==(uintptr_t)b && seen[2]==(uintptr_t)e);
 assert(state.phase==AF_AP_LIFE_RECORDED && af_ap_lifecycle_take(&state,&out)==AF_OK);
 assert(out.registry==(uintptr_t)tree && out.rows==5591 && out.serial==1 && out.constructor_index==104);
 before=out;assert(af_ap_lifecycle_take(&state,&out)==AF_STALE && !memcmp(&out,&before,sizeof out));
 for(unsigned variant=0;variant<4;variant++){
  reset();assert(af_ap_lifecycle_arm(&state,base,tree)==AF_OK);
  wrong_count=variant==0;reenter=variant==1;
  af_ap_lifecycle_dispatch(&state,original,tree,variant==2?(void *)0x1234:b,e);
  if(variant==3)af_ap_lifecycle_dispatch(&state,original,tree,b,e);
  assert(count==((variant==1 || variant==3)?2u:1u));
  before=out;assert(af_ap_lifecycle_take(&state,&out)==AF_STALE && !memcmp(&out,&before,sizeof out));
 }
 reset();assert(af_ap_lifecycle_arm(&state,base,tree)==AF_OK);
 af_ap_lifecycle_dispatch(&state,original,tree,b,e);tree[5]++;
 before=out;assert(af_ap_lifecycle_take(&state,&out)==AF_STALE && !memcmp(&out,&before,sizeof out));
 count=0;af_ap_lifecycle_dispatch(0,original,tree,b,e);assert(count==1);
 return 0;
}
''')
    target=tmp_path/'contract'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),
        '-I'+str(ROOT/'a7r5-firmware-features/custom-filters/native'),str(NATIVE/'af_ap_lifecycle.c'),str(source),'-o',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    result=subprocess.run([str(target)],capture_output=True,text=True);assert result.returncode==0,result.stderr

def test_instruction_failure_restores_original_or_reports_nx_without_false_success(tmp_path):
    source=tmp_path/'main.c';source.write_text(r'''
#include "af_ap_lifecycle.h"
#include <assert.h>
static uint32_t opcode;static unsigned step,flushes,mode;
static int protect(void *page,int flags){
 (void)page;step++;assert(flags==(step==1?3:5));
 if(mode==1)return step==1?-1:0;
 if(mode==2)return step==2?-1:0;
 if(mode==3)return step>=2?-1:0;
 return 0;
}
static void flush(void *at,size_t n){assert(at==&opcode && n==4);flushes++;}
int main(void){
 for(mode=0;mode<4;mode++){
  opcode=0x94166e21u;step=flushes=0;
  int r=af_ap_lifecycle_write(&opcode,0x94166e21u,0x94000001u,protect,flush);
  if(mode==0)assert(r==AF_OK && opcode==0x94000001u && step==2 && flushes==1);
  if(mode==1)assert(r==AF_IO && opcode==0x94166e21u && step==1 && !flushes);
  if(mode==2)assert(r==AF_IO && opcode==0x94166e21u && step==3 && flushes==2);
  if(mode==3)assert(r==AF_AP_LIFE_UNSAFE_PERMISSIONS && opcode==0x94166e21u && step==3 && flushes==2);
 }
 step=0;opcode=123;assert(af_ap_lifecycle_write(&opcode,1,2,protect,flush)==AF_STALE && !step);
 return 0;
}
''')
    target=tmp_path/'contract'
    r=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),
        '-I'+str(ROOT/'a7r5-firmware-features/custom-filters/native'),str(NATIVE/'af_ap_lifecycle.c'),str(source),'-o',str(target)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    r=subprocess.run([str(target)],capture_output=True,text=True);assert r.returncode==0,r.stderr
