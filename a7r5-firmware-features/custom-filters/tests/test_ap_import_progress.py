"""分批导入的原菜单进度与一次性ENTER取消，提交阶段不能取消。"""
import subprocess

from test_ap_export_menu import compile_case
from test_ap_menu_intent import HARNESS


EXTRA = r'''
int main(void){
 prepare();shown=AF_MANAGE_MENU_IMPORT;
 manager.job.request.op=AF_MANAGE_IMPORT;manager.job.ticket=7;manager.phase=AF_MANAGE_RUNNING;
 manager.progress_done=710;manager.progress_total=1000;native.focus=2;
 assert(af_ap_manage_menu_disabled()==0);
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+3),"Import 71% (Enter to cancel)"));
 af_ap_manage_menu_action(shown);assert(!manager.cancel_requested&&!opens);
 native.focus=1;assert(af_ap_manage_menu_disabled()==1);native.focus=2;
 assert(af_ap_manage_menu_intent(shown)==0);af_ap_manage_menu_action(shown);
 assert(manager.cancel_requested&&manager.phase==AF_MANAGE_RUNNING&&!opens);
 assert(af_ap_manage_menu_disabled()==1);
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+3),"Cancelling import..."));
 manager.cancel_requested=0;manager.phase=AF_MANAGE_COMMITTING;
 assert(af_ap_manage_menu_disabled()==1);
 assert(af_ap_manage_menu_intent(shown)==0);af_ap_manage_menu_action(shown);
 assert(!manager.cancel_requested&&manager.phase==AF_MANAGE_COMMITTING&&!opens&&native.result==AF_BUSY);
 manager.phase=AF_MANAGE_RUNNING;language=25;manager.progress_done=1000;
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+3),"导入 100%（确定可取消）"));
 shown=AF_MANAGE_MENU_CREATE;assert(af_ap_manage_menu_intent(shown)==0);af_ap_manage_menu_action(shown);
 assert(!manager.cancel_requested&&!opens&&native.result==AF_BUSY);return 0;
}
'''


def test_import_progress_and_cancel_use_existing_enter_gate(tmp_path):
    source = HARNESS.split('int main(int argc,char **argv)')[0] + EXTRA
    binary = compile_case(tmp_path, 'af_ap_manage', source,
                          'static uintptr_t va(uintptr_t offset) { return native.base+offset; }')
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
