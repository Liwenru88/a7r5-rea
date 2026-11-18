"""非连续清空ID及旧服务能力隔离；仅明确ENTER意图可打开选择。"""
from pathlib import Path
import subprocess
from test_ap_menu_intent import HARNESS
NATIVE=Path(__file__).resolve().parents[1]/'native'
EXTRA=r'''
static void clear_mapping(void){
 prepare();native.picker.capabilities|=AF_MANAGE_CAP(AF_MANAGE_CLEAR);shown=AF_MANAGE_MENU_CLEAR;
 assert(af_ap_manage_menu_for_op(5)==0x1602&&af_ap_manage_menu_parent(shown)==AF_MANAGE_MENU_ROOT);
 assert(af_ap_manage_menu_is_id(shown)&&af_ap_manage_menu_name(shown)==AF_MANAGE_TEXT_FIRST+5);
 for(uint32_t menu=0x15ec;menu<=0x1601;++menu)assert(!af_ap_manage_menu_is_id(menu));
 AfApManage before=manager;AfCatalog old=catalog;af_ap_manage_menu_action(shown);
 assert(!opens&&!memcmp(&before,&manager,sizeof manager));
 native.service.capabilities=11;assert(af_ap_manage_menu_intent(shown)==AF_OK);af_ap_manage_menu_action(shown);
 assert(!opens&&!memcmp(&before,&manager,sizeof manager));
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+5),"Clear (Unavailable)"));
 native.service.capabilities=AF_MANAGE_CAP_PERSIST;
 assert(af_ap_manage_menu_intent(shown)==AF_OK);af_ap_manage_menu_action(shown);
 assert(opens==1&&last_op==AF_MANAGE_CLEAR&&!last_source&&manager.phase==AF_MANAGE_IDLE);
 af_ap_manage_menu_action(shown);assert(opens==1&&!memcmp(&catalog,&old,sizeof old));
 language=25;assert(af_ap_manage_menu_notice(5,AF_MANAGE_CANCEL)==AF_OK);
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+5),"已取消"));
 assert(af_ap_manage_menu_notice(5,AF_STALE)==AF_OK);
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+5),"清空失败"));
}
int main(int argc,char **argv){assert(argc==2);if(argv[1][0]=='q')clear_mapping();
 else if(argv[1][0]=='c')commands();else cancelled_or_stale();}
'''
def test_clear_uses_independent_row_and_missing_service_cap_never_opens_or_queues(tmp_path):
 body=(NATIVE/'af_ap_manage.c').read_text();old='static uintptr_t va(uintptr_t offset) { return native.base+offset; }'
 assert body.count(old)==1
 body=body.replace(old,'static uintptr_t test_va(uintptr_t);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
 source=tmp_path/'clear.c';source.write_text((HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA).replace('#include "af_ap_manage.c"',body))
 binary=tmp_path/'clear'
 run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),str(NATIVE/'af_slots.c'),'-o',str(binary)],capture_output=True,text=True)
 assert run.returncode==0,run.stderr
 run=subprocess.run([str(binary),'q'],capture_output=True,text=True);assert run.returncode==0,run.stderr
