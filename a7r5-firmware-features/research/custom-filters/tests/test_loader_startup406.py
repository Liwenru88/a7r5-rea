"""真实启动胶合的宿主边界测试；不运行原AP、ARM指令或任何设备。"""
from pathlib import Path
import subprocess

import pytest

HOME=Path(__file__).resolve().parents[1]
LOADER=HOME/'experiments/packaging406/loader'
NATIVE=HOME/'native'


def function(text,signature):
    start=text.index(signature);at=text.index('{',start);end=at+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]+'\n'


PREFIX=r'''
#include "af_bootstrap406.h"
#include "af_ap_ui.h"
#include "af_apply.h"
#include "manifest_types.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define COUNT(a) (sizeof(a)/sizeof((a)[0]))
#define PAGE(a) ((uintptr_t)(a)&~(uintptr_t)4095)
#define BOOT_STARTUP_REQUIRED (AF_APPLY_ALL|AF_AP_IMAGING_REQUIRED|AF_AP_IMAGING_FULL_RECIPE|AF_AP_IMAGING_USER20|AF_AP_IMAGING_SECTOR_MATRIX)
typedef struct {unsigned tag;} Loaded;
static Loaded ui,requests;
static uintptr_t ap_base;
static volatile unsigned admission_ready;
static unsigned installed;
static unsigned registered,hook_changed,parent_open,descriptor_open,disabled;
static int last_status,parent_protection=1,descriptor_protection=1;
static void *island;
static uint32_t hook_after[3];
static const BootHook boot_hooks[]={
 {0x1e97a24,0xa9bd7bfd,"af_ap_refresh",0},
 {0x2209580,0xa9bc7bfd,"af_ap_select",0},
 {0x220933c,0xa9bd7bfd,"af_ap_reset",0}};
static const BootHook boot_startup_hooks[]={
 {0x3554d38,0x97861836,"af_ap_runtime_gate",0},
 {0x3554d90,0x39400260,"af_ap_hs_gate",0},
 {0x1ec738c,0x97ff41a6,"startup_refresh",1}};
static const BootCheck boot_startup_checks[]={
 {0x3554d38,0x97861836},{0x3554d90,0x39400260},{0x1ec738c,0x97ff41a6}};
static uint32_t words[3],ui_words[3],caps,menu=0x2b36;
static unsigned writes,fail_write,published,storage_calls,stock_calls,status_calls,cap_calls,cache_calls,protect_calls;
static uintptr_t thread_id=7,owner[128];
static int peer=AF_BUSY,publish_result,storage_result;
static uint32_t island_words[1024] __attribute__((aligned(4096)));
static int force_island;
static uintptr_t startup_refresh(void *);
static void startup_poll(void *,uintptr_t);
static int startup_admitted(void);
static int fail(int);
static uintptr_t test_thread(void){return thread_id;}
static uint32_t test_caps(void){++cap_calls;return caps;}
static int test_peer(void){++status_calls;return peer;}
static uintptr_t test_refresh(void *value){assert(value==owner);++stock_calls;return 0x17;}
static const uint32_t *test_menu(void){return &menu;}
static void *symbol(const Loaded *m,const char *name){
 if(m==&ui){assert(!strcmp(name,"af_ap_refresh") || !strcmp(name,"af_ap_select") || !strcmp(name,"af_ap_reset"));return (void *)test_refresh;}
 assert(m==&requests);
 if(!strcmp(name,"af_ap_runtime_preset_capabilities"))return (void *)test_caps;
 if(!strcmp(name,"af_ap_runtime_preset_status"))return (void *)test_peer;
 assert(!strcmp(name,"af_ap_runtime_gate") || !strcmp(name,"af_ap_hs_gate"));
 return force_island?(void *)0x1000:(void *)test_refresh;
}
#define UF(name,type) ((type)symbol(&ui,name))
static void *dlsym(void *handle,const char *name){assert(!handle&&!strcmp(name,"pthread_self"));return (void *)test_thread;}
static int maps(void){return 1;}
static int protection(uintptr_t at,size_t size){(void)size;return at==(uintptr_t)owner || at==(uintptr_t)&menu?3:5;}
static int word(uintptr_t at,uint32_t value,int flags){
 assert(flags==5);for(unsigned i=0;i<3;++i)if(at==ap_base+boot_startup_hooks[i].at)return words[i]==value;
 for(unsigned i=0;i<3;++i)if(at==ap_base+boot_hooks[i].at)return ui_words[i]==value;
 assert(0);return 0;
}
static int code(uintptr_t at,uint32_t expected,uint32_t value){
 ++writes;if(writes==fail_write)return 0;
 for(unsigned i=0;i<3;++i)if(at==ap_base+boot_startup_hooks[i].at){assert(words[i]==expected);words[i]=value;return 1;}
 for(unsigned i=0;i<3;++i)if(at==ap_base+boot_hooks[i].at){assert(ui_words[i]==expected);ui_words[i]=value;return 1;}
 assert(0);return 0;
}
static void *gap(uintptr_t low,uintptr_t high,size_t bytes){
 assert(bytes==4096 && low<=(uintptr_t)island_words && (uintptr_t)island_words+bytes<=high);return island_words;
}
static void cache(uintptr_t at,size_t size){assert(at==(uintptr_t)island_words && size==4096);++cache_calls;}
static int mprotect(void *at,size_t size,int flags){assert(at==island_words && size==4096 && flags==5);++protect_calls;return 0;}
static void disable(void){if(registered)++disabled;}
int af_bootstrap406_publish(void){
 ++published;assert(startup_admitted());
 assert(startup_live && hook_changed==3 && startup_changed==3);
 for(unsigned i=0;i<3;++i){assert(words[i]!=boot_startup_hooks[i].before);assert(ui_words[i]==hook_after[i]);}
 /* 原UI回调可嵌套刷新，但不能递归发布/注册。 */
 startup_poll(owner,ap_base+0x1ec7390);assert(published==1);
 if(publish_result)return fail(publish_result);
 installed=1;return AF_OK;
}
int af_bootstrap406_bind_native_storage(int library){assert(library==-1 && installed && published==1);++storage_calls;return storage_result;}
'''

