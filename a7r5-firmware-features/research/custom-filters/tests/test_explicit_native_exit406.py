"""真实UI/AP发送/CP入口的明确退出回归；固定地址/原系统与capture为宿主端口。"""
from pathlib import Path
import subprocess

import pytest

from test_cp_native_binding406 import DRIVER, NATIVE, native_binding_driver


EXTRA = r'''
#include "af_imaging406.h"
extern AfRuntime af_ap_runtime;
int af_ap_runtime_poll(void);
extern int af_cp_hs_last_prepare;
static uint64_t now=100;
static unsigned ap_sends,recipe_frames,native_sends,fail_frame,fail_native,stock_selections;
static unsigned char allocated[128];
static uint32_t shown=AF_UI_NEW_FIRST,native_selected,photo_mode;
static uint32_t no_restriction(void){return 0;}
static const uint32_t *menu_for_exit(void){return &shown;}
static const uint32_t *native_for_exit(void){return &native_selected;}
static const uint32_t *mode_for_exit(void){return &photo_mode;}
static Word address_for_exit(Word offset){
 if(offset==0x28a87e8)return (Word)menu_for_exit;
 if(offset==0x28ae4b0)return (Word)native_for_exit;
 if(offset==0x17ffd84)return (Word)no_restriction;
 if(offset==0x28bfdcc)return (Word)mode_for_exit;
 if(offset==0x58d2fb8)return ap_base+offset;
 assert(!"本测试不访问其他原AP地址");return 0;
}
void af_stock_select(uint32_t selector){++stock_selections;native_selected=selector;}
void af_stock_preview(void *context,uint32_t selector){(void)context;af_stock_select(selector);}
int af_ap_factory406_snapshot(uintptr_t base,uint32_t selector,AfPreset *out){
 assert(base==0x70000000u);*out=(AfPreset){.base=(uint8_t)selector,.params={0,0,0,0,0,0,3,0}};return AF_OK;
}
static int monotonic(int clock,void *out){
 int64_t *p=out;assert(clock==1);p[0]=(int64_t)(now/1000);p[1]=(int64_t)(now%1000)*1000000;return 0;
}
void *af_stock_dlsym(void *p,const char *name){assert(!p&&!strcmp(name,"clock_gettime"));return (void *)monotonic;}
int af_stock_open(const char *p,int f,...){(void)p;(void)f;return -1;}
long af_stock_read(int f,void *p,size_t n){(void)f;(void)p;(void)n;return -1;}
int af_stock_close(int f){(void)f;return 0;}
int *af_stock_errno(void){static int e=4;return &e;}
int af_stock_usleep(unsigned n){(void)n;return 0;}
int af_stock_allocate(uint32_t q,void **out,uint32_t bytes,int wait){
 assert(q==0x90030001u&&bytes==128&&!wait);*out=allocated;return 0;
}
void af_stock_source(void *p,uint32_t source){assert(p==allocated&&source==0x80020002u);}
int af_stock_receive(uint32_t q,void **p,int wait){(void)q;(void)wait;*p=0;return -1022;}
int af_stock_send(uint32_t q,void *p){
 assert(q==0x90030001u&&p==allocated);++ap_sends;
 if(!memcmp(p,"A7R1",4)){++recipe_frames;if(recipe_frames==fail_frame)return -5;}
 else{
  AfApplyPacket packet;assert(!af_apply_packet_decode(p,128,&packet));
  assert(packet.operation==AF_APPLY_NATIVE&&packet.version==3&&packet.session==71);
  ++native_sends;if(fail_native)return -7;
 }
 assert(af_cp_hs_receive(p,0x80020002u,128)==1);return 0;
}
static int capture_for_exit(void *image,uint32_t slot,const AfPreset *p,uint64_t session,uint64_t version,AfRecipeTx *out){
 return af_recipe_tx_init(out,session,version,slot,p,image,AF_JOINT_ASSET_BYTES);
}
static void encode_for_exit(unsigned version,unsigned char *image,AfPreset *p){
 AfJointAsset a=make_asset(version);size_t bytes=0;
 assert(!af_joint_asset_encode(&a,image,AF_JOINT_ASSET_BYTES,&bytes));*p=make_preset(image,bytes);
}
static void connect_for_exit(void){
 setup();assert(!af_cp_hs_start_once());
 af_ap_runtime.attempted=1;af_ap_runtime.last_now=now;
 af_ap_runtime.hello=(AfHandshake){.session=71,.deadline=1100,.required=AF_APPLY_PROTOCOL_REQUIRED,.state=1};
 AfApplyPacket hello={.operation=AF_APPLY_HELLO,.session=71,.required=AF_APPLY_PROTOCOL_REQUIRED};
 unsigned char raw[128];size_t bytes=0;assert(!af_apply_packet_encode(&hello,raw,sizeof raw,&bytes));
 assert(af_cp_hs_receive(raw,0x80020002u,bytes)==1);
 assert(af_ap_runtime.hello.state==2&&af_cp_handshake.state==5);
}
static void bad_native_does_not_cancel(void){
 unsigned char raw[128];size_t bytes=0;
 AfApplyPacket packet={.operation=AF_APPLY_NATIVE,.session=72,.version=3,.required=AF_APPLY_PROTOCOL_REQUIRED};
 assert(!af_apply_packet_encode(&packet,raw,sizeof raw,&bytes));
 assert(af_cp_hs_receive(raw,0x80020002u,bytes)==1&&af_cp_recipe406_busy());
 packet.session=71;packet.version=2;assert(!af_apply_packet_encode(&packet,raw,sizeof raw,&bytes));
 assert(af_cp_hs_receive(raw,0x80020002u,bytes)==1&&af_cp_recipe406_busy());
 assert(af_cp_recipe406_seen_version()==2&&af_cp_hs_input_version==1);check_active(1);
}
int main(int argc,char **argv){
 assert(argc==3);unsigned selector=(unsigned)atoi(argv[1]),scenario=(unsigned)atoi(argv[2]);
 assert(selector==0||selector==17||selector==18);
 /* 未握手绝不借退出路径启动发送或建立会话。 */
 assert(af_ap_runtime_release_preset()==AF_BUSY&&!ap_sends);
 connect_for_exit();prepared=enabled=1;ap_base=0x70000000u;af_catalog_init(&af_ap_catalog);
 unsigned char image[AF_JOINT_ASSET_BYTES];AfPreset p;AfRecipeAck ack;
 encode_for_exit(1,image,&p);assert(!af_install(&af_ap_catalog,7,&p,0));
 AfImaging406RecipeSource source={1,sizeof source,image,capture_for_exit};
 assert(!af_imaging406_bind_recipe_source(&source));AfApImagingBinding binding;
 assert(!af_imaging406_binding(ap_base,&binding)&&!af_ap_imaging_bind(&binding));
 af_ap_select(19);assert(af_ap_imaging_result()==AF_OK&&!af_ap_runtime_recipe_result(&ack));
 assert(ack.status==AF_OK&&ack.version==1&&acks==1);check_active(1);
 encode_for_exit(2,image,&p);assert(!af_install(&af_ap_catalog,7,&p,1));
 if(scenario==1)fail_unlock=1;else fail_frame=28+5;
 af_ap_select(19);
 if(scenario==1){
  /* CP已take且解锁未知：保留pending，AP超时关闭后仍不能猜测回滚。 */
  assert(af_ap_imaging_result()==AF_OK&&af_cp_hs_input_fault);
  now=2100;(void)af_ap_runtime_poll();
 }else{
  assert(af_ap_imaging_result()==AF_IO&&recipe_frames==33);
  assert(af_cp_recipe406_busy()&&!af_cp_hs_input_fault);check_active(1);
  bad_native_does_not_cancel();
 }
 assert(af_ap_runtime_preset_status()==AF_IO&&!af_ap_runtime_preset_capabilities());
 unsigned before=ap_sends;if(scenario==2)fail_native=1;
 shown=selector==0?0x84c:selector==17?0x852:0x853;
 af_ap_select(selector);
 assert(stock_selections==1&&native_selected==selector&&native_sends==1&&ap_sends==before+1);
 assert(af_ap_imaging_result()==(scenario==2?AF_IO:AF_OK));
 if(scenario==0){
  assert(af_cp_hs_last_prepare==AF_OK&&!af_cp_recipe406_busy()&&!af_cp_hs_input_fault);
  assert(test_active()->mode==AF_CP_OVERRIDE_NATIVE&&test_active()->version==3&&!af_cp_native406_banks()->active);
  assert(af_cp_hs_input_version==3&&!af_cp_hs_input_slot&&af_cp_recipe406_seen_version()==2);
  AfRecipeTx late;unsigned char raw[128];
  assert(!af_recipe_tx_init(&late,71,2,7,&p,image,sizeof image));
  assert(!af_recipe_tx_frame(&late,4,raw,sizeof raw));
  assert(af_cp_hs_receive(raw,0x80020002u,sizeof raw)==1&&!af_cp_recipe406_busy());
  assert(af_cp_recipe406_last_result()==AF_STALE&&test_active()->mode==AF_CP_OVERRIDE_NATIVE);
  assert(af_ap_runtime_reply(reply,0x90030001u,sizeof reply)==1&&af_ap_runtime_recipe_result(&ack)==AF_IO);
 }else if(scenario==1){
  AfRecipeLease lease;const AfRecipeOwned *pending=0;
  assert(af_cp_hs_last_prepare==AF_IO&&af_cp_hs_input_fault&&af_cp_recipe406_busy());
  assert(!af_cp_recipe406_pending(&lease,&pending)&&pending&&af_cp_recipe406_release(&lease)==AF_BUSY);
  assert(test_active()->mode==AF_CP_OVERRIDE_USER&&test_active()->version==2);
 }else{assert(af_cp_recipe406_busy()&&test_active()->mode==AF_CP_OVERRIDE_USER);check_active(1);}
 /* 原厂事件不丢，特殊退出尝试仅一次；原刷新不得自动重发或恢复LUT功能。 */
 before=ap_sends;af_ap_select(selector);assert(stock_selections==2&&ap_sends==before&&native_sends==1);
 assert(af_ap_runtime_release_preset()==AF_IO&&ap_sends==before);
 assert(af_ap_runtime_send_preset(0,&(AfPreset){.params={0,0,0,0,0,0,3,0}})==AF_IO);
 assert(af_ap_runtime_send_recipe(7,&p,image,sizeof image,1000)==AF_IO);
 assert(af_ap_runtime_last_attempted_version()==3&&!af_ap_runtime_preset_capabilities());
 Word manager[1]={ap_address(0x58d2fb8)};imaging_pending_poll(manager);assert(ap_sends==before);
 return 0;
}
'''


