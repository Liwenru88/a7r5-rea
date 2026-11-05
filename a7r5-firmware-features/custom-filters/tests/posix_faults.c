/* 仅测试链接：对真实POSIX适配器注入短写/EINTR/ENOSPC/同步和关闭错误。 */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <unistd.h>
#include <stddef.h>
#include <stdint.h>
static int mode,calls,stage_fd=-1;
void af_test_fault(int value) { mode=value;calls=0;stage_fd=-1; }
ssize_t af_test_write(int fd,const void *p,size_t n) {
    stage_fd=fd;++calls;
    if (mode==1 && calls==1) { errno=EINTR;return -1; }
    if (mode==2 && calls>2) { errno=ENOSPC;return -1; }
    if ((mode==1 || mode==2) && n>3) n=3;
    return write(fd,p,n);
}
int af_test_fsync(int fd) {
    if (mode==3 && fd==stage_fd) { errno=EIO;return -1; }
    return fsync(fd);
}
int af_test_close(int fd) {
    int result=close(fd);
    if (mode==4 && fd==stage_fd) { stage_fd=-1;errno=EIO;return -1; }
    return result;
}
