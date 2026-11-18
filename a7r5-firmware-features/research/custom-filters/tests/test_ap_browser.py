"""只读浏览契约：分页、同代选择与旧令牌拒绝；不把选择称作导入。"""
from pathlib import Path
import shutil,subprocess
import pytest
NATIVE=Path(__file__).resolve().parents[1]/'native'
HARNESS=r'''
#include "af_ap_browser.c"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint32_t shown=AF_BROWSER_MENU_ROOT;
static uint32_t language;
static uint32_t parent_override=UINT32_MAX;
static const uint32_t *current(void) {return &shown;}
static const uint32_t *get_language(void) {return &language;}
static uint32_t get_parent(uint32_t menu) {return parent_override==UINT32_MAX?af_ap_browser_parent(menu):parent_override;}
static uintptr_t test_va(uintptr_t off) {
    if(off==0x28a87e8)return (uintptr_t)current;
    if(off==0x28b0464)return (uintptr_t)get_language;
    if(off==0x1bdb214)return (uintptr_t)get_parent;
    assert(0);return 0;
}
static AfMediaList input(unsigned count,uint64_t generation) {
    AfMediaList list={0};list.generation=generation;list.device=3;list.inode=44;list.count=count;
    for(unsigned i=0;i<count;++i) {snprintf(list.entries[i].name,128,"filter%02u.Cube",i);list.entries[i].size=64;}
    return list;
}
static void prepare(void) {
    memset(&native,0,sizeof(native));native.registered=native.enabled=1;
    native.base=1;parent_override=UINT32_MAX;language=0;
    for(unsigned i=0;i<68;++i)put32(native.records[i],AF_BROWSER_MENU_ROOT+i);
}
/* 只模拟ENTER成功关闭点的许可；原方向/ENTER分派另有原指令和GUI证据。 */
static void choose(uint32_t menu) {shown=menu;assert(af_ap_browser_intent(menu)==AF_OK);af_ap_browser_action(menu);}
static void pages(void) {
    prepare();AfMediaList list=input(64,8),before=list;AfApBrowserSelection selection={91,92,93},old=selection;
    assert(af_ap_browser_publish(&list)==AF_OK);uint32_t first_token=af_ap_browser_name(AF_BROWSER_MENU_FILE_FIRST);
    shown=AF_BROWSER_MENU_FILE_FIRST;af_ap_browser_action(AF_BROWSER_MENU_FILE_FIRST);
    assert(native.active && !native.selected && af_ap_browser_result()==AF_EMPTY);
    assert(af_ap_browser_intent(AF_BROWSER_MENU_FILE_FIRST)==AF_OK);
    assert(af_ap_browser_intent(AF_BROWSER_MENU_FILE_FIRST)==AF_BUSY);
    af_ap_browser_action(AF_BROWSER_MENU_NEXT);assert(!af_ap_browser_page() && native.intent);
    assert(af_ap_browser_intent(0)==AF_OK);
    af_ap_browser_action(AF_BROWSER_MENU_FILE_FIRST);assert(native.active && !native.selected);
    shown=AF_BROWSER_MENU_ROOT;
    assert(af_ap_browser_rows()==19 && af_ap_browser_page()==0);
    assert(!strcmp(af_ap_browser_text(first_token),"filter00.Cube"));
    assert(af_ap_browser_take(8,&selection)==AF_EMPTY && !memcmp(&selection,&old,sizeof(old)));
    af_ap_browser_action(AF_BROWSER_MENU_FILE_FIRST);assert(af_ap_browser_result()==AF_EMPTY);
    assert(af_ap_browser_publish(&list)==AF_BUSY);
    choose(AF_BROWSER_MENU_NEXT);assert(af_ap_browser_page()==1 && af_ap_browser_rows()==20);
    af_ap_browser_action(AF_BROWSER_MENU_NEXT);assert(af_ap_browser_page()==1); /* leave不能重复授权换页。 */
    choose(AF_BROWSER_MENU_FILE_FIRST);assert(af_ap_browser_result()==AF_STALE);
    choose(AF_BROWSER_MENU_NEXT);assert(af_ap_browser_page()==2 && af_ap_browser_rows()==20);
    choose(AF_BROWSER_MENU_NEXT);assert(af_ap_browser_page()==3 && af_ap_browser_rows()==15);
    choose(AF_BROWSER_MENU_PREVIOUS);assert(af_ap_browser_page()==2);
    choose(AF_BROWSER_MENU_NEXT);choose(AF_BROWSER_MENU_FILE_FIRST+63);
    assert(af_ap_browser_result()==AF_OK);
    assert(af_ap_browser_take(7,&selection)==AF_STALE && !memcmp(&selection,&old,sizeof(old)));
    assert(af_ap_browser_take(8,&selection)==AF_OK && selection.generation==8 && selection.index==63 && !selection.reserved);
    assert(af_ap_browser_take(8,&selection)==AF_EMPTY);assert(!memcmp(&list,&before,sizeof(list)));
    list=input(2,9);assert(af_ap_browser_publish(&list)==AF_OK);
    assert(!strcmp(af_ap_browser_text(first_token),"List changed"));
    af_ap_browser_focus(first_token);assert(!native.focus);
    shown=AF_BROWSER_MENU_FILE_FIRST+1;assert(af_ap_browser_intent(AF_BROWSER_MENU_FILE_FIRST)==AF_STALE);
    af_ap_browser_action(AF_BROWSER_MENU_FILE_FIRST);assert(af_ap_browser_result()==AF_EMPTY);
    shown=AF_BROWSER_MENU_FILE_FIRST;parent_override=0x7f;assert(af_ap_browser_intent(AF_BROWSER_MENU_FILE_FIRST)==AF_OK);
    af_ap_browser_action(AF_BROWSER_MENU_FILE_FIRST);
    assert(af_ap_browser_result()==AF_STALE);parent_override=UINT32_MAX;
    choose(AF_BROWSER_MENU_CANCEL);assert(af_ap_browser_result()==AF_BROWSER_CANCELLED);
    assert(af_ap_browser_take(9,&selection)==AF_EMPTY);
    assert(af_ap_browser_publish(&list)==AF_STALE);list.generation=10;assert(af_ap_browser_publish(&list)==AF_OK);
    shown=0x15ea;assert(af_ap_browser_intent(AF_BROWSER_MENU_FILE_FIRST)==AF_STALE);
    af_ap_browser_action(AF_BROWSER_MENU_FILE_FIRST);assert(af_ap_browser_result()==AF_EMPTY);
    shown=AF_BROWSER_MENU_ROOT;assert(af_ap_browser_intent(AF_BROWSER_MENU_FILE_FIRST)==AF_STALE);
    af_ap_browser_action(AF_BROWSER_MENU_FILE_FIRST);assert(af_ap_browser_result()==AF_EMPTY);
    choose(AF_BROWSER_MENU_FILE_FIRST);assert(af_ap_browser_take(10,&selection)==AF_OK);
}
static void invalid(void) {
    prepare();AfMediaList list=input(2,1);list.entries[1]=list.entries[0];assert(af_ap_browser_publish(&list)==AF_INVALID);
    list=input(2,1);strcpy(list.entries[1].name,"../x.cube");assert(af_ap_browser_publish(&list)==AF_INVALID);
    list=input(1,1);strcpy(list.entries[0].name,"abc\xc0\x80.cube");assert(af_ap_browser_publish(&list)==AF_INVALID);
    list=input(1,1);list.entries[0].nanoseconds=-1;assert(af_ap_browser_publish(&list)==AF_INVALID);
    list=input(0,1);assert(af_ap_browser_publish(&list)==AF_OK && af_ap_browser_rows()==1);
    assert(!strcmp(af_ap_browser_text(AF_BROWSER_TEXT_FIRST),"No LUT or preset files"));choose(AF_BROWSER_MENU_CANCEL);
    for(unsigned i=2;i<=255;++i) {list.generation=i;assert(af_ap_browser_publish(&list)==AF_OK);choose(AF_BROWSER_MENU_CANCEL);}
    list.generation=256;assert(af_ap_browser_publish(&list)==AF_EXHAUSTED);
}
static void localization(void) {
    prepare();language=25;
    assert(!strcmp(af_ap_browser_text(AF_BROWSER_TEXT_FIRST),"没有LUT或滤镜配方"));
    AfMediaList list=input(1,1);strcpy(list.entries[0].name,"中文测试.A7FILTER");
    assert(af_ap_browser_publish(&list)==AF_OK);
    uint32_t file=af_ap_browser_name(AF_BROWSER_MENU_FILE_FIRST);
    assert(!strcmp(af_ap_browser_text(AF_BROWSER_TEXT_FIRST),"选择LUT或滤镜配方"));
    assert(!strcmp(af_ap_browser_text(af_ap_browser_name(AF_BROWSER_MENU_PREVIOUS)),"上一页"));
    assert(!strcmp(af_ap_browser_text(af_ap_browser_name(AF_BROWSER_MENU_NEXT)),"下一页"));
    assert(!strcmp(af_ap_browser_text(af_ap_browser_name(AF_BROWSER_MENU_CANCEL)),"取消"));
    assert(!strcmp(af_ap_browser_text(file),"中文测试.A7FILTER"));
    language=0;assert(!strcmp(af_ap_browser_text(AF_BROWSER_TEXT_FIRST),"Choose LUT or preset"));
    assert(!strcmp(af_ap_browser_text(file),"中文测试.A7FILTER"));language=25;
    choose(AF_BROWSER_MENU_CANCEL);list.generation=2;
    assert(af_ap_browser_publish(&list)==AF_OK);
    assert(!strcmp(af_ap_browser_text(file),"列表已变化"));
    assert(native.active && !native.selected && !native.intent && native.list.generation==2);
}
int main(int argc,char **argv) {assert(argc==2);if(argv[1][0]=='p')pages();else if(argv[1][0]=='l')localization();else invalid();}
'''
@pytest.fixture(scope='module')
def browser_binary(tmp_path_factory):
    folder=tmp_path_factory.mktemp('ap-browser');source=folder/'browser.c'
    # 同一产品C，只替换不可在宿主调用的AP地址解析；真实入口另由A64运行。
    body=(NATIVE/'af_ap_browser.c').read_text()
    resolver='static uintptr_t va(uintptr_t off) {return native.base+off;}'
    assert body.count(resolver)==1
    body=body.replace(resolver,'static uintptr_t test_va(uintptr_t off);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
    source.write_text(HARNESS.replace('#include "af_ap_browser.c"',body))
    target=folder/'browser';compiler=shutil.which('clang') or shutil.which('cc')
    subprocess.run([compiler,'-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),'-o',str(target)],check=True,capture_output=True,text=True)
    return target
@pytest.mark.parametrize('case',['pages','invalid','localization'])
def test_readonly_browser_contract(browser_binary,case):
    subprocess.run([str(browser_binary),case],check=True,capture_output=True,text=True)
