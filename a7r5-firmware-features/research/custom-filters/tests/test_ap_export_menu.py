"""导出须两次原ENTER；这里只验证菜单和CPU调用契约，不执行文件或整机。"""
from pathlib import Path
import subprocess

import pytest

from test_ap_targets import HARNESS as TARGETS
from test_ap_menu_intent import HARNESS as MENU

NATIVE = Path(__file__).resolve().parents[1] / 'native'


def compile_case(tmp_path, stem, source, resolver):
    body = (NATIVE / (stem + '.c')).read_text()
    assert body.count(resolver) == 1
    body = body.replace(resolver, 'static uintptr_t test_va(uintptr_t);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
    file = tmp_path / 'export.c'
    file.write_text(source.replace('#include "' + stem + '.c"', body))
    binary = tmp_path / 'export'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                          '-I' + str(NATIVE), str(file), str(NATIVE / 'af_slots.c'), '-o', str(binary)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return binary


TARGET_EXTRA = r'''
static void export_confirm(void) {
 prepare();AfCatalog before=catalog;
 assert(af_ap_targets_begin_export(7,1)==AF_OK);
 assert(af_ap_targets_stage()==AF_TARGETS_CONFIRM_WAIT);
 assert(af_ap_targets_current()==af_ap_targets_name(AF_TARGETS_CANCEL));
 assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"Export saved C07?"));
 assert(!strcmp(af_ap_targets_command_text(menu(7)),"Yes"));
 assert(af_ap_targets_intent(menu(7))==AF_STALE);
 shown=menu(7);assert(af_ap_targets_intent(menu(7))==AF_BUSY);
 af_ap_targets_action(menu(7));assert(!calls);
 shown=AF_TARGETS_CANCEL;assert(af_ap_targets_presented()==AF_OK);
 af_ap_targets_action(menu(7));assert(!calls); /* 高亮和异步+88都无许可。 */
 choose(AF_TARGETS_CANCEL);assert(!calls&&!memcmp(&before,&catalog,sizeof before));
 assert(af_ap_targets_begin_export(7,2)==AF_OK);shown=AF_TARGETS_CANCEL;
 assert(af_ap_targets_presented()==AF_OK);language=25;
 assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"导出已保存 C07?"));
 assert(!strcmp(af_ap_targets_command_text(menu(7)),"导出"));
 choose(menu(7));assert(calls==1&&received.op==AF_MANAGE_EXPORT&&received.source_slot==7&&received.target_slot==7&&!received.overwrite);
 assert(received.source.revision==1&&received.target.revision==1);
 choose(menu(7));assert(calls==1&&!memcmp(&before,&catalog,sizeof before));
}
static void export_reject(void) {
 prepare();assert(af_ap_targets_begin_export(0,1)==AF_INVALID);
 assert(af_ap_targets_begin_export(6,1)==AF_EMPTY); /* 原生数据不自动迁移为overlay。 */
 assert(af_ap_targets_begin_export(21,1)==AF_INVALID);
 assert(af_ap_targets_begin_export(20,1)==AF_EMPTY);
 catalog.slots[6].pending.request=1;assert(af_ap_targets_begin_export(7,1)==AF_BUSY);
 catalog.slots[6].pending.request=0;catalog.slots[6].working.kind=1;
 assert(af_ap_targets_begin_export(7,1)==AF_INVALID);catalog.slots[6].working.kind=0;
 assert(af_ap_targets_begin_export(7,1)==AF_OK);shown=AF_TARGETS_CANCEL;
 assert(af_ap_targets_presented()==AF_OK);assert(af_edit(&catalog,7,0,4)==AF_OK);
 AfCatalog before=catalog;choose(menu(7));assert(!calls&&af_ap_targets_result()==AF_STALE);
 assert(!memcmp(&before,&catalog,sizeof before));choose(AF_TARGETS_CANCEL);assert(!calls);
}
int main(int argc,char **argv){assert(argc==2);if(argv[1][0]=='p')export_confirm();else export_reject();}
'''


@pytest.mark.parametrize('case', ['positive', 'reject'])
def test_export_confirmation_is_default_cancel_and_rechecks_the_whole_source(tmp_path, case):
    source = TARGETS.split('int main(int argc,char **argv)')[0] + TARGET_EXTRA
    binary = compile_case(tmp_path, 'af_ap_targets', source,
                          'static uintptr_t va(uintptr_t off) {return native.base+off;}')
    run = subprocess.run([str(binary), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


MENU_EXTRA = r'''
int main(void){
 prepare();shown=AF_MANAGE_MENU_EXPORT;
 assert(af_ap_manage_menu_for_op(7)==0x1604&&af_ap_manage_menu_parent(shown)==AF_MANAGE_MENU_ROOT);
 assert(af_ap_manage_menu_is_id(shown)&&af_ap_manage_menu_name(shown)==AF_MANAGE_TEXT_FIRST+7);
 for(uint32_t x=0x15ec;x<=0x1601;++x)assert(!af_ap_manage_menu_is_id(x));
 AfCatalog before=catalog;AfApManage old=manager;af_ap_manage_menu_action(shown);
 assert(!opens&&!memcmp(&old,&manager,sizeof old));
 assert(af_ap_manage_menu_intent(shown)==AF_OK);af_ap_manage_menu_action(shown);
 assert(!opens&&!memcmp(&old,&manager,sizeof old)); /* 旧服务能力绝不开放导出。 */
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+7),"Export (Unavailable)"));
 native.service.capabilities|=AF_MANAGE_CAP(AF_MANAGE_EXPORT);native.picker.capabilities|=AF_MANAGE_CAP(AF_MANAGE_EXPORT);
 assert(af_ap_manage_menu_intent(shown)==AF_OK);af_ap_manage_menu_action(shown);
 assert(opens==1&&last_op==AF_MANAGE_EXPORT&&!last_source&&manager.phase==AF_MANAGE_IDLE);
 af_ap_manage_menu_action(shown);assert(opens==1&&!memcmp(&before,&catalog,sizeof before));
 af_ap_manage_menu_focus(6);assert(af_ap_manage_menu_current()==6);
 language=25;assert(af_ap_manage_menu_notice(7,AF_MANAGE_CANCEL)==AF_OK);
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+7),"已取消"));
 assert(af_ap_manage_menu_notice(7,AF_STALE)==AF_OK);
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+7),"导出失败"));
 native.result=AF_OK;manager.job.ticket=1;manager.job.request.op=AF_MANAGE_EXPORT;manager.phase=AF_MANAGE_DONE;
 assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+7),"已导出"));
 manager.phase=AF_MANAGE_UNCERTAIN;assert(!strcmp(af_ap_manage_menu_text(AF_MANAGE_TEXT_FIRST+7),"导出状态不确定"));
 return 0;
}
'''


def test_export_menu_does_not_queue_on_hover_or_without_a_library_capability(tmp_path):
    source = MENU.split('int main(int argc,char **argv)')[0] + MENU_EXTRA
    binary = compile_case(tmp_path, 'af_ap_manage', source,
                          'static uintptr_t va(uintptr_t offset) { return native.base+offset; }')
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
