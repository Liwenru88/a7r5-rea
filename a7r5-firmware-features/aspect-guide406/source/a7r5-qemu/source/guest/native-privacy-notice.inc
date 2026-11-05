#include "a7r5-privacy-policy.h"
/* 请求文件只存在于客体 /tmp；入口固定，不接受任意页面编号。 */
static void a7r5_privacy_notice_poll(void) {
    static unsigned int attempted;
    if (!getenv("A7R5_INITIAL_PRIVACY_NOTICE") ||
        (unsigned int)syscall(178)!=ui_thread_id || a7r5_apply_depth || create_screen_active) return;
    static unsigned int last_accepted=0xffffffff;
    unsigned int state=*(const unsigned int *)(appfw_base+0x7effa98+0xa74f8);
    if(state!=last_accepted) {
        char text[80];snprintf(text,sizeof text,"accepted=%u",state);
        record("KEY_TRACE_PRIVACY_STATUS ",text);last_accepted=state;
    }
    if(attempted)return;
    int fd=open("/tmp/a7r5-request-initial-privacy",0);
    if(fd<0)return;
    close(fd);attempted=1;
    unsigned long m=captured_manager;
    if(!m || *(unsigned long *)m!=appfw_base+0x58d2fb8) {
        record("A7R5_PRIVACY_REFUSED ","manager fingerprint differs");return;
    }
    unsigned long properties=appfw_base+0x7effa98;
    unsigned int current=*(unsigned int *)(m+0x3b8);
    unsigned int selecting=*(unsigned int *)(properties+0x18f40);
    unsigned int accepted=*(unsigned int *)(properties+0xa74f8);
    char text[180];
    snprintf(text,sizeof text,"current=%#x selecting=%#x accepted=%u tid=%u",current,selecting,accepted,ui_thread_id);
    record("A7R5_PRIVACY_GATE ",text);
    if(!a7r5_privacy_can_open(current,selecting,accepted)) {
        record("A7R5_PRIVACY_REFUSED ","not an uninitialized original menu context");return;
    }
    unsigned long table=*(unsigned long *)(appfw_base+0x5915668);
    const unsigned int *desc=(const unsigned int *)(table+0x1e3*96);
    if(table!=appfw_base+0x506bf20 || desc[8]!=0x1e3 ||
        *(const unsigned long *)((const char *)desc+8)!=appfw_base+0x1d4ca54) __builtin_trap();
    unsigned int to=0x1e3,restore=current;
    record("A7R5_PRIVACY_OPEN ","original scr7248_0001 first-setup mode; no consent field written");
    a7r5_original_open((void *)m,&current,&to,&restore,1,0);
}
