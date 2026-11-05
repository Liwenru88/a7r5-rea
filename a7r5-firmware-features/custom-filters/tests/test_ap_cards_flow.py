"""实际UI函数的宿主生命周期边界；不执行原AP或模拟器，不访问文件/卡。"""
from pathlib import Path
import subprocess
import pytest
from test_ap_cards import HARNESS as CARDS

NATIVE=Path(__file__).resolve().parents[1]/'native'

PREFIX=r'''
#include "af_ap_ui.h"
#include "af_ap_media.h"
typedef uintptr_t Word;
AfCatalog af_ap_catalog;
AfApManage af_ap_manager;
static uint32_t enabled=1,group,can_select=1,route_calls,scans,opens,cleanup,selected_slot;
static uint32_t opened_root;
static int notice,route_fault,scan_fault;
static Word ap_base=1;
static struct {uint32_t phase;} rename_ui;
static uint64_t manage_selection_generation,manage_ui_ticket;
static uint32_t manage_ui_stage,manage_ui_op,manage_ui_root,manage_ui_page,manage_ui_prepared,manage_ui_from_root;
static uint32_t manage_ui_physical=UINT32_MAX,manage_ui_import_valid;
static int manage_ui_result;
static AfApManageRequest manage_ui_import;
static uint32_t confirm_active,confirm_consumed,confirm_group,confirm_menu;
static void *confirm_controller;
static int (*confirm_intent)(uint32_t);
static void (*confirm_action)(uint32_t);
static const uint32_t *group_value(void){return &group;}
static void close_original(void *p){(void)p;}
static Word ap_address(Word off){
 if(off==0x58da458)return 0x7710;
 if(off==0x58d2fb8)return 0x7720;
 if(off==0x28a8720)return (Word)group_value;
 if(off==0x21edb2c)return (Word)close_original;
 return test_va(off);
}
static uint32_t current_menu(void){return shown;}
static uint32_t get32(const void *p){uint32_t v;memcpy(&v,p,4);return v;}
static void rename_abort(void){}
static int rename_begin(uint32_t s){(void)s;return AF_MANAGE_NOT_READY;}
static int rename_prepare(void){return AF_MANAGE_NOT_READY;}
static int rename_finish(uint32_t s){(void)s;return AF_MANAGE_NOT_READY;}
static uint32_t ui_active_user_slot(void){return 7;}
static int ui_open_d4(void *p,uint32_t root){(void)p;++opens;opened_root=root;group=root;return AF_OK;}
static void ui_manage_save_return(uint64_t t){(void)t;}
void af_ap_confirm_close(void *);
static uint32_t af_stock_confirm(void *controller,void *event){
 /* 原值应用可能在方向事件中出现；只有原关闭资格边界才调用close。 */
 af_ap_cards_action(shown);
 if(*(int *)event){af_ap_confirm_close(controller);af_ap_confirm_close(controller);}
 return 1;
}
int af_ap_manage_menu_intent(uint32_t m){(void)m;return AF_OK;}
void af_ap_manage_menu_action(uint32_t m){(void)m;}
int af_ap_targets_intent(uint32_t m){(void)m;return AF_OK;}
void af_ap_targets_action(uint32_t m){(void)m;}
int af_ap_browser_intent(uint32_t m){(void)m;return AF_OK;}
void af_ap_browser_action(uint32_t m){(void)m;}
int af_ap_manage_menu_is_id(uint32_t m){return m>=0x15e7&&m<=0x15eb;}
int af_ap_targets_is_id(uint32_t m){return m>=0x15ec&&m<=0x1601;}
int af_ap_browser_is_id(uint32_t m){return m>=0x1620&&m<=0x1663;}
uint32_t af_ap_manage_menu_for_op(uint32_t op){return 0x15e7+op;}
int af_ap_targets_begin(uint32_t op,uint32_t slot,uint64_t g){(void)op;(void)slot;(void)g;return AF_OK;}
int af_ap_targets_begin_clear(uint32_t slot,uint64_t g){(void)slot;(void)g;return AF_OK;}
int af_ap_targets_begin_export(uint32_t slot,uint64_t g){(void)slot;(void)g;return AF_OK;}
int af_ap_targets_cancel(void){return AF_OK;}
int af_ap_targets_result(void){return AF_EMPTY;}
uint32_t af_ap_targets_stage(void){return 0;}
int af_ap_targets_presented(void){return AF_OK;}
uint32_t af_ap_targets_disabled(void){return 1;}
int af_ap_browser_result(void){return AF_EMPTY;}
uint32_t af_ap_browser_page(void){return 0;}
int af_ap_media_card_available(void){return (int)can_select;}
int af_ap_media_card_select(uint32_t slot){++route_calls;selected_slot=slot;return route_fault?AF_BUSY:AF_OK;}
int af_ap_media_prepare(void){++scans;return scan_fault?AF_IO:AF_OK;}
int af_ap_media_finish(void){return AF_MANAGE_NOT_READY;}
int af_ap_media_result(void){return AF_MANAGE_NOT_READY;}
int af_ap_media_import_request(AfApManageRequest *p){(void)p;return AF_MANAGE_NOT_READY;}
int af_ap_media_cancel(void){++cleanup;return AF_OK;}
int af_ap_manage_menu_notice(uint32_t op,int result){assert(op==AF_MANAGE_IMPORT);notice=result;return AF_OK;}
'''

