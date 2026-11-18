"""旧六只在真实二次确认后成为overlay；没有原生数据的自动迁移。"""
import subprocess
import pytest
from test_ap_targets_overwrite import HARNESS
from test_ap_export_menu import compile_case

EXTRA=r'''
static void explicit_overlay(void){
 for(unsigned op=AF_TARGETS_COPY;op<=AF_TARGETS_CREATE;++op)for(unsigned slot=1;slot<=6;++slot){
  prepare();AfCatalog original=catalog;
  assert(af_ap_targets_begin(op,op==AF_TARGETS_COPY?7:0,1)==AF_OK);
  assert(af_ap_targets_available(menu(slot)));
  assert(af_ap_targets_current()!=af_ap_targets_name(menu(slot))); /* 不默认选原生槽。 */
  shown=menu(slot);af_ap_targets_action(shown);assert(!calls&&!catalog.slots[slot-1].present);
  choose(menu(slot));assert(!calls&&af_ap_targets_stage()==AF_TARGETS_CONFIRM_WAIT);
  assert(af_ap_targets_current()==af_ap_targets_name(AF_TARGETS_CANCEL));
  assert(af_ap_targets_intent(menu(slot))==AF_BUSY);
  choose(AF_TARGETS_CANCEL);assert(!calls&&!memcmp(&catalog,&original,sizeof original));
  assert(af_ap_targets_begin(op,op==AF_TARGETS_COPY?7:0,2)==AF_OK);
  choose(menu(slot));presented();choose(menu(slot));
  assert(calls==1&&received.op==op&&received.target_slot==slot&&received.overwrite==1);
  assert(!received.target.present&&!received.target.revision); /* 没有用seed伪造旧槽副本。 */
  assert(!memcmp(&catalog,&original,sizeof original));
 }
}
static void stale_overlay_and_clear(void){
 prepare();assert(af_ap_targets_begin(AF_TARGETS_IMPORT,0,1)==AF_OK);
 choose(menu(1));presented();AfPreset p={0};p.params[6]=3;
 assert(af_install(&catalog,1,&p,0)==AF_OK);choose(menu(1));assert(!calls&&af_ap_targets_result()==AF_STALE);
 assert(af_ap_targets_cancel()==AF_OK);
 assert(af_ap_targets_begin_clear(1,2)==AF_OK&&!af_ap_targets_available(menu(1)));
 assert(af_ap_targets_cancel()==AF_OK);
 assert(af_ap_targets_begin_clear(7,3)==AF_OK&&af_ap_targets_available(menu(1))&&!af_ap_targets_available(menu(6)));
 choose(menu(1));assert(!calls);presented();choose(menu(1));
 assert(calls==1&&received.op==AF_TARGETS_CLEAR&&received.target.present&&received.overwrite);
 assert(af_ap_targets_begin_export(6,4)==AF_EMPTY);
 assert(af_ap_targets_begin_export(1,4)==AF_OK);presented();choose(menu(1));
 assert(calls==2&&received.op==AF_TARGETS_EXPORT&&!received.overwrite&&received.target.present);
}
int main(int argc,char **argv){assert(argc==2);if(argv[1][0]=='e')explicit_overlay();else stale_overlay_and_clear();}
'''

@pytest.mark.parametrize('case',['explicit','stale-clear'])
def test_original_slots_only_gain_overlay_after_explicit_confirm(tmp_path,case):
    source=HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA
    binary=compile_case(tmp_path,'af_ap_targets',source,
        'static uintptr_t va(uintptr_t off) {return native.base+off;}')
    result=subprocess.run([str(binary),case],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
