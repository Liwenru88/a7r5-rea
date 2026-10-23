/* 普通文件故障注入夹具；不允许打开块设备，不是机身执行入口。 */
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include "jit_config.h"
#include "trust_config.h"
#include "sha256.h"
static int injected,notes;
static int note(int fd,const char *phase,unsigned completed,long offset,int code)
{
    notes++;
    if((injected==7&&!strcmp(phase,"WRITE_BEGIN")) ||
       (injected==8&&!strcmp(phase,"WRITE_RETURNED")))return -1;
    char row[256];int n=snprintf(row,sizeof(row),"A7R5_TRUST %s %s completed=%u offset=%ld code=%d\n",RUN_ID,phase,completed,offset,code);
    return n<=0||write(fd,row,n)!=n||fsync(fd)?-1:0;
}
#define TRUST_HOST_TEST 1
#include "sector_core.inc"
int main(int argc,char **argv)
{
    if(argc!=4)return 90;
    int target=open(argv[1],O_RDWR|O_NOFOLLOW);struct stat st;
    if(target<0||fstat(target,&st)||!S_ISREG(st.st_mode))return 91;
    int journal=open(argv[2],O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);if(journal<0)return 92;
    injected=atoi(argv[3]);
    int code=trust_apply_fd(target,journal,injected);
    if(close(target)||close(journal))return 93;
    printf("code=%d notes=%d\n",code,notes);return 0;
}
