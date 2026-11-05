"""原UI与真实CP覆盖叶联验：不能把factory发送接受误作pending结束。"""
from pathlib import Path
import subprocess
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents
          if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'

@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    d=tmp_path_factory.mktemp('factory-pending');source=d/'pending.c';out=d/'pending'
    body=(NATIVE/'af_ap_ui.c').read_text()
    resolver='static Word ap_address(Word offset) { return ap_base + offset; }'
    assert body.count(resolver)==1
    body=body.replace(resolver,'static Word address_for_test(Word);\nstatic Word ap_address(Word offset) {return address_for_test(offset);}')
    source.write_text(body+r'''
#include "af_cp_override406.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static AfCpOverride406 cp_private;
static unsigned char native_state[AF_CP406_STATE_BYTES],marker;
static uint32_t shown=AF_UI_NEW_FIRST,native_selected,mode;
static AfPreset working[19];
static unsigned sent,released;
static uint32_t ordinary(void){return 0;}
static const uint32_t *current(void){return &shown;}
static const uint32_t *current_native(void){return &native_selected;}
static const uint32_t *photo_mode(void){return &mode;}
static uint32_t unused_native(void *object){(void)object;assert(0);return 0;}
static Word address_for_test(Word off){
 if(off==0x28a87e8)return (Word)current;if(off==0x28ae4b0)return (Word)current_native;
 if(off==0x17ffd84)return (Word)ordinary;if(off==0x28bfdcc)return (Word)photo_mode;
 if(off==0x1af11f0||off==0x220929c)return (Word)unused_native;
 assert(0);return 0;
}
void af_stock_select(uint32_t selector){native_selected=selector;}
void af_stock_preview(void *context,uint32_t selector){(void)context;af_stock_select(selector);}
void af_stock_preview_menu(uint32_t menu){(void)menu;}
Word af_stock_inhibited(void *object){(void)object;return 1;}
static uint32_t capabilities(void *context){assert(context==&sent);return 0x31fff;}
static int send_request(void *context,uint32_t slot,const AfPreset *preset){
 assert(context==&sent);++sent;
 return af_cp_override406_publish_locked(&cp_private,cp_private.version+1,slot,preset,&marker);
}
static int factory(void *context,uint32_t selector,AfPreset *out){
 assert(context==&sent&&selector<19);*out=working[selector];return AF_OK;
}
static int release_request(void *context){
 assert(context==&sent);++released;return af_cp_override406_release_locked(&cp_private,cp_private.version+1,&marker);
}
static void edit_factory(void *object,uint32_t direction){
 (void)object;(void)direction;assert(native_selected==17);++working[17].params[0];
 assert(af_cp406_write_state(&working[17],native_state,sizeof native_state,&marker)==AF_OK);
}
void af_stock_step_0(void *object,uint32_t direction){edit_factory(object,direction);}
void af_stock_base_cycle(void *object,uint32_t direction){edit_factory(object,direction);}
void af_stock_reset(void *transaction){edit_factory(transaction,0);}
Word af_stock_direct(void *object,const void *event){
 if(get32((const uint8_t *)event+0xc)==0xd)edit_factory(object,0);
 return 0x55a7;
}
int main(int argc,char **argv){
 assert(argc==2);prepared=enabled=1;af_catalog_init(&af_ap_catalog);
 AfPreset user={0};user.params[6]=3;assert(af_install(&af_ap_catalog,7,&user,0)==AF_OK);
 working[17]=(AfPreset){.base=17,.params={-3,4,-5,2,6,7,4,8}};
 working[18]=working[17];working[18].base=18;
 AfApImagingBinding b={AF_AP_IMAGING_VERSION,sizeof b,&sent,capabilities,send_request,factory,release_request};
 assert(af_ap_imaging_bind(&b)==AF_OK);
 shown=AF_UI_NEW_FIRST;af_ap_select(19);assert(cp_private.mode==AF_CP_OVERRIDE_USER);
 shown=0x852;af_ap_select(17);assert(cp_private.mode==AF_CP_OVERRIDE_FACTORY_PENDING);
 /* 故意延迟第一次原CP拍摄snapshot，随后发生另一条合法原厂事件。 */
 unsigned expected_wire;int expected_contrast;
 if(!strcmp(argv[1],"switch")){
   shown=0x853;af_ap_select(18);
   assert(af_cp406_write_state(&working[18],native_state,sizeof native_state,&marker)==AF_OK);
   expected_wire=20;expected_contrast=-3;
 }else{
   layout_allowed=1;display_menu=shown;expected_wire=19;expected_contrast=-2;
   if(!strcmp(argv[1],"step"))af_ap_step_0(0,0);
   else if(!strcmp(argv[1],"reset"))af_ap_reset(0);
   else if(!strcmp(argv[1],"base"))af_ap_base_cycle(0,0);
   else{
     unsigned char event[0x40]={0};
     if(!strcmp(argv[1],"direct"))put32(event+0xc,0xd);
     else{assert(!strcmp(argv[1],"direct_other"));put32(event+0xc,0xc);expected_contrast=-3;}
     assert(af_ap_direct(0,event)==0x55a7);
     if(!strcmp(argv[1],"direct_other"))assert(sent==2&&!released&&cp_private.mode==AF_CP_OVERRIDE_FACTORY_PENDING);
   }
 }
 unsigned char output[sizeof native_state];memcpy(output,native_state,sizeof output);
 assert(af_cp_override406_snapshot_locked(&cp_private,native_state,output,sizeof output)==AF_OK);
 printf("scenario=%s native=%u/%d copied=%u/%d private_mode=%u sends=%u releases=%u\n",
   argv[1],native_state[0xa40],(int8_t)native_state[0xa44],output[0xa40],(int8_t)output[0xa44],cp_private.mode,sent,released);
 return output[0xa40]==expected_wire&&(int8_t)output[0xa44]==expected_contrast?0:1;
}
''')
    cmd=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffunction-sections','-fdata-sections',
         '-Wl,-dead_strip','-I'+str(NATIVE),str(source),
         *[str(NATIVE/p) for p in ('af_slots.c','af_ui.c','af_cp406_state.c','af_cp_override406.c')],'-o',str(out)]
    r=subprocess.run(cmd,capture_output=True,text=True);assert r.returncode==0,r.stderr
    return out

@pytest.mark.parametrize('scenario',['switch','step','direct','direct_other','reset','base'])
def test_factory_pending_updates_or_releases_after_native_event(binary,scenario):
    r=subprocess.run([str(binary),scenario],capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
