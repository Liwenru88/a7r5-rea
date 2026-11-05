/* 复现原FAT短名模式：指针为短名，但完整UTF8长名同时存在。 */
#define main original_contract_main
#include "fsys406_contract.c"
#undef main
static unsigned alias_epoch;
static int allow_utf8(void *p){assert(p==&alias_epoch);return AF_OK;}
static void alias_name(unsigned index,char out[13]){snprintf(out,13,"F%06u.BIN",(mode==3?0:index)+alias_epoch*10);}
static void alias_result(void *out,unsigned index){
    result(out,index);uint8_t *p=out;char alias[13];alias_name(index,alias);
    put64(p,(uintptr_t)(p+0x5aa));memcpy(p+0x5aa,alias,strlen(alias)+1);
    if(mode==2)memcpy(p+0x5aa,"../BAD.BIN",11);
}
static int32_t alias_first(const char *path,uint8_t attr,void *out){
    int at=check_path(path);assert(attr==0x80);
    if(!strcmp(path+at,"*.*")){enum_index=0;alias_result(out,0);return 0;}
    for(unsigned i=0;i<files;++i){char alias[13];alias_name(i,alias);if(!strcmp(path+at,alias)){alias_result(out,i);return 0;}}
    return 2;
}
static int32_t alias_next(void *out){if(++enum_index==files)return 2;alias_result(out,enum_index);return 0;}
static int32_t alias_open(const char *path,uint64_t *out,uint32_t flags){
    int at=check_path(path);assert(flags==1);
    for(current_file=0;current_file<files;++current_file){char alias[13];alias_name(current_file,alias);if(!strcmp(path+at,alias))break;}
    assert(current_file<files);++opens;position=0;*out=token+opens;return 0;
}
int main(int argc,char **argv){
    assert(argc==2);mode=atoi(argv[1]);test_policy=allow_utf8;test_policy_context=&alias_epoch;setup(0);
    strcpy(names[0],"暖光.cube");strcpy(names[1],"电脑参数.a7filter");
    context.binding.fsys.find_first=alias_first;context.binding.fsys.find_next=alias_next;context.binding.fsys.open=alias_open;
    AfMediaList before=listing;int status=af_fsys406_scan(&context,1,&work,&listing);
    if(mode==2||mode==3){assert(status==AF_INVALID&&!memcmp(&listing,&before,sizeof before));return 0;}
    assert(!status&&listing.count==2);assert(strcmp(listing.entries[0].name,"F000000.BIN"));
    AfMediaSource metadata;memset(&metadata,0xa5,sizeof metadata);AfMediaSource old=metadata;
    uint8_t output[sizeof data];if(mode==1)alias_epoch=1;
    status=af_fsys406_read(&context,&listing,0,output,sizeof output,&metadata,0,0);
    if(mode==1){assert(status==AF_STALE&&!memcmp(&metadata,&old,sizeof old)&&!opens);return 0;}
    assert(!status&&opens==2&&closes==2&&metadata.bytes==sizeof data&&!memcmp(output,data,sizeof data));
    printf("PASS original-short-alias-route case=%d\n",mode);return 0;
}
