/* 宿主契约：探针关闭时完全透传，开启时仅包装已指纹匹配的回调。 */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <fcntl.h>
#include "headless-osd.h"
typedef struct { const char *dli_fname; void *dli_fbase; const char *dli_sname; void *dli_saddr; } Dl_info;
static unsigned long appfw_base;
static unsigned int records,callback_calls,list_calls,forwarded_events;
static void (*registered)(int,void *);
static void *expected_self;
static const void *expected_list;
static int expected_count;
static void *expected_event;
static void original_event(int id,void *event) {
    assert(id==10 && event==expected_event);
    ++forwarded_events;
}
static int original_register(void *self,int *id,void (*callback)(int,void *)) {
    assert(self==expected_self);
    ++callback_calls;
    *id=10;registered=callback;
    return 1;
}
static int original_list(void *self,int id,const void *list,int count) {
    assert(self==expected_self && id==10 && list==expected_list && count==expected_count);
    ++list_calls;
    return 0;
}
static char last_prefix[100],last_text[300];
static void record(const char *prefix,const char *text) { assert(prefix && text); ++records;snprintf(last_prefix,sizeof last_prefix,"%s",prefix);snprintf(last_text,sizeof last_text,"%s",text); }
static int fake_dladdr(void *address,Dl_info *info) {
    assert(address==(void *)original_event);
    info->dli_fname="test-appFw";info->dli_fbase=(void *)appfw_base;return 1;
}
static int (*real_dladdr)(void *,Dl_info *)=fake_dladdr;
static void *lookup(void *handle,const char *name) {
    assert(handle==(void *)-1);
    if (strstr(name,"SetCallback"))return original_register;
    assert(strstr(name,"SetEventKeyList"));return original_list;
}
static void *(*real_dlsym)(void *,const char *)=lookup;
static void initialize(void) { abort(); }
static void clear_cache_range(void *start,size_t length) { (void)start;(void)length; }
/* 客体使用 Linux gettid；宿主契约只验证传参，避免调用 macOS 的不同 syscall 号。 */
static long test_gettid(int number) { assert(number==178); return 1; }
#define syscall test_gettid
static int test_open(const char *path,int flags) { assert(!strcmp(path,HOSD_PATH) && flags==0);return 77; }
static int test_close(int fd) { assert(fd==77);return 0; }
static int short_header;
static long test_read(int fd,void *data,size_t length) {
    assert(fd==77 && length==16);unsigned char header[16]={'H','O','S','D','A','P','0','2',42};
    memcpy(data,header,16);return short_header?8:16;
}
#define open test_open
#define read test_read
#define close test_close
#include "a7r5-input-trace.inc"
static unsigned int original_process(void *self,const unsigned int *input,unsigned int a,unsigned int b) {
    assert(self==expected_self && input==expected_event && a==3 && b==4);return 55;
}
int main(void) {
    int self=7,id=-1;
    unsigned int event[8]={0x7095,0,1,0,1,0,0,0};
    const unsigned int before[8]={0x7095,0,1,0,1,0,0,0};
    const unsigned int list[]={0x7095,0x7095,0x7ffffffe,0x1f7,0x1f7,0x7ffffffe};
    expected_self=&self;expected_list=list;expected_count=2;expected_event=event;
    appfw_base=(unsigned long)original_event-0x1800da4;
    unsetenv("A7R5_INPUT_TRACE");
    a7r5_input_trace_install(0);
    assert(a7r5_input_set_callback(&self,&id,original_event)==1 && id==10);
    assert(registered==original_event);
    assert(a7r5_input_set_keylist(&self,id,list,2)==0 && records==0);
    registered(id,event);
    setenv("A7R5_INPUT_TRACE","1",1);
    assert(a7r5_input_set_callback(&self,&id,original_event)==1 && id==10);
    assert(registered!=original_event);
    assert(a7r5_input_set_keylist(&self,id,list,2)==0);
    registered(id,event);
    assert(callback_calls==2 && list_calls==2 && forwarded_events==2);
    assert(records==5 && !memcmp(event,before,sizeof event));
    unsetenv("A7R5_INPUT_TRACE");unsetenv("A7R5_INPUT_COMPLETIONS");
    a7r5_input_original_process=original_process;
    assert(a7r5_input_process(&self,event,3,4)==55 && records==5);
    setenv("A7R5_INPUT_COMPLETIONS","1",1);
    assert(a7r5_input_process(&self,event,3,4)==55 && records==6);
    assert(!strcmp(last_prefix,"A7R5_INPUT_COMPLETED "));
    assert(!strcmp(last_text,"key=0x7095 status=0x1 frame_sequence=42 result=55"));
    short_header=1;
    assert(a7r5_input_process(&self,event,3,4)==55 && records==7);
    assert(!strcmp(last_text,"key=0x7095 status=0x1 frame_sequence=0 result=55"));
    assert(!memcmp(event,before,sizeof event));
    puts("input trace transparency: PASS");
    return 0;
}
