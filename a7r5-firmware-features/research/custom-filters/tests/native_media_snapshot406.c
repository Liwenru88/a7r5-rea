/* 仅宿主注入原三个调用边界，不执行AP指令或访问媒体。 */
#include "af_media_snapshot406.h"
#include "fixtures/media406_snapshot_pins.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static uint8_t *ap;
static uintptr_t getter_result;
static unsigned trace[4],calls,held,mutate_on_unlock;
static const uintptr_t getter=0x28a3b60,lock=0x2e7d208,unlock=0x2e7cee4,value=0x7f0cf00;

void af_media_snapshot406_test_lock(uintptr_t address){
    assert(address==(uintptr_t)ap+lock && !held);held=1;trace[calls++]=1;
}
const uint8_t *af_media_snapshot406_test_get(uintptr_t address){
    assert(address==(uintptr_t)ap+getter && held);trace[calls++]=2;
    return (const uint8_t *)getter_result;
}
void af_media_snapshot406_test_unlock(uintptr_t address){
    assert(address==(uintptr_t)ap+unlock && held);trace[calls++]=3;
    if(mutate_on_unlock)memset(ap+value,0xe3,AF_MEDIA_SNAPSHOT406_BYTES);
    held=0;
}
static void reset(void){
    memcpy(ap+getter,pin_getter,sizeof(pin_getter));
    memcpy(ap+lock,pin_lock,sizeof(pin_lock));
    memcpy(ap+unlock,pin_unlock,sizeof(pin_unlock));
    for(size_t i=0;i<AF_MEDIA_SNAPSHOT406_BYTES;++i)ap[value+i]=(uint8_t)(i*37u+3u);
    getter_result=(uintptr_t)ap+value;calls=held=mutate_on_unlock=0;
    memset(trace,0,sizeof(trace));
}
static void success(void){
    AfMediaSnapshot406 out;uint8_t expected[AF_MEDIA_SNAPSHOT406_BYTES];
    reset();memcpy(expected,ap+value,sizeof(expected));memset(&out,0x5a,sizeof(out));
    mutate_on_unlock=1;
    assert(af_ap_media_snapshot406((uintptr_t)ap,AF_MEDIA_SNAPSHOT406_AP_SPAN,&out)==AF_OK);
    assert(calls==3 && trace[0]==1 && trace[1]==2 && trace[2]==3 && !held);
    assert(memcmp(out.bytes,expected,sizeof(expected))==0 && ap[value]==0xe3);
    /* 第三条仅原样复制，不被推断为第三张卡。 */
    assert(out.bytes[2*0x70+0x6f]==expected[2*0x70+0x6f]);
}
static void preflight(void){
    AfMediaSnapshot406 out,before;memset(&before,0x6b,sizeof(before));
    const uintptr_t bad_pins[]={getter+16,lock+12,unlock+12};
    for(size_t i=0;i<3;++i){
        reset();out=before;ap[bad_pins[i]]^=1;
        assert(af_ap_media_snapshot406((uintptr_t)ap,AF_MEDIA_SNAPSHOT406_AP_SPAN,&out)==AF_STALE);
        assert(!calls && memcmp(&out,&before,sizeof(out))==0);
    }
    reset();out=before;
    assert(af_ap_media_snapshot406((uintptr_t)ap,AF_MEDIA_SNAPSHOT406_AP_SPAN-1,&out)==AF_INVALID);
    assert(!calls && memcmp(&out,&before,sizeof(out))==0);
    AfMediaSnapshot406 source_before;memcpy(&source_before,ap+value,sizeof(source_before));
    assert(af_ap_media_snapshot406((uintptr_t)ap,AF_MEDIA_SNAPSHOT406_AP_SPAN,(void *)(ap+value))==AF_INVALID);
    assert(!calls && memcmp(ap+value,&source_before,sizeof(source_before))==0);
    assert(af_ap_media_snapshot406(UINTPTR_MAX-4095,AF_MEDIA_SNAPSHOT406_AP_SPAN,&out)==AF_INVALID);
    assert(!calls && memcmp(&out,&before,sizeof(out))==0);
}
static void wrong_pointer(void){
    AfMediaSnapshot406 out,before;memset(&before,0x7c,sizeof(before));
    const uintptr_t pointers[]={0,(uintptr_t)ap+value+1,(uintptr_t)ap+AF_MEDIA_SNAPSHOT406_AP_SPAN-16};
    for(size_t i=0;i<3;++i){
        reset();out=before;getter_result=pointers[i];
        assert(af_ap_media_snapshot406((uintptr_t)ap,AF_MEDIA_SNAPSHOT406_AP_SPAN,&out)==AF_STALE);
        assert(calls==3 && trace[0]==1 && trace[1]==2 && trace[2]==3 && !held);
        assert(memcmp(&out,&before,sizeof(out))==0);
    }
}
int main(void){
    assert(posix_memalign((void **)&ap,4096,AF_MEDIA_SNAPSHOT406_AP_SPAN)==0);
    success();preflight();wrong_pointer();free(ap);
    puts("PASS locked_copy_private_snapshot / preflight_no_publication / wrong_getter_unlock_no_publication");
    return 0;
}