MAIN=r'''
static void originals(void){for(unsigned i=0;i<3;++i){assert(words[i]==boot_startup_hooks[i].before);assert(ui_words[i]==boot_hooks[i].before);}}
int main(int argc,char **argv){
 assert(argc==2);ap_base=((uintptr_t)startup_refresh&~(uintptr_t)4095)-0x2000000;
 owner[0]=ap_base+0x58d2fb8;((uint32_t *)owner)[0x3b8/4]=0x2d4;
 for(unsigned i=0;i<3;++i){words[i]=boot_startup_hooks[i].before;ui_words[i]=boot_hooks[i].before;}
 if(!strcmp(argv[1],"preimage"))words[1]^=1;
 if(!strcmp(argv[1],"write"))fail_write=2;
 if(!strcmp(argv[1],"startup-write"))fail_write=5;
 if(!strcmp(argv[1],"island"))force_island=1;
 int result=startup_install();
 if(result!=AF_OK)(void)fail(result); /* 原prepare的相同失败收尾。 */
 if(!strcmp(argv[1],"preimage")){
  assert(result==AF_STALE && !writes && startup_phase==4 && !admission_ready);return 0;
 }
 if(!strcmp(argv[1],"write") || !strcmp(argv[1],"startup-write")){
  assert(result==AF_IO && startup_phase==4 && !startup_changed && !hook_changed && !startup_live);originals();return 0;
 }
 assert(result==AF_OK && startup_phase==1 && startup_live && startup_changed==3 && hook_changed==3 && !admission_ready && !status_calls && !cap_calls);
 startup_menu_getter=test_menu;unsigned frozen_writes=writes;
 /* 实际包装器总是原refresh完整委派一次并保留返回；宿主LR不伪装原AP。 */
 assert(startup_refresh(owner)==0x17 && stock_calls==1 && !status_calls);
 startup_poll(owner,ap_base+0x1ec7394);assert(!status_calls && !startup_owner);
 startup_poll(owner,ap_base+0x1ec7390);assert(startup_phase==1 && status_calls==1 && !cap_calls && !published && !storage_calls);
 if(!strcmp(argv[1],"owner"))thread_id++;
 else if(!strcmp(argv[1],"closed"))peer=AF_IO;
 else {peer=AF_OK;caps=BOOT_STARTUP_REQUIRED;}
 if(!strcmp(argv[1],"capability"))caps&=~AF_AP_IMAGING_USER20;
 if(!strcmp(argv[1],"publish"))publish_result=AF_IO;
 if(!strcmp(argv[1],"storage"))storage_result=AF_IO;
 if(!strcmp(argv[1],"idle")){
  ((uint32_t *)owner)[0x3b8/4]=0xd4;startup_poll(owner,ap_base+0x1ec7390);
  assert(startup_phase==1 && !published && !admission_ready);
  ((uint32_t *)owner)[0x3b8/4]=0x2d4;menu=0x84c;startup_poll(owner,ap_base+0x1ec7390);
  assert(startup_phase==1 && !published && !admission_ready);menu=0x2b36;
 }
 startup_poll(owner,ap_base+0x1ec7390);
 assert(writes==frozen_writes); /* 活跃任务后的成功/失败一律零代码写。 */
 if(!strcmp(argv[1],"owner") || !strcmp(argv[1],"closed") || !strcmp(argv[1],"capability") || !strcmp(argv[1],"publish")){
  assert(startup_phase==4 && !admission_ready && startup_changed==3 && hook_changed==3 && !installed && !storage_calls);
  assert(startup_result==(!strcmp(argv[1],"closed") || !strcmp(argv[1],"publish")?AF_IO:AF_STALE));
  for(unsigned i=0;i<3;++i){assert(words[i]==startup_after[i]);assert(ui_words[i]==hook_after[i]);}
  unsigned old=published;peer=AF_OK;caps=BOOT_STARTUP_REQUIRED;
  startup_poll(owner,ap_base+0x1ec7390);assert(published==old);return 0;
 }
 assert(startup_phase==3 && installed && admission_ready && published==1 && storage_calls==1 && startup_changed==3);
 assert(startup_result==(!strcmp(argv[1],"storage")?AF_IO:AF_OK));
 if(force_island){
  assert(cache_calls==1 && protect_calls==1);
  for(unsigned i=0;i<2;++i)assert(island_words[4*i]==0x58000050 && island_words[4*i+1]==0xd61f0200);
  assert(!island_words[8] && !island_words[9]);
 }
 startup_poll(owner,ap_base+0x1ec7390);assert(published==1 && storage_calls==1);
 return 0;
}
'''


