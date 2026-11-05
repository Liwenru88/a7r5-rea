"""实际loader能力声明必须把导入/导出送入既有选择页，不能被静默吞掉。"""
from pathlib import Path
import re
import subprocess
import pytest
from test_ap_export_menu import compile_case
from test_ap_menu_intent import HARNESS,NATIVE

LOADER=NATIVE.parent/'experiments/packaging406/loader/af_bootstrap406.c'

@pytest.mark.parametrize('op',[3,7])
def test_published_picker_routes_import_and_export_without_enqueuing(tmp_path,op):
    text=LOADER.read_text()
    declaration=re.search(r'AfApManagePicker picker=\{[^\n]+;',text).group(0)
    main=r'''
int main(void){
 prepare();native.service.capabilities|=AF_MANAGE_CAP(AF_MANAGE_EXPORT);
 AfApManage before=manager;shown=af_ap_manage_menu_for_op(OP);
 AfCatalog *bound_catalog=native.catalog;
 {AfCatalog *catalog=bound_catalog;
 #define UF(name,type) ((type)open_picker)
 DECLARATION
 native.picker=(AfApManagePicker){0};assert(af_ap_manage_picker_bind(&picker)==AF_OK);
 }
 af_ap_manage_menu_action(shown);assert(!opens);
 assert(af_ap_manage_menu_intent(shown)==AF_OK);af_ap_manage_menu_action(shown);
 assert(opens==1&&last_op==OP&&last_source==0);
 assert(!memcmp(&before,&manager,sizeof(before)));return 0;
}
'''.replace('DECLARATION',declaration).replace('OP',str(op))
    source=HARNESS.split('int main(int argc,char **argv)')[0]+main
    binary=compile_case(tmp_path,'af_ap_manage',source,
        'static uintptr_t va(uintptr_t offset) { return native.base+offset; }')
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
