"""管理值应用必须有成功ENTER的一次性许可；真正按键路径另有原指令／GUI证据。"""
from pathlib import Path
import subprocess

import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'
HARNESS=r'''
#include "af_ap_manage.c"
#include <assert.h>
#include <string.h>
static uint32_t shown,language,opens,last_op,last_source;
static AfCatalog catalog;
static AfApManage manager;
static const uint32_t *current(void){return &shown;}
static const uint32_t *locale(void){return &language;}
static uintptr_t test_va(uintptr_t offset){
    if(offset==0x28a87e8)return (uintptr_t)current;
    if(offset==0x28b0464)return (uintptr_t)locale;
    assert(0);return 0;
}
static int open_picker(void *context,uint32_t op,uint32_t source){
    assert(context==&catalog);++opens;last_op=op;last_source=source;return AF_OK;
}
static void prepare(void){
    memset(&native,0,sizeof(native));af_catalog_init(&catalog);af_ap_manage_init(&manager);
    AfPreset preset={0};preset.params[6]=3;assert(af_install(&catalog,7,&preset,0)==AF_OK);
    native.base=native.enabled=native.registered=1;native.manager=&manager;native.catalog=&catalog;native.context=7;
    native.result=AF_EMPTY;native.service.capabilities=AF_MANAGE_CAP_PERSIST;
    native.picker.context=&catalog;native.picker.open=open_picker;native.picker.capabilities=14;
    opens=last_op=last_source=0;
}
static void commands(void){
    for(uint32_t op=1;op<=4;++op){
        prepare();shown=AF_MANAGE_MENU_ROOT+op;AfCatalog before=catalog;AfApManage old=manager;
        /* 方向／退出触发的无授权+88不改任何结果、焦点、目录、请求或picker。 */
        af_ap_manage_menu_action(shown);af_ap_manage_menu_action(shown);
        assert(!opens && !native.refresh && native.result==AF_EMPTY && !native.focus);
        assert(!memcmp(&old,&manager,sizeof(old))&&!memcmp(&before,&catalog,sizeof(before)));
        assert(af_ap_manage_menu_intent(shown)==AF_OK&&af_ap_manage_menu_intent(shown)==AF_BUSY);
        af_ap_manage_menu_action(AF_MANAGE_MENU_ROOT+(op==4?1:op+1));assert(native.intent==shown&&!opens);
        af_ap_manage_menu_action(shown);assert(!native.intent);
        if(op==AF_MANAGE_SAVE)assert(manager.phase==AF_MANAGE_QUEUED&&manager.job.ticket==1&&!opens);
        else assert(manager.phase==AF_MANAGE_IDLE&&opens==1&&last_op==op&&last_source==(op==2?7:0));
        AfApManage after=manager;uint32_t count=opens;
        af_ap_manage_menu_action(shown);assert(opens==count&&!memcmp(&after,&manager,sizeof(after)));
    }
}
static void cancelled_or_stale(void){
    assert(af_ap_manage_menu_intent(0)==AF_OK);prepare();shown=AF_MANAGE_MENU_SAVE;
    assert(af_ap_manage_menu_intent(AF_MANAGE_MENU_ROOT)==AF_INVALID);
    assert(af_ap_manage_menu_intent(AF_MANAGE_MENU_COPY)==AF_STALE);
    assert(af_ap_manage_menu_intent(shown)==AF_OK);
    assert(af_ap_manage_menu_intent(0)==AF_OK);af_ap_manage_menu_action(shown);assert(manager.phase==AF_MANAGE_IDLE);
    assert(af_ap_manage_menu_intent(shown)==AF_OK);shown=AF_MANAGE_MENU_COPY;
    af_ap_manage_menu_action(AF_MANAGE_MENU_SAVE);assert(!native.intent&&native.result==AF_STALE&&manager.phase==AF_MANAGE_IDLE);
    shown=AF_MANAGE_MENU_SAVE;af_ap_manage_menu_action(shown);assert(manager.phase==AF_MANAGE_IDLE);
    assert(af_ap_manage_menu_intent(shown)==AF_OK);assert(af_ap_manage_menu_context(8)==AF_OK&&!native.intent);
    af_ap_manage_menu_action(shown);assert(manager.phase==AF_MANAGE_IDLE&&!opens);
}
int main(int argc,char **argv){assert(argc==2);if(argv[1][0]=='c')commands();else cancelled_or_stale();}
'''


@pytest.fixture(scope='module')
def intent_program(tmp_path_factory):
    folder=tmp_path_factory.mktemp('manage-intent');source=folder/'intent.c';binary=folder/'intent'
    body=(NATIVE/'af_ap_manage.c').read_text()
    resolver='static uintptr_t va(uintptr_t offset) { return native.base+offset; }'
    assert body.count(resolver)==1
    body=body.replace(resolver,'static uintptr_t test_va(uintptr_t offset);\nstatic uintptr_t va(uintptr_t offset) {return test_va(offset);}')
    source.write_text(HARNESS.replace('#include "af_ap_manage.c"',body))
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),str(NATIVE/'af_slots.c'),'-o',str(binary)]
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary


@pytest.mark.parametrize('case',['commands','stale'])
def test_management_requires_single_use_enter_permission(intent_program,case):
    result=subprocess.run([str(intent_program),case],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