MAIN=r'''
int main(int argc,char **argv){
 assert(argc==2);prepare();af_catalog_init(&af_ap_catalog);memset(&af_ap_manager,0,sizeof(af_ap_manager));
 AfPreset preset={0};preset.params[6]=3;assert(!af_install(&af_ap_catalog,7,&preset,0));AfCatalog before=af_ap_catalog;
 can_select=strcmp(argv[1],"fd")!=0;route_fault=!strcmp(argv[1],"busy");scan_fault=!strcmp(argv[1],"read-failure");
 uint8_t owner[0x3c0]={0};Word controller=ap_address(0x58da458);putptr(owner,ap_address(0x58d2fb8));put32(owner+0x3b8,0x2ed);
 group=AF_MANAGE_MENU_ROOT;shown=AF_MANAGE_MENU_IMPORT;
 assert(!af_ap_manage_ui_open(&af_ap_catalog,AF_MANAGE_IMPORT,0)&&!scans&&!route_calls&&!opens);
 shown=0x2b36;assert(ui_manage_poll(owner)==1&&opens==1);
 if(!can_select){assert(opened_root==AF_BROWSER_MENU_ROOT&&scans==1&&!route_calls&&!native.generation);return 0;}
 assert(opened_root==AF_CARDS_MENU_ROOT&&!scans&&!route_calls);
 put32(owner+0x3b8,0xd4);shown=AF_CARDS_MENU_CANCEL;assert(ui_manage_poll(owner)==1&&manage_ui_stage==3);
 if(!strcmp(argv[1],"wrong-parent")){
  group=0x1e6;shown=0x2b36;put32(owner+0x3b8,0x2ed);
  assert(ui_manage_poll(owner)==1&&notice==AF_STALE&&manage_ui_stage==0&&!route_calls&&!scans);return 0;
 }
 if(!strcmp(argv[1],"cancel"))shown=AF_CARDS_MENU_CANCEL;else shown=AF_CARDS_MENU_SLOT1;
 int direction=0,enter=1;
 assert(af_ap_confirm(&controller,&direction)==1&&af_ap_cards_result()==AF_EMPTY&&!route_calls&&!scans);
 assert(af_ap_confirm(&controller,&enter)==1&&!route_calls&&!scans);
 if(!strcmp(argv[1],"disabled"))enabled=0;
 if(!enabled){
  assert(ui_manage_poll(owner)==1&&notice==AF_STALE&&!manage_ui_stage&&!route_calls&&!scans);return 0;
 }
 assert(ui_manage_poll(owner)==0&&!route_calls&&!scans); /* 等原Main返回，不能在关闭栈内读取。 */
 shown=0x2b36;put32(owner+0x3b8,0x2ed);assert(ui_manage_poll(owner)==1);
 if(!strcmp(argv[1],"cancel"))assert(notice==AF_MANAGE_CANCEL&&!route_calls&&!scans&&opened_root==AF_MANAGE_MENU_ROOT);
 else if(route_fault)assert(notice==AF_BUSY&&route_calls==1&&!scans&&opened_root==AF_MANAGE_MENU_ROOT);
 else if(scan_fault)assert(notice==AF_IO&&route_calls==1&&scans==1&&opened_root==AF_MANAGE_MENU_ROOT);
 else assert(!notice&&route_calls==1&&selected_slot==1&&scans==1&&opened_root==AF_BROWSER_MENU_ROOT);
 assert(!af_ap_manager.job.ticket&&af_ap_manager.phase==AF_MANAGE_IDLE);
 assert(!memcmp(&before,&af_ap_catalog,sizeof(before)));return 0;
}
'''

def function(text,signature):
    start=text.index(signature);at=text.index('{',start);depth=1;end=at+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]+'\n'

@pytest.fixture(scope='module')
def flow(tmp_path_factory):
    folder=tmp_path_factory.mktemp('card-flow');source=folder/'flow.c';binary=folder/'flow'
    card=(NATIVE/'af_ap_cards.c').read_text().replace(
        'static uintptr_t va(uintptr_t off) {return native.base+off;}',
        'static uintptr_t test_va(uintptr_t off);\nstatic uintptr_t va(uintptr_t off) {return test_va(off);}')
    common=CARDS.split('static void selection(')[0].replace('#include "af_ap_cards.c"',card)
    ui=(NATIVE/'af_ap_ui.c').read_text()
    selected=''.join(function(ui,s) for s in ('uint32_t af_ap_confirm(', 'void af_ap_confirm_close(',
        'int af_ap_manage_ui_open(', 'static uint32_t ui_model(', 'static int ui_main(',
        'static void ui_manage_failed(', 'static int ui_manage_poll('))
    source.write_text(common+PREFIX+selected+MAIN)
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
        '-I'+str(NATIVE),str(source),str(NATIVE/'af_slots.c'),'-o',str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    return binary

@pytest.mark.parametrize('case',['selected','cancel','busy','read-failure','wrong-parent','disabled','fd'])
def test_original_confirm_and_main_lifecycle_controls_card_then_file_scan(flow,case):
    run=subprocess.run([str(flow),case],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
