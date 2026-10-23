/* 使用真实 /proc/self/mem 和生成的帧捕获实现，验证忙锁后的完整释放与失败停止。 */
#define _GNU_SOURCE
#include "headless-osd.h"
#include <assert.h>
#include <string.h>
#include <sys/mman.h>
#include <stdio.h>
#include <stdint.h>
static unsigned int sem,ref,reader,raster,attempts,busy,read_error,signal_error;
static unsigned char *region,*bits;
static int wait_sem(unsigned int id,unsigned int timeout) {
    assert(id==1 && timeout==0 && !sem && !ref && !reader && !raster);
    sem=1;attempts++;return 0;
}
static int signal_sem(unsigned int id) {assert(id==1&&sem&&!ref&&!reader&&!raster);sem=0;return signal_error?-1:0;}
static int addref(void *p) {assert(sem&&!ref);ref=1;return 0;}
static int lock_bits(void *p,int timeout,const void **out) {
    assert(sem&&ref&&!reader&&timeout==0);
    if(read_error)return -1;reader=1;*out=bits;return 0;
}
static int unlock_bits(void *p) {assert(reader&&!raster);reader=0;return 0;}
static int release(void *p) {assert(ref&&!reader&&!raster);ref=0;return 0;}
static int physical(void *p,unsigned long *out) {*out=0x43b9a8100;return 0;}
static int rows(void *p,short *out) {*out=640;return 0;}
static int bytes(void *p,unsigned long *out) {*out=HOSD_PIXELS;return 0;}
static int try_raster(void) {assert(sem&&ref&&reader&&!raster);if(attempts<=busy)return 16;raster=1;return 0;}
static int unlock_raster(void) {assert(raster);raster=0;return 0;}
static void record(const char *a,const char *b) {}
static void reset(void) {sem=ref=reader=raster=attempts=busy=read_error=signal_error=0;}
int main(void) {
    size_t length=0x400000;
    region=mmap((void *)0x4000000000UL,length,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0);
    assert(region==(void *)0x4000000000UL);
    unsigned long base=(unsigned long)region;
    unsigned char *mgr=region+0x1000,*fb=region+0x2000,*bitmap=region+0x3000;
    bits=region+0x4000;
    *(unsigned long *)(region+0x2d1588)=(unsigned long)mgr;
    *(unsigned long *)(mgr+8)=(unsigned long)fb;
    *(unsigned long *)(fb+0x68)=(unsigned long)(fb+0x20);
    *(unsigned long *)(fb+0x70)=(unsigned long)(fb+0x40);
    *(unsigned long *)(fb+0x20)=(unsigned long)bitmap;
    *(unsigned int *)(fb+0x30)=0x402;
    *(unsigned long *)(fb+0x38)=0x43b9a8100;
    *(unsigned short *)(fb+8)=640;*(unsigned short *)(fb+10)=480;
    *(unsigned int *)(fb+12)=1;*(unsigned int *)(fb+0x98)=1;
    *(unsigned long *)bitmap=base+0x2555a0;
    for(unsigned int i=0;i<HOSD_PIXELS;i++)bits[i]=(i*37+9)&255;
    unsigned char out[HOSD_PIXELS];
    struct hosd_native api={wait_sem,signal_sem,addref,lock_bits,unlock_bits,release,physical,rows,bytes,try_raster,unlock_raster,record};
    struct hosd_frame f={0x402,640,480,1,0};
    reset();busy=7;
    assert(!hosd_capture_frame(base,&api,&f,out));assert(attempts==8&&!sem&&!ref&&!reader&&!raster);
    assert(!memcmp(out,bits,HOSD_PIXELS));
    reset();busy=1000;memset(out,0x55,sizeof out);
    assert(hosd_capture_frame(base,&api,&f,out)==-1 && attempts==1000);
    assert(!sem&&!ref&&!reader&&!raster && out[0]==0x55 && out[HOSD_PIXELS-1]==0x55);
    reset();read_error=1;
    assert(hosd_capture_frame(base,&api,&f,out)==-1 && attempts==1&&!sem&&!ref&&!reader&&!raster);
    reset();busy=7;signal_error=1;
    assert(hosd_capture_frame(base,&api,&f,out)==-1 && attempts==1&&!sem&&!ref&&!reader&&!raster);
    assert(!munmap(region,length));
    puts("A7R5_NATIVE_LEASE_PASS busy-release/snapshot/timeout/read-error/cleanup-error");
}
