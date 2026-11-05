#include "af_cp_copy406.h"

static int range(const void *p,size_t n){return p&&n&&(uintptr_t)p<=UINTPTR_MAX-n;}
static int separate(const void *a,size_t n,const void *b,size_t m){
    return range(a,n)&&range(b,m)&&((uintptr_t)a+n<=(uintptr_t)b||(uintptr_t)b+m<=(uintptr_t)a);
}
int af_cp_copy406_observe(AfCpInput406 *input,void *destination,uint32_t logical_destination,
    const void *source,uint32_t logical_source,size_t bytes,uint32_t native_vd,unsigned allow,
    AfCpCopy406Port copy){
    if(!copy||!separate(input,sizeof(*input),source,bytes)||
       !separate(input,sizeof(*input),destination,bytes)||!separate(source,bytes,destination,bytes))return AF_INVALID;
    AfCpInput406Write write;
    int result=af_cp_input406_copy_begin(input,logical_destination,allow?logical_source:0,
        bytes,native_vd,&write);
    /* 任何资格失败也必须完成原复制；不能把原厂输入留成半份。 */
    copy(destination,source,bytes);
    return result==AF_OK?af_cp_input406_copy_end(input,&write,destination,bytes):result;
}
