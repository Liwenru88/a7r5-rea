"""清空只选非当前已装槽；完整LUT另有同类契约，不将+88当作确认。"""
from pathlib import Path
import shutil
import subprocess
import pytest
from test_ap_targets_overwrite import HARNESS
NATIVE=Path(__file__).resolve().parents[1]/'native'
EXTRA=r'''
static void clear_contract(void){
 prepare();AfCatalog before=catalog;
 assert(af_ap_targets_begin_clear(21,1)==AF_INVALID);
 assert(af_ap_targets_begin(AF_TARGETS_CLEAR,0,1)==AF_INVALID);
 assert(af_ap_targets_begin_clear(7,1)==AF_OK);
 assert(!af_ap_targets_available(menu(1))&&!af_ap_targets_available(menu(7))&&!af_ap_targets_available(menu(8)));
 assert(af_ap_targets_available(menu(20))&&af_ap_targets_current()==af_ap_targets_name(menu(20)));
 shown=menu(20);af_ap_targets_action(shown);assert(!calls&&af_ap_targets_stage()==AF_TARGETS_SELECT);
 choose(menu(20));assert(!calls&&af_ap_targets_stage()==AF_TARGETS_CONFIRM_WAIT);
 assert(af_ap_targets_current()==af_ap_targets_name(AF_TARGETS_CANCEL));
 assert(af_ap_targets_intent(menu(20))==AF_BUSY);choose(AF_TARGETS_CANCEL);
 assert(!calls&&!memcmp(&catalog,&before,sizeof before));
 assert(af_ap_targets_begin_clear(7,2)==AF_OK);choose(menu(20));presented();
 language=25;assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"确认清空 C20?"));
 assert(!strcmp(af_ap_targets_command_text(menu(20)),"清空"));
 assert(af_edit(&catalog,20,0,4)==AF_OK);before=catalog;choose(menu(20));
 assert(!calls&&af_ap_targets_result()==AF_STALE&&!memcmp(&catalog,&before,sizeof before));
 assert(af_ap_targets_cancel()==AF_OK);
 assert(af_ap_targets_begin_clear(7,3)==AF_OK);choose(menu(20));presented();
 choose(menu(20));assert(calls==1&&af_ap_targets_result()==AF_OK);
 assert(received.version==2&&received.bytes==512&&received.op==AF_TARGETS_CLEAR&&received.overwrite==1);
 AfApManageSlot empty={0};assert(!received.source_slot&&!memcmp(&received.source,&empty,sizeof empty));
 assert(received.target_slot==20&&received.target.present&&received.target.working.params[0]==4);
 assert(!memcmp(&catalog,&before,sizeof before));af_ap_targets_action(menu(20));assert(calls==1);
 assert(af_ap_targets_begin_clear(20,4)==AF_OK);assert(!af_ap_targets_available(menu(20)));
 assert(af_ap_targets_available(menu(7)));choose(menu(7));presented();callback_result=AF_IO;
 choose(menu(7));assert(calls==2&&af_ap_targets_result()==AF_IO&&!memcmp(&catalog,&before,sizeof before));
}
int main(int argc,char **argv){assert(argc==2);if(argv[1][0]=='q')clear_contract();
 else if(argv[1][0]=='c')cancel_default();else if(argv[1][0]=='o')overwrite_and_failure();else stale_and_protected();}
'''

def test_clear_target_protects_current_empty_original_and_requires_second_enter(tmp_path):
 body=(NATIVE/'af_ap_targets.c').read_text()
 old='static uintptr_t va(uintptr_t off) {return native.base+off;}'
 assert body.count(old)==1
 body=body.replace(old,'static uintptr_t test_va(uintptr_t off);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
 source=tmp_path/'clear.c';source.write_text((HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA).replace('#include "af_ap_targets.c"',body))
 binary=tmp_path/'clear'
 result=subprocess.run([shutil.which('clang'),'-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),str(NATIVE/'af_slots.c'),'-o',str(binary)],capture_output=True,text=True)
 assert result.returncode==0,result.stderr
 result=subprocess.run([str(binary),'q'],capture_output=True,text=True)
 assert result.returncode==0,result.stderr