@pytest.fixture(scope="module")
def exit_driver(native_binding_driver, tmp_path_factory):
    folder = tmp_path_factory.mktemp("explicit-native-exit406")
    previous = native_binding_driver.parent
    for name in ("core.c", "overlay.c", "ingress.c", "ports.h"):
        (folder / name).write_text((previous / name).read_text())
    driver = DRIVER.split("int main(int argc,char **argv)")[0]
    needle = "}else{AfApplyPacket value;assert(!af_apply_packet_decode(data,bytes,&value));++hellos;}\n return 0;"
    assert driver.count(needle) == 1
    driver = driver.replace(needle, needle[:-len("return 0;")] + "assert(af_ap_runtime_reply(data,0x90030001u,bytes)==1);return 0;")
    ui = (NATIVE / "af_ap_ui.c").read_text()
    resolver = "static Word ap_address(Word offset) { return ap_base + offset; }"
    assert ui.count(resolver) == 1
    ui = ui.replace(resolver, "static Word address_for_exit(Word);\nstatic Word ap_address(Word offset){return address_for_exit(offset);}")
    source = folder / "driver.c"
    source.write_text('#include "af_runtime_ap406.h"\nextern int af_ap_runtime_reply(const void *,uint32_t,size_t);\n' + ui + driver + EXTRA)
    files = ("af_cp_native_bank406.c", "af_cp_input406.c", "af_cp_copy406.c", "af_cp406_state.c",
             "af_cp_recipe406.c", "af_recipe_transport.c", "af_joint_asset.c", "af_joint.c",
             "af_sha256.c", "af_slots.c", "af_handshake.c", "af_apply_wire.c", "af_runtime_ap406.c",
             "af_runtime.c", "af_imaging406.c", "af_ui.c")
    flags = ("AF_CP_NATIVE406", "AF_CP_PRESET406", "AF_RUNTIME406", "AF_FACTORY_RESTORE406",
             "AF_RECIPE_BRIDGE406", "AF_SNAPSHOT_OVERLAY406", "AF_CP_CARVE_BRANCH406",
             "AF_CP_CAPTURE_INPUT406", "AF_CP_CAPTURE_COPIES406")
    if native_binding_driver.name == "native-binding-capture":
        flags += ("AF_CP_CAPTURE406",)
    binary = folder / "exit"
    built = subprocess.run(["clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
        "-ffunction-sections", "-fdata-sections", "-Wl,-dead_strip", *["-D" + f + "=1" for f in flags],
        "-DAF_CP_SNAPSHOT_ENTRY406=0xbefa29u", "-I" + str(NATIVE), "-include", str(folder / "ports.h"),
        *[str(folder / name) for name in ("core.c", "overlay.c", "ingress.c")], str(source),
        *[str(NATIVE / name) for name in files], "-o", str(binary)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    return binary


@pytest.mark.parametrize("selector,scenario", [(0, 0), (17, 0), (18, 0), (18, 1), (17, 2)],
                         ids=["ST", "FL2", "FL3", "unknown-taken-kept", "exit-send-failed-no-retry"])
def test_explicit_factory_exit_after_partial_recipe_failure(exit_driver, selector, scenario):
    run = subprocess.run([str(exit_driver), str(selector), str(scenario)], capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
