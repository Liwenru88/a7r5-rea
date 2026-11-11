#include "r5_stable_io425.h"
#include "r5_runtime_session.h"
uint8_t r5_stable_scratch425[R5_STABLE_SCRATCH_BYTES] __attribute__((aligned(16)));
static const char *name(unsigned id,int pending){
    if(id==R5_STABLE_LIBRARY)return pending?"R5NATIVE.NEW":"R5NATIVE.BIN";
    if(id==R5_STABLE_PREVIOUS)return pending?"R5PREV.NEW":"R5PREV.BIN";
    if(id==R5_STABLE_SELECTION)return pending?"R5FILTER.NEW":"R5FILTER.BIN";
    if(id==R5_STABLE_RECOVERY)return pending?"R5RECOV.NEW":"R5RECOV.BIN";
    if(id==R5_STABLE_TUNE)return pending?"R5TUNE.NEW":"R5TUNE.BIN";
    if(id==R5_STABLE_TUNE_RECOVERY)return pending?"R5TREC.NEW":"R5TREC.BIN";
    return 0;
}
static int ready(struct r5_lut_directory *d){return d && d->phase==2 && d->fd>=0;}
static int absent(struct r5_lut_directory *d){int *e=d->api.error_number();return e && *e==2;}
int r5_stable_read425(struct r5_lut_directory *d,unsigned id,uint8_t *out,size_t capacity,size_t *length){
    const char *path=name(id,0);int fd,rc=2;size_t used=0;intptr_t got;
    if(!ready(d)||!path||!out||!length||capacity<2||capacity>R5_STABLE_SCRATCH_BYTES)return 2;
    fd=d->api.openat(d->fd,path,0x8000,0);if(fd<0)return absent(d)?1:2;
    /* 每次正读至少消耗一个字节；0为EOF，既支持短读又有严格字节界限。 */
    while(used<capacity){
        size_t wanted=capacity-used;if(wanted>1024)wanted=1024;
        if(!r5_session_current())break;
        got=d->api.read(fd,out+used,wanted);
        if(got<0||(size_t)got>wanted)break;
        if(!got){*length=used;rc=0;break;}used+=(size_t)got;
        if(used==capacity)rc=3;
    }
    if(d->api.close(fd))rc=2;return rc;
}
int r5_stable_publish425(struct r5_lut_directory *d,unsigned id,const uint8_t *bytes,size_t length){
    const char *pending=name(id,1),*active=name(id,0);uint8_t check[128];
    int fd,rc=2;size_t used=0,i;intptr_t got;
    if(!ready(d)||!pending||!bytes||!length||length>=R5_STABLE_SCRATCH_BYTES||!r5_session_current())return 2;
    if(d->api.unlinkat(d->fd,pending,0)&&!absent(d))return 2;
    fd=d->api.openat(d->fd,pending,0x80c1,0600);if(fd<0)return 2;
    while(used<length){
        size_t wanted=length-used;if(wanted>1024)wanted=1024;
        if(!r5_session_current())goto close_write;
        got=d->api.write(fd,bytes+used,wanted);
        if(got<=0||(size_t)got>wanted)goto close_write;used+=(size_t)got;
    }
    if(!d->api.sync(fd))rc=0;
close_write:
    if(d->api.close(fd))rc=2;if(rc)return rc;
    fd=d->api.openat(d->fd,pending,0x8000,0);if(fd<0)return 2;used=0;
    for(;;){
        size_t wanted=length+1-used;if(wanted>sizeof check)wanted=sizeof check;
        if(!r5_session_current()){rc=2;break;}
        got=d->api.read(fd,check,wanted);
        if(got<0||(size_t)got>wanted||used+(size_t)got>length){rc=2;break;}
        if(!got){if(used!=length)rc=2;break;}
        for(i=0;i<(size_t)got;i++)if(check[i]!=bytes[used+i]){rc=2;break;}
        if(rc)break;used+=(size_t)got;
    }
    if(d->api.close(fd))rc=2;if(rc)return rc;
    if(!r5_session_current())return 2;
    if(d->api.renameat(d->fd,pending,d->fd,active))return 3;
    return d->api.sync(d->fd)?3:0;
}
int r5_stable_remove425(struct r5_lut_directory *d,unsigned id){
    const char *path=name(id,0);if((id!=R5_STABLE_RECOVERY && id!=R5_STABLE_TUNE_RECOVERY) || !ready(d)||!path||!r5_session_current())return 2;
    if(d->api.unlinkat(d->fd,path,0))return absent(d)?0:2;
    return d->api.sync(d->fd)?3:0;
}
