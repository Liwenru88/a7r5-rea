"""目标选择的真实C契约：只有确认空槽才回调，取消/陈旧选择没有队列副作用。"""
from pathlib import Path
import shutil,subprocess
import pytest
NATIVE=Path(__file__).resolve().parents[1]/'native'
HARNESS=r'''
#include "af_ap_targets.c"
#include <assert.h>
#include <string.h>
static uint32_t shown=AF_TARGETS_ROOT,calls;
static uint32_t language;
static uint32_t parent_override=UINT32_MAX;
static int callback_result;
static AfApTargetChoice received;
static AfCatalog catalog;
static const uint32_t *get_current(void) {return &shown;}
static const uint32_t *get_language(void) {return &language;}
static uint32_t get_parent(uint32_t item) {return parent_override==UINT32_MAX?af_ap_targets_parent(item):parent_override;}
static uintptr_t test_va(uintptr_t off) {
    if(off==0x28a87e8)return (uintptr_t)get_current;
    if(off==0x28b0464)return (uintptr_t)get_language;
    if(off==0x1bdb214)return (uintptr_t)get_parent;
    assert(0);return 0;
}
static int chosen(void *context,const AfApTargetChoice *choice) {
    assert(context==&catalog);++calls;received=*choice;
    assert(af_ap_targets_cancel()==AF_BUSY);
    assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,choice->generation+1)==AF_BUSY);
    return callback_result;
}
static void prepare(void) {
    memset(&native,0,sizeof(native));af_catalog_init(&catalog);calls=0;callback_result=0;
    native.registered=native.enabled=1;native.base=1;parent_override=UINT32_MAX;language=0;
    native.catalog=&catalog;native.context=&catalog;native.chosen=chosen;
    AfPreset p={0};p.params[6]=3;assert(af_install(&catalog,7,&p,0)==0);assert(af_install(&catalog,8,&p,0)==0);
}
static uint32_t menu(unsigned slot) {return AF_TARGETS_SLOT_FIRST+slot-1;}
/* 显式模拟真实ENTER成功关闭点的许可；不把+88本身当确认。 */
static void choose(uint32_t item) {shown=item;int status=af_ap_targets_intent(item);if(native.active)assert(status==AF_OK);af_ap_targets_action(item);}
static void copy_and_cancel(void) {
    prepare();AfCatalog before=catalog;
    assert(af_ap_targets_begin(AF_TARGETS_COPY,7,1)==0);
    shown=menu(20);af_ap_targets_action(menu(20));
    assert(!calls && native.active); /* 方向键的+88不代表用户确认。 */
    assert(af_ap_targets_intent(menu(20))==AF_OK && af_ap_targets_intent(menu(20))==AF_BUSY);
    af_ap_targets_action(menu(19));assert(!calls && native.intent);
    assert(af_ap_targets_intent(0)==AF_OK);af_ap_targets_action(menu(20));assert(!calls);
    assert(af_ap_targets_available(menu(1)) && af_ap_targets_available(menu(8)) && af_ap_targets_available(menu(20)));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(1))),"C01 (Original)"));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(7))),"C07 (Source)"));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(20))),"C20 (Empty)"));
    uint32_t old_token=af_ap_targets_name(menu(20));choose(menu(20));
    assert(calls==1 && received.generation==1 && received.op==AF_TARGETS_COPY && received.source_slot==7 && received.target_slot==20);
    assert(af_ap_targets_result()==AF_OK && !memcmp(&before,&catalog,sizeof(catalog)));
    choose(menu(20));assert(calls==1);
    assert(af_ap_targets_begin(AF_TARGETS_COPY,7,2)==0);
    af_ap_targets_focus(old_token);assert(!native.focus);
    shown=menu(19);assert(af_ap_targets_intent(menu(20))==AF_STALE);
    af_ap_targets_action(menu(20));assert(af_ap_targets_result()==AF_EMPTY && calls==1);
    shown=AF_TARGETS_ROOT;assert(af_ap_targets_intent(menu(20))==AF_STALE);
    af_ap_targets_action(menu(20));assert(af_ap_targets_result()==AF_EMPTY && calls==1);
    shown=menu(20);parent_override=0x7f;assert(af_ap_targets_intent(menu(20))==AF_OK);af_ap_targets_action(menu(20));
    assert(af_ap_targets_result()==AF_STALE && calls==1);parent_override=UINT32_MAX;
    choose(AF_TARGETS_CANCEL);assert(af_ap_targets_result()==AF_TARGETS_CANCELLED && calls==1);
    assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,2)==AF_STALE);
}
static void stale_and_fail(void) {
    prepare();assert(af_ap_targets_begin(AF_TARGETS_COPY,7,10)==0);
    assert(af_edit(&catalog,7,0,4)==0);assert(!af_ap_targets_disabled());choose(menu(20));assert(af_ap_targets_result()==AF_STALE && !calls);
    assert(af_ap_targets_cancel()==0);
    assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,11)==0);
    AfPreset p={0};p.params[6]=3;assert(af_install(&catalog,20,&p,0)==0);
    choose(menu(20));assert(af_ap_targets_result()==AF_STALE && !calls);
    catalog.slots[18].pending.request=1;assert(!af_ap_targets_available(menu(19)));
    choose(menu(19));assert(af_ap_targets_result()==AF_STALE && !calls);
    catalog.slots[18].pending.request=0;callback_result=AF_IO;AfCatalog before=catalog;
    choose(menu(18));assert(calls==1 && received.op==AF_TARGETS_CREATE && !received.source_slot && received.target_slot==18);
    assert(af_ap_targets_result()==AF_IO && !native.active && !memcmp(&catalog,&before,sizeof(catalog)));
    assert(af_ap_targets_begin(AF_TARGETS_COPY,0,12)==AF_INVALID);
    assert(af_ap_targets_begin(AF_TARGETS_CREATE,7,12)==AF_INVALID);
    for(unsigned i=7;i<=20;++i)if(!catalog.slots[i-1].present)assert(af_install(&catalog,i,&p,0)==0);
    assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,12)==0);
    assert(af_ap_targets_current()==af_ap_targets_name(menu(7)));
    choose(AF_TARGETS_CANCEL);assert(calls==1);
    for(unsigned i=13;native.serial<255;++i) {assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,i)==0);assert(af_ap_targets_cancel()==0);}
    assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,1000)==AF_EXHAUSTED);
}
static void localization(void) {
    prepare();language=25;
    assert(af_ap_targets_begin(AF_TARGETS_COPY,7,1)==AF_OK);
    AfCatalog before=catalog;
    assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"另存为：选择槽位"));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(1))),"C01（原厂）"));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(7))),"C07（源槽）"));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(8))),"C08（已占用）"));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(20))),"C20（空闲）"));
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(AF_TARGETS_CANCEL)),"取消"));
    uint32_t old=af_ap_targets_name(menu(20));language=0;
    assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"Save As: target"));
    assert(!strcmp(af_ap_targets_text(old),"C20 (Empty)"));language=25;
    assert(!memcmp(&before,&catalog,sizeof(catalog)) && !calls && !native.intent);
    assert(af_ap_targets_cancel()==AF_OK);
    assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,2)==AF_OK);
    assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"新建：选择槽位"));
    assert(!strcmp(af_ap_targets_text(old),"选择已变化"));
    catalog.slots[19].pending.request=1;
    assert(!strcmp(af_ap_targets_text(af_ap_targets_name(menu(20))),"C20（不可用）"));
    assert(!calls && !native.intent);
}
int main(int argc,char **argv) {assert(argc==2);if(argv[1][0]=='c')copy_and_cancel();else if(argv[1][0]=='l')localization();else stale_and_fail();}
'''
@pytest.fixture(scope='module')
def targets_binary(tmp_path_factory):
    folder=tmp_path_factory.mktemp('ap-targets');source=folder/'targets.c'
    # 宿主无法执行AP绝对地址；只把统一地址解析换成显式模型/父项边界。
    body=(NATIVE/'af_ap_targets.c').read_text()
    resolver='static uintptr_t va(uintptr_t off) {return native.base+off;}'
    assert body.count(resolver)==1
    body=body.replace(resolver,'static uintptr_t test_va(uintptr_t off);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
    source.write_text(HARNESS.replace('#include "af_ap_targets.c"',body))
    target=folder/'targets';compiler=shutil.which('clang') or shutil.which('cc')
    subprocess.run([compiler,'-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),str(NATIVE/'af_slots.c'),'-o',str(target)],check=True,capture_output=True,text=True)
    return target
@pytest.mark.parametrize('case',['copy','stale','localization'])
def test_target_selection_contract(targets_binary,case):
    subprocess.run([str(targets_binary),case],check=True,capture_output=True,text=True)
