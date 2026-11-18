"""启动预装但UI未启用时，原reset不得读取当前菜单或吞掉原调用。"""
from pathlib import Path
import subprocess

NATIVE = Path(__file__).resolve().parents[1] / "native"


def test_disabled_reset_delegates_once_without_reading_menu_model(tmp_path):
    body = (NATIVE / "af_ap_ui.c").read_text()
    resolver = "static Word ap_address(Word offset) { return ap_base + offset; }"
    assert body.count(resolver) == 1
    body = body.replace(resolver, "static Word forbidden_model(Word);\nstatic Word ap_address(Word off){return forbidden_model(off);}")
    body += r'''
#include <assert.h>
static unsigned stock_calls;
static void *last_transaction;
static Word forbidden_model(Word offset){(void)offset;assert(!"禁用reset不能读取尚未就绪的菜单模型");return 0;}
void af_stock_reset(void *transaction){++stock_calls;last_transaction=transaction;}
int main(void){
 unsigned char transaction[8]={0};
 for(unsigned stage=0;stage<2;++stage){
  prepared=stage;enabled=0;af_ap_reset(transaction);
  assert(stock_calls==stage+1&&last_transaction==transaction&&!imaging.requested);
 }
 return 0;
}
'''
    source, binary = tmp_path / "disabled.c", tmp_path / "disabled"
    source.write_text(body)
    built = subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-ffunction-sections", "-fdata-sections", "-Wl,-dead_strip", "-I" + str(NATIVE), str(source),
        str(NATIVE / "af_slots.c"), str(NATIVE / "af_ui.c"), "-o", str(binary)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
