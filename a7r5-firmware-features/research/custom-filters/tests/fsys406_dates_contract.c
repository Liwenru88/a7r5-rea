/* 原Find稳定元数据契约；原访问字段映射另有同包只读指令证据。 */
#define main original_contract_main
#include "fsys406_contract.c"
#undef main

static int stable_offset;
static int32_t dated_first(const char *path,uint8_t attr,void *v){
    int32_t r=first(path,attr,v);
    if(!r&&opens){
        uint8_t *p=v;
        /* 原Read可更新访问日期、UTC和时间；原更新10ms(result+20)必须保留。 */
        static const uint8_t access[]={0x18,0x19,0x22,0x23,0x24,0x25};
        for(unsigned i=0;i<sizeof(access);++i)p[access[i]]=(uint8_t)(7+opens);
        if(stable_offset>=0)p[stable_offset]^=1;
    }
    return r;
}

int main(int argc,char **argv){
    assert(argc==2);stable_offset=atoi(argv[1]);
    setup(0);context.binding.fsys.find_first=dated_first;
    assert(!af_fsys406_scan(&context,1,&work,&listing));
    uint8_t out[sizeof(data)];AfMediaSource source;
    memset(&source,0xa5,sizeof(source));AfMediaSource before=source;
    int r=af_fsys406_read(&context,&listing,0,out,sizeof(out),&source,0,0);
    if(stable_offset<0){
        assert(r==AF_OK&&opens==2&&closes==2);
        assert(source.bytes==sizeof(data)&&!memcmp(out,data,sizeof(data)));
    }else{
        assert(r==AF_STALE&&opens==1&&closes==1);
        assert(!memcmp(&source,&before,sizeof(source)));
    }
    for(unsigned i=0;i<sizeof(context.details[0].dates);++i)
        assert(context.details[0].dates[i]==7); /* 比较规则不改写原缓存。 */
    return 0;
}
