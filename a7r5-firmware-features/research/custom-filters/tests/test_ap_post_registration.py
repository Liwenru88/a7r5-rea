"""编译实际UI C的post接口：原range不重放、只追加14行、不发布列表。"""
from pathlib import Path
import re
import subprocess
import sys
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
OWN=Path(__file__).resolve().parents[1]/'native';NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'

def test_post_adds_only_private_range_and_never_replays_or_enables(tmp_path):
    text=(OWN/'af_ap_ui.c').read_text().split('static const AfApCheck checks[] = {',1)[1].split('};',1)[0]
    checks=re.findall(r'\{(0x[0-9a-f]+),(0x[0-9a-f]+)\}',text);assert len(checks)==132
    init='\n'.join('*(uint32_t *)(base+'+a+')='+v+'u;'for a,v in checks)
    source=tmp_path/'main.c';source.write_text(r'''
#include "af_ap_ui.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
static uintptr_t base,tree[6];static unsigned calls,stock_calls,added;
extern uint8_t af_ap_rows[33][128];extern AfCatalog af_ap_catalog;
extern void af_ap_register(void *,const void *,const void *);
void af_stock_register(void *r,const void *b,const void *e){
 assert(r==tree);calls++;
 if((uintptr_t)b==base+0x5030590 && (uintptr_t)e==base+0x5046300){stock_calls++;if(tree[5]<5591)tree[5]=5591;return;}
 assert((const uintptr_t *)e-(const uintptr_t *)b==28);
 const uintptr_t *p=b;for(unsigned i=0;i<14;i++){
  assert(p[i*2]==0x15d9u+i && p[i*2+1]==(uintptr_t)af_ap_rows[18+i]);
 }added+=14;tree[5]+=14;
}
int main(void){
 void *memory=mmap(0,0x8e84000,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);assert(memory!=MAP_FAILED);
 base=(uintptr_t)memory;
 assert(af_ap_after_original_registration(0)==AF_INVALID);
''' + init + r'''
 *(uintptr_t *)(base+0x5858b08+0x58)=base+0x3f4a280;
 *(uint32_t *)(base+0x5858b08+0x54)=19;
 *(uintptr_t *)(base+0x5858b08+0x78)=base+0x1c05f18;
 *(uintptr_t *)(base+0x5915b80)=(uintptr_t)tree;
 for(unsigned i=0;i<19*128;i++)((uint8_t *)(base+0x3f4a280))[i]=(uint8_t)(i*17+5);
 AfApBinding binding={1,sizeof(binding),base,AF_AP_IMAGE_SPAN,base+0x17feac0,{0}};
 const uint8_t hash[32]={0xd1,0x59,0x33,0xce,0xb5,0xff,0x9a,0xd0,0xb4,0xf7,0x89,0xcb,0xab,0xd6,0xff,0x0a,0x51,0x52,0x64,0x72,0xdd,0x35,0xc9,0x0d,0xb9,0x71,0x96,0xdd,0x22,0x78,0x20,0xe9};memcpy(binding.ap_sha256,hash,32);
 assert(af_ap_bind(&binding)==AF_OK);
 AfApRegistration r={1,sizeof r,base,(uintptr_t)tree,base+0x5030590,base+0x5046300,5591,1,104,AF_AP_LIFE_RECORDED};
 tree[5]=5591;
 AfApRegistration bad=r;bad.serial=0;assert(af_ap_after_original_registration(&bad)==AF_INVALID && calls==0);
 tree[5]=5590;assert(af_ap_after_original_registration(&r)==AF_STALE && calls==0);tree[5]=5591;
 assert(af_ap_after_original_registration(&r)==AF_OK);
 assert(calls==1 && !stock_calls && added==14 && tree[5]==5605);
 assert(*(uint32_t *)(base+0x5858b08+0x54)==19);
 assert(*(uintptr_t *)(base+0x5858b08+0x58)==base+0x3f4a280);
 assert(*(uintptr_t *)(base+0x5858b08+0x78)==base+0x1c05f18);
 assert(af_ap_catalog.next_request==0 && af_ap_manager.next_ticket==1);
 assert(af_ap_after_original_registration(&r)==AF_BUSY && calls==1);
 af_ap_register(tree,(void *)(base+0x5030590),(void *)(base+0x5046300));
 assert(calls==2 && stock_calls==1 && added==14 && tree[5]==5605);
 assert(munmap(memory,0x8e84000)==0);return 0;
}
''')
    target=tmp_path/'contract';dead=['-Wl,-dead_strip'] if sys.platform=='darwin' else ['-Wl,--gc-sections']
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-DAF_AP_DYNAMIC','-ffunction-sections','-fdata-sections',*dead,
        '-I'+str(OWN),'-I'+str(NATIVE),str(OWN/'af_ap_ui.c'),str(NATIVE/'af_slots.c'),str(NATIVE/'af_ap_manage.c'),str(source),'-o',str(target)]
    r=subprocess.run(command,capture_output=True,text=True);assert r.returncode==0,r.stderr
    r=subprocess.run([str(target)],capture_output=True,text=True);assert r.returncode==0,r.stderr
