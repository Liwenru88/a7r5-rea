/* 直接测试实际载荷的状态门槛、一次按键和 UI 线程边界。 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
static unsigned int a7r5_native_pending,a7r5_native_seen_menu=1,a7r5_native_key_down;
static unsigned int ui_thread_id=42,create_screen_active,a7r5_apply_depth;
static unsigned long appfw_base=0x100000,captured_manager;
static unsigned int fake_tid=43,source=0x92840747,size=20,applies,refused;
static long fake_syscall(long n){assert(n==178);return fake_tid;}
#define syscall fake_syscall
static unsigned int msg_size(void *p){(void)p;return size;}
static unsigned int msg_source(void *p){(void)p;return source;}
static int msg_free(unsigned int q,void *p){(void)q;(void)p;return 0;}
static unsigned int (*real_msg_size)(void *)=msg_size;
static unsigned int (*real_get_source)(void *)=msg_source;
static int (*real_free_msg)(unsigned int,void *)=msg_free;
static void record(const char *prefix,const char *text){(void)text;if(strstr(prefix,"REFUSED"))++refused;}
static unsigned long owner;
static unsigned int original_exit_calls;
static void a7r5_native_boot_exit(void *,const unsigned int *);
static void real_exit(void *o,const unsigned int *to){(void)o;(void)to;++original_exit_calls;}
static void apply(void *o,const unsigned int *a,const unsigned int *b,const unsigned int *c,unsigned int d,unsigned int e,unsigned int f,unsigned int g,unsigned int h){
 assert(*a==0x4cf && *b==0x354 && *c==0x4cf);assert(!d && e==1 && !f && !g && !h);
 assert(fake_tid==ui_thread_id && !create_screen_active && a7r5_apply_depth==1);
 a7r5_native_boot_exit(&owner,b);
 assert(!original_exit_calls);
 *(unsigned int *)((char *)o+0x3b8)=0x354;++applies;
}
static void (*a7r5_original_apply)(void *,const unsigned int *,const unsigned int *,const unsigned int *,unsigned int,unsigned int,unsigned int,unsigned int,unsigned int)=apply;
#include "../source/guest/native-menu-reentry.inc"
static union {unsigned long align;char bytes[1024];} storage;
static unsigned int key[5]={0x1ab,0,1,0,1};
static void current(unsigned int v){*(unsigned int *)(storage.bytes+0x3b8)=v;}
static int down(void){key[2]=1;return a7r5_native_key_received(0x807a0020,key);}
static int up(void){key[2]=0;return a7r5_native_key_received(0x807a0020,key);}
int main(void){
 setenv("A7R5_NATIVE_MENU_REENTRY","1",1);
 captured_manager=(unsigned long)storage.bytes;
 *(unsigned long *)storage.bytes=appfw_base+0x58d2fb8;
 owner=appfw_base+0x58d3028;
 a7r5_native_original_boot_exit=real_exit;
 *(unsigned long *)(storage.bytes+0x398)=(unsigned long)&owner;
 current(0x2d6);assert(!down());assert(!up());assert(!a7r5_native_pending);
 current(0x355);assert(down());assert(down());assert(up());assert(!up());
 a7r5_native_reentry_poll();assert(!applies);
 fake_tid=42;a7r5_apply_depth=1;a7r5_native_reentry_poll();assert(!applies);
 a7r5_apply_depth=0;create_screen_active=1;a7r5_native_reentry_poll();assert(!applies);
 create_screen_active=0;a7r5_native_reentry_poll();assert(applies==1);a7r5_native_reentry_poll();assert(applies==1);
 for(unsigned int i=0;i<20;++i){current(0x355);assert(down());assert(up());a7r5_native_reentry_poll();assert(applies==i+2);}
 unsigned int before=applies;
 current(0x316);assert(!down());assert(!up());a7r5_native_reentry_poll();assert(applies==before);
 current(0x355);key[0]=3;assert(!down());assert(!up());key[0]=0x1ab;
 size=19;assert(!down());size=20;source=7;assert(!down());source=0x92840747;
 assert(down());assert(up());current(0x2d6);a7r5_native_reentry_poll();assert(refused==1 && applies==before && !a7r5_native_pending);
 unsigned int target=0x354;a7r5_native_boot_exit(&owner,&target);assert(original_exit_calls==1);
 unsetenv("A7R5_NATIVE_MENU_REENTRY");current(0x355);assert(!down());assert(!a7r5_native_pending);
 puts("NATIVE_REENTRY_POLICY_PASS menu-only/edge-pair/once/ui-thread/draw-boundary/unknown-state/race/feature-off");return 0;
}
