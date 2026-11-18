"""有效LUT的菜单动作与快照保护；只运行宿主C，不运行模拟器。"""
import subprocess

from test_ap_export_menu import compile_case
from test_ap_targets import HARNESS, NATIVE


EXTRA = r'''
static void present_confirmation(void){shown=AF_TARGETS_CANCEL;assert(af_ap_targets_presented()==0);}
int main(void){
 prepare();AfPreset lut={0};lut.kind=1;lut.base=18;lut.params[6]=3;
 lut.payload_sha256[0]=1;lut.lut_sha256[0]=2;
 assert(af_install(&catalog,7,&lut,1)==0&&af_install(&catalog,20,&lut,0)==0);
 assert(af_edit(&catalog,7,0,4)==0);AfCatalog before=catalog;
 assert(af_ap_targets_begin(AF_TARGETS_COPY,7,1)==0);
 assert(af_ap_targets_available(menu(1))&&!af_ap_targets_available(menu(7))&&af_ap_targets_available(menu(20)));
 choose(menu(20));assert(!calls&&af_ap_targets_result()==AF_TARGETS_CONFIRM_REQUIRED);
 present_confirmation();choose(menu(20));
 assert(calls==1&&received.op==AF_MANAGE_COPY&&received.overwrite&&received.source.initial.kind==1&&received.target.initial.kind==1);
 assert(received.source.working.params[0]==4&&received.source.saved.params[0]==0);
 assert(af_ap_targets_begin_clear(7,2)==0&&!af_ap_targets_available(menu(7))&&af_ap_targets_available(menu(20)));
 choose(menu(20));present_confirmation();choose(menu(20));
 assert(calls==2&&received.op==AF_MANAGE_CLEAR&&received.target.initial.kind==1);
 assert(af_ap_targets_begin_export(7,3)==0&&af_ap_targets_stage()==AF_TARGETS_CONFIRM_WAIT);
 present_confirmation();choose(menu(7));
 assert(calls==3&&received.op==AF_MANAGE_EXPORT&&!received.overwrite&&received.source.saved.kind==1);
 assert(!memcmp(&before,&catalog,sizeof(catalog)));
 catalog.slots[6].working.payload_sha256[0]^=1;
 assert(af_ap_targets_begin(AF_TARGETS_COPY,7,4)==AF_INVALID);
 assert(af_ap_targets_begin_export(7,4)==AF_INVALID);return 0;
}
'''


def test_lut_management_requires_consistent_source_and_confirmed_target(tmp_path):
    source = HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA
    binary = compile_case(tmp_path, 'af_ap_targets', source,
                          'static uintptr_t va(uintptr_t off) {return native.base+off;}')
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr


def test_lut_rename_entry_keeps_complete_snapshot_and_detects_edits(tmp_path):
    source = tmp_path/'rename.c'
    source.write_text(r'''
#include "af_ap_ui.c"
#include <assert.h>
#include <string.h>
int main(void){
 af_catalog_init(&af_ap_catalog);af_labels_init(&af_ap_labels);
 AfPreset lut={0};lut.kind=1;lut.base=18;lut.params[6]=3;lut.payload_sha256[0]=1;lut.lut_sha256[0]=2;
 assert(af_install(&af_ap_catalog,7,&lut,0)==0&&af_edit(&af_ap_catalog,7,0,4)==0);
 assert(af_labels_publish(&af_ap_labels,7,1,"Film",4)==0);
 AfCatalog before=af_ap_catalog;
 assert(rename_begin(7)==0&&rename_unchanged()&&rename_ui.snapshot.initial.kind==1);
 assert(!memcmp(&before,&af_ap_catalog,sizeof(before)));
 assert(af_edit(&af_ap_catalog,7,0,3)==0&&!rename_unchanged());
 return 0;
}
''')
    binary = tmp_path/'rename'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                          '-ffunction-sections', '-fdata-sections', '-Wl,-dead_strip', '-I'+str(NATIVE),
                          str(source), str(NATIVE/'af_slots.c'), str(NATIVE/'af_labels.c'), '-o', str(binary)],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
