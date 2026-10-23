/* 宿主契约仅验证捕获完整性和边界，不代替原厂初始化或 ISP。 */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../source/guest/cp-request-capture.inc"

int main(void) {
    unsigned long long storage[2048]={0};
    unsigned char request[2400],original[2400];
    const unsigned char header[8]={5,0,0x63,0x40,3,0,0,0x80};
    for(unsigned i=0;i<sizeof request;i++)request[i]=(i*37+9)&255;
    memcpy(request,header,8);memcpy(original,request,sizeof request);
    assert(a7r5_capture_cp_init(request,80,0x90030001,0x80020002,0,(void *)storage,sizeof storage)<0);
    assert(a7r5_capture_cp_init(request,2400,0x90030001,0xa5a5a5a5,0,(void *)storage,sizeof storage)<0);
    assert(a7r5_capture_cp_init(request,2400,0x90030001,0x80020002,4,(void *)storage,sizeof storage)<0);
    assert(a7r5_capture_cp_init(request,2400,0x90030001,0x80020002,0,(void *)storage,sizeof storage-1)<0);
    assert(a7r5_capture_cp_init(request,2400,0x90030001,0x80020002,0,(unsigned char *)storage+1,sizeof storage)<0);
    for(unsigned i=0;i<sizeof storage/sizeof storage[0];i++)assert(!storage[i]);
    assert(!a7r5_capture_cp_init(request,2400,0x90030001,0x80020002,0,(void *)storage,sizeof storage));
    assert(!memcmp(request,original,sizeof request));
    unsigned long long snapshot[2048];memcpy(snapshot,storage,sizeof storage);
    assert(a7r5_capture_cp_init(request,2400,0x90030001,0x80020002,0,(void *)storage,sizeof storage)<0);
    assert(!memcmp(snapshot,storage,sizeof storage));
    assert(fwrite(storage,1,sizeof storage,stdout)==sizeof storage);
    return 0;
}
