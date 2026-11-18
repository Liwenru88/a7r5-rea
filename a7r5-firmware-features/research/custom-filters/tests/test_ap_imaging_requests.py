"""原UI事件到完整参数研究发送；不模拟硬件或宣称照片已生效。"""
from pathlib import Path
import subprocess

NATIVE = Path(__file__).resolve().parents[1]/'native'


def test_user_edits_and_factory_return_send_complete_snapshots(tmp_path):
    body = (NATIVE/'af_ap_ui.c').read_text()
    resolver = 'static Word ap_address(Word offset) { return ap_base + offset; }'
    assert body.count(resolver) == 1
    body = body.replace(resolver, 'static Word address_for_test(Word);\nstatic Word ap_address(Word offset) {return address_for_test(offset);}')
    source = tmp_path/'requests.c'
    source.write_text(body+r'''
#include <assert.h>
#include <string.h>
static uint32_t shown=AF_UI_NEW_FIRST,native_selected,mode,caps=0x31fff;
static unsigned calls,stock_calls,factory_reads,releases;static int send_error;
static AfPreset sent[16];static uint32_t slots[16];
static uint32_t ordinary(void){return 0;}
static const uint32_t *current(void){return &shown;}
static const uint32_t *current_native(void){return &native_selected;}
static const uint32_t *photo_mode(void){return &mode;}
static Word address_for_test(Word off){
 if(off==0x28a87e8)return (Word)current;if(off==0x28ae4b0)return (Word)current_native;
 if(off==0x17ffd84)return (Word)ordinary;if(off==0x28bfdcc)return (Word)photo_mode;
 assert(0);return 0;
}
void af_stock_select(uint32_t selector){++stock_calls;native_selected=selector;}
void af_stock_preview(void *context,uint32_t selector){(void)context;af_stock_select(selector);}
void af_stock_preview_menu(uint32_t menu){(void)menu;++stock_calls;}
static uint32_t capabilities(void *context){assert(context==&calls);return caps;}
static int send_request(void *context,uint32_t slot,const AfPreset *preset){
 assert(context==&calls);slots[calls]=slot;sent[calls++]=*preset;return send_error;
}
static int factory(void *context,uint32_t selector,AfPreset *out){
 assert(context==&calls);++factory_reads;
 if(!(selector<=9||selector==17||selector==18))return AF_INVALID;
 *out=(AfPreset){.base=(uint8_t)selector,.params={-3,4,-5,2,6,7,4,8}};return AF_OK;
}
static int release_request(void *context){assert(context==&calls);++releases;return send_error;}
int main(void){
 prepared=enabled=1;af_catalog_init(&af_ap_catalog);AfPreset preset={0};preset.params[6]=3;
 assert(af_install(&af_ap_catalog,7,&preset,0)==0);
 af_ap_select(19);assert(!calls&&selected_valid);selected_valid=0;
 AfApImagingBinding binding={AF_AP_IMAGING_VERSION,sizeof(binding),&calls,capabilities,send_request,factory,release_request};
 caps=0x1fff;assert(af_ap_imaging_bind(&binding)==AF_BUSY);
 caps=0x11fff;assert(af_ap_imaging_bind(&binding)==AF_BUSY);caps=0x31fff;
 assert(af_ap_imaging_bind(&binding)==0&&af_ap_imaging_bind(&binding)==AF_BUSY);
 af_ap_select(19);assert(calls==1&&slots[0]==7&&sent[0].params[6]==3&&native_selected==0&&!stock_calls);
 assert(af_ap_imaging_result()==0);
 unsigned reads=factory_reads;
 /* 明确的合法参数变化发整组，边界不变化则不重发。 */
 layout_allowed=1;display_menu=shown;
 step(0,0,0,0);assert(calls==2&&sent[1].params[0]==1&&sent[1].params[6]==3);
 af_ap_catalog.slots[6].working.params[0]=9;step(0,0,0,0);assert(calls==2);
 assert(factory_reads==reads);
 shown=0x852;af_ap_select(17);
 assert(calls==3&&slots[2]==0&&sent[2].base==17&&stock_calls==1&&native_selected==17);
 assert(!memcmp(sent[2].params,(int8_t[]){-3,4,-5,2,6,7,4,8},8));
 /* 前一次factory可能仍pending；下一原厂事件必须更新整组，不能丢在旧base。 */
 shown=0x853;af_ap_select(18);assert(stock_calls==2&&calls==4&&slots[3]==0&&sent[3].base==18);
 shown=AF_UI_NEW_FIRST;send_error=AF_IO;af_ap_select(19);
 assert(calls==5&&af_ap_imaging_result()==AF_IO);
 /* 错误后不自动轮询重发；新明确事件才产生下一次请求。 */
 unsigned old=calls;request_refresh(shown);assert(calls==old);
 shown=0x853;send_error=0;af_ap_select(18);assert(calls==6&&slots[5]==0&&sent[5].base==18);
 shown=AF_UI_NEW_FIRST;caps=0x1fff;af_ap_select(19);assert(calls==6&&af_ap_imaging_result()==AF_BUSY);
 caps=0x31fff;af_ap_select(19);assert(calls==7);
 /* 明确选择事件在受限模式退出覆盖，不再留下私有值影响原厂。 */
 mode=1;shown=0x852;af_ap_select(17);assert(calls==7&&releases==1&&af_ap_imaging_result()==0);
 mode=0;af_ap_select(17);assert(calls==7);
 shown=AF_UI_NEW_FIRST;af_ap_select(19);shown=0x852;af_ap_select(17);
 assert(calls==9&&slots[8]==0&&sent[8].base==17);
 /* 从旧六槽进入/退出不丢其网格；只发NATIVE，不假造纯参数。 */
 shown=AF_UI_NEW_FIRST;native_selected=10;af_ap_select(19);assert(calls==10);
 shown=0x858;af_ap_select(10);assert(calls==10&&releases==2&&native_selected==10);
 shown=AF_UI_NEW_FIRST;native_selected=16;af_ap_select(19);
 assert(calls==10&&af_ap_imaging_result()==AF_STALE);
 return 0;
}
''')
    binary = tmp_path/'requests'
    build = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-ffunction-sections', '-fdata-sections', '-Wl,-dead_strip', '-I'+str(NATIVE), str(source),
                            str(NATIVE/'af_slots.c'), str(NATIVE/'af_ui.c'), '-o', str(binary)], capture_output=True, text=True)
    assert build.returncode == 0, build.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_runtime_bundle_preserves_factory_identity_and_refuses_unready_peer(tmp_path):
    source = tmp_path/'bundle.c'
    source.write_text(r'''
#include "af_imaging406.h"
#include "af_apply.h"
#include <assert.h>
#include <string.h>
static uint32_t caps,seen_slot,seen_selector;static uintptr_t seen_base;
uint32_t af_ap_runtime_preset_capabilities(void){return caps;}
int af_ap_runtime_send_preset(uint32_t slot,const AfPreset *p){seen_slot=slot;return p->base==18?AF_OK:AF_STALE;}
int af_ap_runtime_release_preset(void){seen_slot=99;return AF_OK;}
int af_ap_factory406_snapshot(uintptr_t base,uint32_t selector,AfPreset *out){
 seen_base=base;seen_selector=selector;*out=(AfPreset){.base=(uint8_t)selector,.params={-3,4,-5,2,6,7,4,8}};return AF_OK;
}
int main(void){
 AfApImagingBinding b,before;memset(&b,0xa5,sizeof b);before=b;
 assert(af_imaging406_binding(0x7000000000u,&b)==AF_BUSY&&!memcmp(&b,&before,sizeof b));
 caps=AF_APPLY_ALL;assert(af_imaging406_binding(0x7000000000u,&b)==AF_BUSY);
 caps|=AF_APPLY_CAP_FACTORY_RESTORE;
 assert(af_imaging406_binding(0x7000000000u,&b)==AF_BUSY);
 caps|=AF_APPLY_CAP_SNAPSHOT_OVERLAY;
 assert(af_imaging406_binding(0x7000000001u,&b)==AF_INVALID);
 assert(af_imaging406_binding(0x7000000000u,(void *)0x7000000010u)==AF_INVALID);
 assert(af_imaging406_binding(0x7000000000u,&b)==0&&b.capabilities(b.context)==caps);
 AfPreset p;assert(b.factory(b.context,18,&p)==0&&seen_base==0x7000000000u&&seen_selector==18);
 assert(b.send(b.context,0,&p)==0&&seen_slot==0&&p.params[0]==-3);
 assert(b.version==2&&b.release(b.context)==0&&seen_slot==99);
 caps=0;assert(!b.capabilities(b.context));return 0;
}
''')
    binary = tmp_path/'bundle'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                          '-I'+str(NATIVE), str(source), str(NATIVE/'af_imaging406.c'), '-o', str(binary)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_lut_ui_uses_full_callback_and_coalesces_latest_busy_request(tmp_path):
    """真实UI+成像胶合；仅运行时发送/原AP访问边界由宿主替代。"""
    body = (NATIVE/'af_ap_ui.c').read_text()
    resolver = 'static Word ap_address(Word offset) { return ap_base + offset; }'
    assert body.count(resolver) == 1
    body = body.replace(resolver, 'static Word address_for_test(Word);\nstatic Word ap_address(Word offset) {return address_for_test(offset);}')
    source = tmp_path/'full-requests.c'
    source.write_text(body+r'''
#include "af_imaging406.h"
#include "af_runtime_ap406.h"
#include <assert.h>
#include <string.h>
static uint32_t shown=AF_UI_NEW_FIRST,native_selected,mode,caps;
static unsigned full_attempts,full_accepted,pure_attempts,releases,captures,base_cycles;
static int send_error,reenter;
static AfPreset last_full,last_pure;static uint32_t last_slot;
static uint32_t ordinary(void){return 0;}
static const uint32_t *current(void){return &shown;}
static const uint32_t *current_native(void){return &native_selected;}
static const uint32_t *photo_mode(void){return &mode;}
static uint32_t focus(void *object){(void)object;return 0;}
int af_ap_runtime_native_only_capable(void){return 0;}
static Word address_for_test(Word off){
 if(off==0x28a87e8)return (Word)current;if(off==0x28ae4b0)return (Word)current_native;
 if(off==0x17ffd84)return (Word)ordinary;if(off==0x28bfdcc)return (Word)photo_mode;
 if(off==0x220b4e0)return (Word)focus;return ap_base+off;
}
void af_stock_select(uint32_t selector){native_selected=selector;}
void af_stock_preview(void *context,uint32_t selector){(void)context;af_stock_select(selector);}
void af_stock_base_cycle(void *object,uint32_t direction){(void)object;(void)direction;++base_cycles;}
Word af_stock_base_available(void){assert(0);return 0;}
#define STOCK_STEP(N) void af_stock_step_##N(void *object,uint32_t direction){(void)object;(void)direction;assert(0);}
STOCK_STEP(0) STOCK_STEP(1) STOCK_STEP(2) STOCK_STEP(3) STOCK_STEP(4) STOCK_STEP(5) STOCK_STEP(6) STOCK_STEP(7)
uint32_t af_ap_runtime_preset_capabilities(void){return caps;}
int af_ap_runtime_send_preset(uint32_t slot,const AfPreset *p){
 ++pure_attempts;last_slot=slot;last_pure=*p;assert(!p->kind);return send_error;
}
int af_ap_runtime_release_preset(void){++releases;return send_error;}
int af_ap_factory406_snapshot(uintptr_t base,uint32_t selector,AfPreset *out){
 assert(base==0x70000000 && (selector<=9 || selector==17 || selector==18));
 *out=(AfPreset){.base=(uint8_t)selector,.params={-3,4,-5,2,6,7,4,8}};return AF_OK;
}
static int capture(void *context,uint32_t slot,const AfPreset *p,uint64_t session,uint64_t version,AfRecipeTx *out){
 assert(context==&captures && (slot==7 || slot==1) && session==1 && version==full_accepted+1 && out);
 ++captures;assert(p->kind==1);return AF_OK;
}
int af_ap_runtime_send_stored_recipe(uint32_t slot,const AfPreset *p,AfApRecipeCapture406 get,void *context,uint32_t timeout){
 ++full_attempts;last_slot=slot;last_full=*p;assert(timeout==2000 && p->kind==1);
 /* 已接受事务尚未结束：真实后端在BUSY时不捕获下一资产。 */
 if(reenter){reenter=0;assert(af_edit(&af_ap_catalog,7,0,6)==AF_OK);imaging_user(7);return AF_BUSY;}
 if(send_error)return send_error;
 AfRecipeTx tx;assert(get(context,slot,p,1,full_accepted+1,&tx)==AF_OK);++full_accepted;return AF_OK;
}
static void pump(void){Word manager[1]={ap_address(0x58d2fb8)};imaging_pending_poll(manager);}
static AfPreset lut(void){
 AfPreset p={.base=17,.kind=1,.params={0,0,0,0,0,0,3,0}};
 p.payload_sha256[0]=7;p.lut_sha256[0]=9;return p;
}
int main(void){
 prepared=enabled=1;ap_base=0x70000000;af_catalog_init(&af_ap_catalog);
 AfPreset p=lut();assert(af_install(&af_ap_catalog,7,&p,0)==0);
 caps=AF_AP_IMAGING_REQUIRED|AF_AP_IMAGING_FULL_RECIPE;
 AfImaging406RecipeSource library={AF_IMAGING406_RECIPE_SOURCE_VERSION,sizeof(library),&captures,capture};
 assert(af_imaging406_bind_recipe_source(&library)==0);
 AfApImagingBinding b;assert(af_imaging406_binding(ap_base,&b)==0 && af_ap_imaging_bind(&b)==0);
 /* FULL能力缺失拒绝kind1；选择后无自动重发，仍可明确重选。 */
 caps&=~AF_AP_IMAGING_FULL_RECIPE;af_ap_select(19);
 assert(!full_attempts && af_ap_imaging_result()==AF_MANAGE_NOT_READY && !imaging.pending.kind);
 caps|=AF_AP_IMAGING_FULL_RECIPE;pump();assert(!full_attempts);
 af_ap_select(19);assert(full_attempts==1 && full_accepted==1 && captures==1 && last_slot==7);
 assert(imaging_same(&p,&last_full) && !pure_attempts);
 /* 八个原编辑入口发完整同资产快照，不改LUT摘要、基底或initial/saved。 */
 layout_allowed=1;display_menu=shown;
 void (*edits[8])(void *,uint32_t)={af_ap_step_0,af_ap_step_1,af_ap_step_2,af_ap_step_3,
  af_ap_step_4,af_ap_step_5,af_ap_step_6,af_ap_step_7};
 for(unsigned i=0;i<8;++i){
  edits[i](0,0);p.params[i]++;assert(full_accepted==i+2 && imaging_same(&p,&last_full));
 }
 assert(full_attempts==9 && captures==9 && !pure_attempts);
 assert(imaging_same(&af_ap_catalog.slots[6].saved,&(AfPreset){.base=17,.kind=1,
  .params={0,0,0,0,0,0,3,0},.payload_sha256={7},.lut_sha256={9}}));
 /* LUT基底仍不可编辑；只有八项路由开放。 */
 assert(!af_ap_base_available());assert(af_edit_base(&af_ap_catalog,7,18)==AF_INVALID);
 /* 忙时只留最新值；一轮刷新只调用一次，成功后不再重发。 */
 send_error=AF_BUSY;af_ap_step_0(0,0);af_ap_step_0(0,0);af_ap_step_1(0,0);
 unsigned attempts=full_attempts;assert(imaging.pending.kind && af_ap_imaging_result()==AF_BUSY);
 pump();assert(full_attempts==attempts+1 && imaging.pending.kind);
 send_error=0;pump();assert(full_attempts==attempts+2 && !imaging.pending.kind);
 assert(imaging_same(&last_full,&af_ap_catalog.slots[6].working));
 attempts=full_attempts;pump();assert(full_attempts==attempts);
 /* Save只变已保存代号，不能吞掉忙期间最后工作编辑。 */
 send_error=AF_BUSY;af_ap_step_0(0,0);attempts=full_attempts;
 AfSave save;assert(af_begin_save(&af_ap_catalog,7,&save)==AF_OK);
 assert(af_finish_save(&af_ap_catalog,&save,1)==AF_OK);
 send_error=0;pump();assert(full_attempts==attempts+1 && !imaging.pending.kind);
 assert(imaging_same(&last_full,&af_ap_catalog.slots[6].working));
 /* 重入出现的新请求不能被外层旧BUSY覆盖。 */
 reenter=1;imaging_user(7);assert(imaging.pending.kind && imaging.pending.preset.params[0]==6);
 pump();assert(!imaging.pending.kind && last_full.params[0]==6);
 /* IO等终止错误无自动重发；新明确事件才可再发送。 */
 send_error=AF_IO;af_ap_step_2(0,0);attempts=full_attempts;send_error=0;pump();
 assert(full_attempts==attempts && af_ap_imaging_result()==AF_IO);
 /* 待发槽被替换/清除或工作值未对应新事件时，旧快照拒绝。 */
 send_error=AF_BUSY;imaging_user(7);attempts=full_attempts;
 assert(af_edit(&af_ap_catalog,7,2,4)==0);send_error=0;pump();
 assert(full_attempts==attempts && af_ap_imaging_result()==AF_STALE);
 send_error=AF_BUSY;imaging_user(7);attempts=full_attempts;
 assert(af_install(&af_ap_catalog,7,&p,1)==0);send_error=0;pump();
 assert(full_attempts==attempts && af_ap_imaging_result()==AF_STALE);
 send_error=AF_BUSY;imaging_user(7);attempts=full_attempts;af_ap_catalog.slots[6].present=0;
 send_error=0;pump();assert(full_attempts==attempts && af_ap_imaging_result()==AF_STALE);
 assert(af_install(&af_ap_catalog,7,&p,1)==0);
 /* 后来的FL2/FL3或旧六原路径覆盖滞留USER，不能轮询后重新装LUT。 */
 send_error=AF_BUSY;af_ap_select(19);shown=0x852;af_ap_select(17);
 assert(imaging.pending.kind==2 && last_pure.base==17);shown=0x853;af_ap_select(18);
 assert(imaging.pending.kind==2);attempts=full_attempts;send_error=0;pump();
 assert(full_attempts==attempts && last_slot==0 && last_pure.base==18 && !imaging.pending.kind);
 shown=AF_UI_NEW_FIRST;send_error=AF_BUSY;af_ap_select(19);
 shown=0x858;af_ap_select(10);assert(imaging.pending.kind==3);
 attempts=full_attempts;send_error=0;pump();
 assert(full_attempts==attempts && !imaging.pending.kind && !imaging.requested && releases==2);
 /* 正确UI拥有者之外不推进待发；能力撤销后不降级到纯参数。 */
 shown=AF_UI_NEW_FIRST;send_error=AF_BUSY;af_ap_select(19);attempts=full_attempts;
 Word wrong[1]={0};imaging_pending_poll(wrong);assert(full_attempts==attempts);
 caps&=~AF_AP_IMAGING_FULL_RECIPE;send_error=0;pump();
 assert(full_attempts==attempts && !imaging.pending.kind && af_ap_imaging_result()==AF_MANAGE_NOT_READY);
 /* C01有独立持久化overlay后，必须额外协商USER20；旧FULL对端不接收。 */
 caps|=AF_AP_IMAGING_FULL_RECIPE;p=lut();assert(af_install(&af_ap_catalog,1,&p,0)==0);
 shown=0x858;af_ap_select(10);assert(full_attempts==attempts && af_ap_imaging_result()==AF_MANAGE_NOT_READY);
 caps|=AF_AP_IMAGING_USER20;af_ap_select(10);
 assert(full_attempts==attempts+1 && last_slot==1 && imaging_same(&last_full,&p));
 assert(!base_cycles);return 0;
}
''')
    binary = tmp_path/'full-requests'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                          '-DAF_RECIPE_BRIDGE406=1', '-ffunction-sections', '-fdata-sections',
                          '-Wl,-dead_strip', '-I'+str(NATIVE), str(source), str(NATIVE/'af_imaging406.c'),
                          str(NATIVE/'af_slots.c'), str(NATIVE/'af_ui.c'), '-o', str(binary)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
