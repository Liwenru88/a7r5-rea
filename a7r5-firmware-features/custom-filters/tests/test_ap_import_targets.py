"""导入目标的原D4确认：允许完整LUT覆盖，保持原厂和其它动作保护。"""
import subprocess

from test_ap_export_menu import compile_case
from test_ap_targets import HARNESS


EXTRA = r'''
int main(void){
 prepare();AfPreset lut={0};lut.kind=1;lut.params[6]=3;
 lut.payload_sha256[0]=1;lut.lut_sha256[0]=2;
 assert(af_install(&catalog,20,&lut,0)==0);AfCatalog before=catalog;
 assert(af_ap_targets_begin(AF_TARGETS_IMPORT,0,1)==0);
 assert(!strcmp(af_ap_targets_text(AF_TARGETS_TEXT_FIRST),"Import LUT: target"));
 assert(af_ap_targets_available(menu(1))&&af_ap_targets_available(menu(7))&&af_ap_targets_available(menu(20)));
 choose(menu(20));assert(!calls&&af_ap_targets_stage()==AF_TARGETS_CONFIRM_WAIT);
 assert(af_ap_targets_result()==AF_TARGETS_CONFIRM_REQUIRED);
 shown=AF_TARGETS_CANCEL;assert(af_ap_targets_presented()==0);
 assert(af_ap_targets_current()==af_ap_targets_name(AF_TARGETS_CANCEL));
 choose(menu(20));assert(calls==1&&received.op==3&&received.target_slot==20&&received.overwrite==1);
 assert(received.target.initial.kind==1&&received.target.saved.kind==1&&received.target.working.kind==1);
 assert(!memcmp(&before,&catalog,sizeof(catalog)));
 assert(af_ap_targets_begin(AF_TARGETS_CREATE,0,2)==0&&!af_ap_targets_available(menu(20)));
 assert(af_ap_targets_cancel()==0);
 catalog.slots[19].working.lut_sha256[0]=3;
 assert(af_ap_targets_begin(AF_TARGETS_IMPORT,0,3)==0&&!af_ap_targets_available(menu(20)));
 choose(menu(20));assert(calls==1&&af_ap_targets_result()!=0);return 0;
}
'''


def test_import_only_permits_consistent_lut_target_and_requires_confirmation(tmp_path):
    source = HARNESS.split('int main(int argc,char **argv)')[0] + EXTRA
    binary = compile_case(tmp_path, 'af_ap_targets', source,
                          'static uintptr_t va(uintptr_t off) {return native.base+off;}')
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
