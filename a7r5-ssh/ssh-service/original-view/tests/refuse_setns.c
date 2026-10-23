/* 仅QEMU注入内核setns失败，确认用户命令零执行。 */
#define setns injected_setns
#include "../session.c"
int injected_setns(int fd,int type){(void)fd;(void)type;errno=1;return -1;}