@pytest.fixture(scope='module')
def startup(tmp_path_factory):
    folder=tmp_path_factory.mktemp('loader-startup406');source=folder/'startup.c';binary=folder/'startup'
    text=(LOADER/'af_bootstrap406.c').read_text()
    start=text.index('static unsigned startup_phase');end=text.index('#endif',start)
    signatures=('static int jump(', 'static int fail(', 'static int install_ui_hooks(',
                'static void startup_restore(', 'static int startup_stop(', 'static int startup_main_idle(',
                'static int startup_admitted(', 'static void startup_poll(', 'static uintptr_t startup_refresh(',
                'static int startup_install(')
    # 前置声明需先于显式端口实现，定义仍逐字使用生产源码。
    split=PREFIX.index('static void *symbol(')
    source.write_text(PREFIX[:split]+text[start:end]+PREFIX[split:]+''.join(function(text,s) for s in signatures)+MAIN)
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-DAF_RECIPE_BRIDGE406=1','-I'+str(NATIVE),'-I'+str(LOADER),str(source),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return binary


@pytest.mark.parametrize('case',['ready','closed','capability','owner','preimage','write','startup-write','publish','storage','island','idle'])
def test_startup_delegates_waits_for_real_status_and_publishes_once(startup,case):
    result=subprocess.run([str(startup),case],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_registered_failure_does_not_write_never_enabled_readonly_parent(tmp_path):
    text=(LOADER/'af_bootstrap406.c').read_text()
    source=tmp_path/'disable.c';binary=tmp_path/'disable'
    source.write_text(r'''
#include "af_ap_ui.h"
#include <assert.h>
#include <string.h>
static uintptr_t ap_base=0x100000;
static unsigned registered=1,manage_menu_enabled,research_enabled,parent_open,descriptor_open;
static unsigned parent_writes,descriptor_writes,bss_calls,map_reads;
static int parent_flags=1,descriptor_flags=1;
static int maps(void){++map_reads;return 1;}
static int protection(uintptr_t at,size_t bytes){
 if(at==ap_base+0x594a7b0u){assert(bytes==8);return parent_flags;}
 assert(at==ap_base+0x5858b08u && bytes==0x80);return descriptor_flags;
}
static int parent_enable(uint32_t value){assert(!value && parent_open && parent_flags==3);++parent_writes;return 0;}
static int descriptor_enable(uint32_t value){assert(!value && descriptor_open && descriptor_flags==3);++descriptor_writes;return 0;}
static int private_enable(uint32_t value){assert(!value);++bss_calls;return 0;}
static void *lookup(const char *name){
 if(!strcmp(name,"af_ap_manage_menu_enable"))return (void *)parent_enable;
 if(!strcmp(name,"af_ap_research_enable"))return (void *)descriptor_enable;
 assert(!strcmp(name,"af_ap_targets_enable") || !strcmp(name,"af_ap_browser_enable") ||
  !strcmp(name,"af_ap_cards_enable") || !strcmp(name,"af_ap_names_enable"));return (void *)private_enable;
}
#define UF(name,type) ((type)lookup(name))
'''+function(text,'static void disable(')+r'''
int main(void){
 /* 自然身份已登记，菜单register/bind尚未成功，parent仍为原RO页。 */
 disable();assert(!parent_writes && !descriptor_writes && !map_reads && bss_calls==4);
 /* 只有CreativeLook描述符已启用，后续名称绑定失败；parent仍不应写。 */
 descriptor_open=research_enabled=1;descriptor_flags=3;disable();
 assert(!parent_writes && descriptor_writes==1 && !research_enabled && map_reads==1);
 /* parent真正启用后才允许恢复，且只写一次；页面仍须实际RW。 */
 parent_open=manage_menu_enabled=1;parent_flags=3;disable();
 assert(parent_writes==1 && !manage_menu_enabled && map_reads==2);
 disable();assert(parent_writes==1 && descriptor_writes==1 && map_reads==2);return 0;
}
''')
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(source),'-o',str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    result=subprocess.run([str(binary)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
