"""原D4覆盖确认的行为契约；只替换宿主无法执行的原AP模型服务。"""
from pathlib import Path
import shutil,subprocess
import pytest
NATIVE=Path(__file__).resolve().parents[1]/'native'
HARNESS=r'''
#include "af_ap_targets.c"
#include <assert.h>
#include <string.h>
static uint32_t shown,calls,language;
static AfCatalog catalog;
static AfApTargetChoice received;
static int callback_result;
static const uint32_t *get_current(void){return &shown;}
static const uint32_t *get_language(void){return &language;}
static uint32_t get_parent(uint32_t item){return af_ap_targets_parent(item);}
static uintptr_t test_va(uintptr_t off){
 if(off==0x28a87e8)return (uintptr_t)get_current;
 if(off==0x28b0464)return (uintptr_t)get_language;
 if(off==0x1bdb214)return (uintptr_t)get_parent;
 assert(0);return 0;
}
static int chosen(void *context,const AfApTargetChoice *choice){
 assert(context==&catalog);++calls;received=*choice;return callback_result;
}
static uint32_t menu(unsigned slot){return AF_TARGETS_SLOT_FIRST+slot-1;}
static void choose(uint32_t item){shown=item;assert(af_ap_targets_intent(item)==AF_OK);af_ap_targets_action(item);}
static void prepare(void){
 memset(&native,0,sizeof native);af_catalog_init(&catalog);shown=AF_TARGETS_ROOT;calls=language=0;callback_result=0;
 native.registered=native.enabled=1;native.base=1;native.catalog=&catalog;native.context=&catalog;native.chosen=chosen;
 AfPreset source={0},target={0};source.params[6]=target.params[6]=3;source.params[0]=1;target.base=1;target.params[0]=-2;
 assert(af_install(&catalog,7,&source,0)==0);assert(af_install(&catalog,20,&target,0)==0);
}
static void cancel_default(void){
 prepare();AfCatalog before=catalog;
 assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,1)==AF_OK);
 choose(menu(20));
 /* 旧实现把已安装目标直接拒绝；新行为必须先出现默认取消的二次确认，零chosen。 */
 assert(af_ap_targets_result()==-24 && native.active && !calls);
 assert(af_ap_targets_current()==af_ap_targets_name(AF_TARGETS_CANCEL));
 assert(af_ap_targets_show()==AF_INVALID);
 choose(AF_TARGETS_CANCEL);assert(af_ap_targets_result()==AF_TARGETS_CANCELLED && !calls);
 assert(!memcmp(&catalog,&before,sizeof catalog));
}

static void presented(void){shown=AF_TARGETS_CANCEL;assert(af_ap_targets_presented()==AF_OK);assert(af_ap_targets_stage()==AF_TARGETS_CONFIRM);}
static void overwrite_and_failure(void){
 prepare();AfCatalog before=catalog;
 assert(af_ap_targets_begin(AF_TARGETS_COPY,7,1)==AF_OK);choose(menu(20));assert(!calls);
 shown=menu(20);assert(af_ap_targets_intent(menu(20))==AF_BUSY);af_ap_targets_action(menu(20));assert(!calls);
 assert(af_ap_targets_presented()==AF_STALE);presented();
 assert(!strcmp(af_ap_targets_command_text(menu(20)),"Yes"));language=25;
 assert(!strcmp(af_ap_targets_command_text(menu(20)),"覆盖"));
 assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"确认覆盖 C20?"));
 shown=menu(20);af_ap_targets_action(menu(20));assert(!calls); /* 异步+88不得提交。 */
 choose(menu(20));assert(calls==1 && af_ap_targets_result()==AF_OK && !native.active);
 assert(received.version==2 && received.bytes==512 && received.overwrite==1 && received.generation==1);
 assert(received.op==AF_TARGETS_COPY && received.source_slot==7 && received.target_slot==20);
 assert(received.source.present && received.source.working.params[0]==1 && received.target.present && received.target.working.params[0]==-2);
 assert(received.target.revision==before.slots[19].saved_revision && received.source.revision==before.slots[6].saved_revision);
 af_ap_targets_action(menu(20));assert(calls==1 && !memcmp(&catalog,&before,sizeof catalog));
 assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,2)==AF_OK);choose(menu(20));presented();callback_result=AF_IO;
 choose(menu(20));assert(calls==2 && received.overwrite && !received.source.present && !received.source_slot);
 assert(af_ap_targets_result()==AF_IO && !memcmp(&catalog,&before,sizeof catalog));
}
static void stale_and_protected(void){
 for(unsigned changed=0;changed<3;changed++){
  prepare();assert(af_ap_targets_begin(AF_TARGETS_COPY,7,1)==AF_OK);choose(menu(20));presented();
  if(changed==0)assert(af_edit(&catalog,7,0,4)==AF_OK);
  else if(changed==1)assert(af_edit(&catalog,20,0,4)==AF_OK);else catalog.slots[19].pending.request=1;
  AfCatalog before=catalog;choose(menu(20));assert(!calls && af_ap_targets_result()==AF_STALE);
  assert(!memcmp(&catalog,&before,sizeof catalog));choose(AF_TARGETS_CANCEL);assert(!calls);
 }
 prepare();assert(af_ap_targets_begin(AF_TARGETS_COPY,7,1)==AF_OK);choose(menu(7));assert(!calls && af_ap_targets_stage()==AF_TARGETS_SELECT);
 assert(af_ap_targets_cancel()==AF_OK);
 AfPreset lut=catalog.slots[19].working;lut.kind=1;lut.payload_sha256[0]=lut.lut_sha256[0]=1;
 assert(af_install(&catalog,20,&lut,1)==AF_OK);assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,2)==AF_OK);
 choose(menu(20));assert(!calls && af_ap_targets_result()==AF_EXISTS && af_ap_targets_stage()==AF_TARGETS_SELECT);
 assert(af_ap_targets_cancel()==AF_OK);assert(af_ap_targets_begin(AF_TARGETS_COPY,20,3)==AF_OK);
 assert(!af_ap_targets_available(menu(20))&&af_ap_targets_available(menu(7)));
 assert(af_ap_targets_cancel()==AF_OK);
}
int main(int argc,char **argv){assert(argc==2);if(argv[1][0]=='c')cancel_default();else if(argv[1][0]=='o')overwrite_and_failure();else stale_and_protected();}

'''
@pytest.fixture(scope='module')
def overwrite_binary(tmp_path_factory):
 folder=tmp_path_factory.mktemp('ap-overwrite');body=(NATIVE/'af_ap_targets.c').read_text()
 resolver='static uintptr_t va(uintptr_t off) {return native.base+off;}'
 assert body.count(resolver)==1
 body=body.replace(resolver,'static uintptr_t test_va(uintptr_t off);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
 source=folder/'overwrite.c';source.write_text(HARNESS.replace('#include "af_ap_targets.c"',body));target=folder/'overwrite'
 result=subprocess.run([shutil.which('clang'),'-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),str(NATIVE/'af_slots.c'),'-o',str(target)],capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 return target

@pytest.mark.parametrize('case',['cancel','overwrite','stale'])
def test_existing_slot_overwrite_contract(overwrite_binary,case):
 result=subprocess.run([str(overwrite_binary),case],capture_output=True,text=True)
 assert result.returncode==0,result.stderr
