"""C01～C06独立overlay的UI确认；只执行宿主C，原AP/任务队列为显式边界。"""
from pathlib import Path
import subprocess

NATIVE = Path(__file__).resolve().parents[1]/'native'


def test_overlay_ui_requires_explicit_choice_and_keeps_snapshot_guards(tmp_path):
    body = (NATIVE/'af_ap_ui.c').read_text()
    resolver = 'static Word ap_address(Word offset) { return ap_base + offset; }'
    assert body.count(resolver) == 1
    body = body.replace(resolver, 'static Word address_for_test(Word);\nstatic Word ap_address(Word offset) {return address_for_test(offset);}')
    source = tmp_path/'overlay.c'
    source.write_text(body+r'''
#include <assert.h>
#include <string.h>
static uint32_t selector,mode,language=25;
static unsigned submitted,taken,finished;
static AfApManageRequest sent;
static uint32_t ordinary(void){return 0;}
static uint32_t native_selector(void){return selector;}
static const uint32_t *native_current(void){return &selector;}
static const uint32_t *photo_mode(void){return &mode;}
static const uint32_t *current_language(void){return &language;}
static Word address_for_test(Word off){
 if(off==0x17ffd84)return (Word)ordinary;if(off==0x28bfdcc)return (Word)photo_mode;
 if(off==0x28ae4b0)return (Word)native_current;if(off==0x28b0464)return (Word)current_language;
 assert(0);return 0;
}
int af_ap_media_import_request(AfApManageRequest *out){*out=manage_ui_import;return AF_OK;}
int af_ap_manage_submit(AfApManage *m,const AfCatalog *c,const AfApManageRequest *request){
 assert(m==&af_ap_manager && c==&af_ap_catalog);++submitted;sent=*request;return AF_OK;
}
int af_ap_manage_menu_notice(uint32_t op,int result){(void)op;(void)result;return AF_OK;}
int af_ap_manage_take(AfApManage *m,AfApManageJob *job){++taken;*job=m->job;return AF_OK;}
int af_ap_manage_finish(AfApManage *m,const AfCatalog *c,const AfApManageReceipt *receipt){
 assert(m==&af_ap_manager && c==&af_ap_catalog && receipt->result==AF_STALE);++finished;return AF_OK;
}
static AfApManageSlot snapshot(uint32_t slot){
 const AfSlot *s=&af_ap_catalog.slots[slot-1];
 return (AfApManageSlot){.revision=s->saved_revision,.present=s->present,
  .initial=s->initial,.saved=s->saved,.working=s->working};
}
static AfApTargetChoice choice(uint32_t op,uint32_t slot){
 manage_ui_stage=3;manage_ui_root=AF_TARGETS_ROOT;manage_ui_op=op;manage_selection_generation=8;
 AfApTargetChoice c={.version=AF_AP_TARGET_CHOICE_VERSION,.bytes=sizeof(c),.generation=8,
  .op=op,.target_slot=slot,.target=snapshot(slot)};
 return c;
}
int main(void){
 prepared=enabled=1;original_current=(Word)native_selector;
 af_catalog_init(&af_ap_catalog);af_labels_init(&af_ap_labels);
 /* 未overlay原六槽不能改名；明确二次确认才允许新overlay，并不改原模型。 */
 assert(rename_begin(1)==AF_INVALID);
 AfApTargetChoice c=choice(AF_MANAGE_CREATE,1);AfCatalog before=af_ap_catalog;
 assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_INVALID && !submitted);
 c.overwrite=1;assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_OK && submitted==1);
 assert(sent.target_slot==1 && sent.overwrite==1 && !memcmp(&before,&af_ap_catalog,sizeof before));
 c.generation++;assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_STALE && submitted==1);
 /* C07真正空槽仍用overwrite0，不能把所有目标变成确认覆盖。 */
 c=choice(AF_MANAGE_CREATE,7);assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_OK && submitted==2);
 c.overwrite=1;assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_INVALID && submitted==2);
 AfPreset p={.base=18,.params={0,0,0,0,0,0,3,0}};
 assert(af_install(&af_ap_catalog,1,&p,0)==AF_OK);
 assert(af_labels_publish(&af_ap_labels,1,1,"Film",4)==AF_OK);
 assert(rename_begin(1)==AF_OK && rename_unchanged() && rename_ui.slot==1);
 assert(af_edit(&af_ap_catalog,1,0,2)==AF_OK && !rename_unchanged());rename_ui.phase=0;
 /* 已overlay可导出；仍要求实际当前槽和完整工作快照。 */
 selector=10;c=choice(AF_MANAGE_EXPORT,1);c.source_slot=1;c.source=c.target;
 assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_OK && submitted==3);
 c.overwrite=1;assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_INVALID && submitted==3);
 c.overwrite=0;assert(af_edit(&af_ap_catalog,1,1,2)==AF_OK);
 assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_STALE && submitted==3);
 /* 清空仅删除非活动overlay；未overlay原六槽禁止清空。 */
 c=choice(AF_MANAGE_CLEAR,1);c.overwrite=1;
 assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_STALE && submitted==3);
 selector=0;assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)==AF_OK && submitted==4);
 c=choice(AF_MANAGE_CLEAR,2);c.overwrite=1;
 assert(af_ap_manage_ui_chosen(&af_ap_catalog,&c)!=AF_OK && submitted==4);
 /* rename/export排队后的旧六身份也能正确保留；换选后按原流程拒绝。 */
 selector=10;af_ap_manager.phase=AF_MANAGE_QUEUED;af_ap_manager.job.request.op=AF_MANAGE_EXPORT;
 af_ap_manager.job.request.target_slot=1;af_ap_manager.job.target=snapshot(1);af_ap_manager.job.ticket=11;
 ui_clear_before_pump();assert(!taken && !finished);
 selector=0;ui_clear_before_pump();assert(taken==1 && finished==1);
 return 0;
}
''')
    binary = tmp_path/'overlay'
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                             '-ffunction-sections', '-fdata-sections', '-Wl,-dead_strip', '-I'+str(NATIVE),
                             str(source), str(NATIVE/'af_slots.c'), str(NATIVE/'af_ui.c'),
                             str(NATIVE/'af_labels.c'), '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
