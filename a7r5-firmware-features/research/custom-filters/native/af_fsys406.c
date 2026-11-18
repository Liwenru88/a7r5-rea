/* 原Fsys私有游标与64位文件token的只读适配；不映射成fd。 */
#include "af_fsys406.h"
#include "af_sha256.h"
#define READY 0x46535934u
_Static_assert(sizeof(uintptr_t)==8,"原Fsys绑定仅用于64位AP");
static void copy(void *v,const void *p,size_t n){uint8_t *a=v;const uint8_t *b=p;for(size_t i=0;i<n;++i)a[i]=b[i];}
static void zero(void *p,size_t n){uint8_t *a=p;for(size_t i=0;i<n;++i)a[i]=0;}
static int equal(const void *v,const void *p,size_t n){const uint8_t *a=v,*b=p;for(size_t i=0;i<n;++i)if(a[i]!=b[i])return 0;return 1;}
/* 原Read可改变访问字段result+18..19/+22..25；保留+20..21更新10ms。
 * dates缓存仍保留完整22B，只在比较时排除有原指令依据的6B。 */
static int details_equal(const AfFsys406Details *a,const AfFsys406Details *b){
    if(a->attributes!=b->attributes||a->reserved!=b->reserved||!equal(a->alias,b->alias,sizeof(a->alias)))return 0;
    for(unsigned i=0;i<sizeof(a->dates);++i){
        if(i==8||i==9||i>=18)continue;
        if(a->dates[i]!=b->dates[i])return 0;
    }
    return 1;
}
static int apart(const void *a,size_t n,const void *b,size_t m){uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);}
static uint64_t u64(const uint8_t *p){uint64_t v=0;for(unsigned i=0;i<8;++i)v|=(uint64_t)p[i]<<(8*i);return v;}
static uint32_t u32(const uint8_t *p){uint32_t v=0;for(unsigned i=0;i<4;++i)v|=(uint32_t)p[i]<<(8*i);return v;}
static size_t length(const char *p,size_t n){size_t i=0;while(i<n&&p[i])++i;return i;}
static int suffix(const char *p,size_t n){return af_media_kind(p,n)!=AF_MEDIA_UNKNOWN;}
/* 原转换器会把坏序列替换为下划线；适配层须先拒绝，避免打开不同名称。 */
static int name_valid(const char *p,size_t n,int utf8){
    if(!n||n>=AF_MEDIA_NAME_BYTES)return 0;
    for(size_t at=0;at<n;){
        uint32_t cp;unsigned more;uint8_t c=(uint8_t)p[at++];
        if(c<0x80){
            if(c<32||c==127||c==':'||c=='/'||c=='\\'||c=='*'||c=='?')return 0;
            if(c=='.'&&at<n&&p[at]=='.')return 0;
            continue;
        }
        if(!utf8)return 0;
        if(c>=0xc2&&c<=0xdf){cp=c&31u;more=1;}
        else if(c>=0xe0&&c<=0xef){cp=c&15u;more=2;}
        else if(c>=0xf0&&c<=0xf4){cp=c&7u;more=3;}
        else return 0;
        if(more>n-at)return 0;
        for(unsigned i=0;i<more;++i){c=(uint8_t)p[at++];if((c&0xc0)!=0x80)return 0;cp=(cp<<6)|(c&63u);}
        if((more==1&&cp<0x80)||(more==2&&cp<0x800)||(more==3&&cp<0x10000)||
           cp>0x10ffff||(cp>=0xd800&&cp<=0xdfff)||(cp>=0x80&&cp<=0x9f)||cp==0x2028||cp==0x2029)return 0;
    }
    return 1;
}
static int policy_apart(AfFsys406 *s,const void *p,size_t n){return !s->binding.utf8_policy||(s->binding.encoding_context&&apart(s->binding.encoding_context,1,p,n));}
static int policy(AfFsys406 *s){return s->binding.utf8_policy?s->binding.utf8_policy(s->binding.encoding_context):AF_OK;}
static int before(const char *a,const char *b){for(size_t i=0;i<AF_MEDIA_NAME_BYTES;++i){unsigned x=(unsigned char)a[i],y=(unsigned char)b[i];if(x!=y)return x<y;if(!x)return 0;}return 0;}
static int live(AfFsys406 *s,uint8_t *record){uint8_t raw[AF_FSYS406_SNAPSHOT_BYTES];int r=s->binding.snapshot(s->binding.snapshot_context,raw);if(r)return r;const uint8_t *p=raw+s->binding.slot*AF_FSYS406_RECORD_BYTES;uint32_t type=u32(p+0x1c);if(p[0x19]<'A'||p[0x19]>'Z'||(type!=3&&type!=9))return AF_STALE;copy(record,p,AF_FSYS406_RECORD_BYTES);return AF_OK;}
static int current(AfFsys406 *s,const uint8_t *record){uint8_t now[AF_FSYS406_RECORD_BYTES];int r=live(s,now);return r?r:(equal(record,now,sizeof(now))?AF_OK:AF_STALE);}
static int path(const uint8_t *record,const char *name,char out[256]){const char *root=u32(record+0x1c)==3?"/Private/Sony/PRO/LUT":"/Sony/PRO/LUT";size_t r=length(root,64),n=length(name,AF_MEDIA_NAME_BYTES);if(r==64||!n||n==AF_MEDIA_NAME_BYTES||r+n+4>256)return AF_INVALID;out[0]=(char)record[0x19];out[1]=':';copy(out+2,root,r);out[2+r]='/';copy(out+3+r,name,n);out[3+r+n]=0;return AF_OK;}
/* 原40510只会把名称指向本结果内的短名或长名；失败不解引用外来指针。 */
static int decode(const uint8_t *find,AfMediaEntry *e,AfFsys406Details *d,int utf8){
    uintptr_t p=(uintptr_t)u64(find),b=(uintptr_t)find;size_t cap;
    if(p==b+0x5aa)cap=13;else if(p==b+0x5b7)cap=0x301;else return AF_IO;
    const char *name=(const char *)p,*alias=0;size_t alias_bytes=0,n=length(name,cap);
    if(n==cap)return AF_IO;if(find[0x26]&(0x10u|0x08u))return 0;
    /* 原40510在卷65A8==0时仍保留内嵌LFN，只把公开指针设为SFN。
     * 不改卷设置：以LFN识别／展示，以已核SFN读取同一目录项。 */
    if(p==b+0x5aa&&utf8&&find[0x5b7]){
        alias=name;alias_bytes=n;name=(const char *)find+0x5b7;n=length(name,0x301);
        if(n==0x301)return AF_IO;
    }
    if(!suffix(name,n))return 0;
    if(!name_valid(name,n,utf8)||(alias&&!name_valid(alias,alias_bytes,utf8)))return AF_INVALID;
    uint64_t size=u64(find+8);if(!size)return AF_INVALID;if(size>AF_MEDIA_SOURCE_MAX)return AF_MEDIA_CAPACITY;
    zero(e,sizeof(*e));zero(d,sizeof(*d));copy(e->name,name,n);e->size=size;
    copy(d->dates,find+0x10,sizeof(d->dates));d->attributes=find[0x26];
    if(alias)copy(d->alias,alias,alias_bytes);return 1;
}
static int exact(AfFsys406 *s,const uint8_t *record,const AfMediaEntry *e,const AfFsys406Details *d){_Alignas(16) uint8_t find[AF_FSYS406_FIND_BYTES];char file[256];AfMediaEntry now;AfFsys406Details info;int r=path(record,d->alias[0]?d->alias:e->name,file);if(r)return r;zero(find,sizeof(find));int32_t f=s->binding.fsys.find_first(file,0x80,find);if(f)return f==2?AF_STALE:AF_IO;r=decode(find,&now,&info,s->binding.utf8_policy!=0);return r==1&&equal(&now,e,sizeof(now))&&details_equal(&info,d)?AF_OK:AF_STALE;}
size_t af_fsys406_bytes(void){return sizeof(AfFsys406);}
int af_fsys406_init(AfFsys406 *s,const AfFsys406Binding *b){if(!s||!b||!apart(s,sizeof(*s),b,sizeof(*b))||b->version!=AF_FSYS406_VERSION||b->bytes!=sizeof(*b)||b->slot>1||b->reserved||(b->utf8_policy&&(!b->encoding_context||!apart(s,sizeof(*s),b->encoding_context,1)))||!b->snapshot||!b->fsys.open||!b->fsys.read||!b->fsys.close||!b->fsys.find_first||!b->fsys.find_next)return AF_INVALID;if(s->initialized||s->busy)return AF_BUSY;zero(s,sizeof(*s));s->binding=*b;s->initialized=READY;return AF_OK;}
int af_fsys406_provider(AfFsys406 *s,AfMediaProvider *p){if(!s||s->initialized!=READY||!apart(s,sizeof(*s),p,sizeof(*p)))return AF_INVALID;AfMediaProvider value={AF_MEDIA_PROVIDER_VERSION,sizeof(value),s,af_fsys406_scan,af_fsys406_read};*p=value;return AF_OK;}
int af_fsys406_scan(void *context,uint64_t gen,AfMediaList *work,AfMediaList *output){AfFsys406 *s=context;if(!s||s->initialized!=READY||!gen||!apart(work,sizeof(*work),output,sizeof(*output))||!apart(s,sizeof(*s),work,sizeof(*work))||!apart(s,sizeof(*s),output,sizeof(*output))||!policy_apart(s,work,sizeof(*work))||!policy_apart(s,output,sizeof(*output)))return AF_INVALID;if(s->busy)return AF_BUSY;if(gen<=s->listing.generation)return AF_STALE;s->busy=1;uint8_t record[AF_FSYS406_RECORD_BYTES];AfFsys406Details details[AF_MEDIA_MAX];_Alignas(16) uint8_t find[AF_FSYS406_FIND_BYTES];char pattern[256];int result=policy(s);if(result)goto finish;result=live(s,record);if(result)goto finish;result=path(record,"*.*",pattern);if(result)goto finish;zero(work,sizeof(*work));work->generation=gen;zero(find,sizeof(find));int32_t f=s->binding.fsys.find_first(pattern,0x80,find);uint32_t visited=0;while(!f){if(++visited>AF_MEDIA_SCAN_MAX){result=AF_MEDIA_CAPACITY;goto finish;}AfMediaEntry e;AfFsys406Details d;result=decode(find,&e,&d,s->binding.utf8_policy!=0);if(result<0)goto finish;if(result){if(work->count==AF_MEDIA_MAX){result=AF_MEDIA_CAPACITY;goto finish;}for(uint32_t i=0;i<work->count;++i)if(equal(e.name,work->entries[i].name,sizeof(e.name))||(d.alias[0]&&equal(d.alias,details[i].alias,sizeof(d.alias)))){result=AF_INVALID;goto finish;}work->entries[work->count]=e;details[work->count++]=d;}f=s->binding.fsys.find_next(find);}if(f!=2){result=AF_IO;goto finish;}result=current(s,record);if(result)goto finish;result=policy(s);if(result)goto finish;for(uint32_t i=1;i<work->count;++i){AfMediaEntry e=work->entries[i];AfFsys406Details d=details[i];uint32_t j=i;while(j&&before(e.name,work->entries[j-1].name)){work->entries[j]=work->entries[j-1];details[j]=details[j-1];--j;}work->entries[j]=e;details[j]=d;}s->listing=*work;copy(s->record,record,sizeof(record));copy(s->details,details,work->count*sizeof(*details));*output=*work;result=AF_OK;finish:s->busy=0;return result;}
static int read_pass(AfFsys406 *s,const AfMediaEntry *e,const AfFsys406Details *d,uint8_t *source,int verify,AfGridProgress progress,void *user){char file[256];uint8_t block[1024];uint64_t handle=0;size_t at=0;int r=current(s,s->record);if(r)return r;r=exact(s,s->record,e,d);if(r)return r;r=path(s->record,d->alias[0]?d->alias:e->name,file);if(r)return r;int32_t opened=s->binding.fsys.open(file,&handle,1);if(opened||!handle)return AF_IO;while(at<e->size){size_t wanted=(size_t)e->size-at;size_t limit=verify?sizeof(block):16384;if(wanted>limit)wanted=limit;void *dst=verify?(void *)block:source+at;int32_t n=s->binding.fsys.read(handle,dst,(int32_t)wanted);if(n<=0||n>(int32_t)wanted){r=AF_IO;break;}if(verify&&!equal(block,source+at,(size_t)n)){r=AF_STALE;break;}at+=(size_t)n;if(progress&&progress(user,verify?(uint32_t)e->size:(uint32_t)at,(uint32_t)e->size)){r=AF_GRID_CANCELLED;break;}}if(!r){uint8_t extra;int32_t n=s->binding.fsys.read(handle,&extra,1);if(n!=0)r=n<0?AF_IO:AF_STALE;}if(s->binding.fsys.close(handle)&&!r)r=AF_IO;if(r)return r;r=current(s,s->record);return r?r:exact(s,s->record,e,d);}
int af_fsys406_read(void *context,const AfMediaList *list,uint32_t index,void *source,size_t capacity,AfMediaSource *metadata,AfGridProgress progress,void *user){AfFsys406 *s=context;if(!s||s->initialized!=READY||!apart(s,sizeof(*s),list,sizeof(*list))||!apart(s,sizeof(*s),source,capacity)||!apart(s,sizeof(*s),metadata,sizeof(*metadata))||!apart(list,sizeof(*list),source,capacity)||!apart(list,sizeof(*list),metadata,sizeof(*metadata))||!apart(source,capacity,metadata,sizeof(*metadata))||!policy_apart(s,source,capacity)||!policy_apart(s,metadata,sizeof(*metadata)))return AF_INVALID;if(s->busy)return AF_BUSY;if(!list->generation||list->count>AF_MEDIA_MAX||index>=list->count||!equal(list,&s->listing,sizeof(*list)))return AF_STALE;const AfMediaEntry *e=&s->listing.entries[index];if(e->size>capacity)return AF_MEDIA_CAPACITY;s->busy=1;int r=policy(s);AfMediaSource next;zero(&next,sizeof(next));if(!r&&progress&&progress(user,0,(uint32_t)e->size))r=AF_GRID_CANCELLED;if(!r)r=read_pass(s,e,&s->details[index],source,0,progress,user);if(!r&&af_sha256(source,(size_t)e->size,next.sha256))r=AF_INVALID;if(!r)r=read_pass(s,e,&s->details[index],source,1,progress,user);if(!r&&progress&&progress(user,(uint32_t)e->size,(uint32_t)e->size))r=AF_GRID_CANCELLED;if(!r)r=policy(s);if(!r){uint8_t final_sha[32];if(af_sha256(source,(size_t)e->size,final_sha))r=AF_INVALID;else if(!equal(final_sha,next.sha256,sizeof(final_sha)))r=AF_STALE;}if(!r){next.bytes=(uint32_t)e->size;*metadata=next;}s->busy=0;return r;}

/* 仅核对已由外层证明完整映射且驻留的同包库，不探测任何地址。 */
int af_fsys406_utf8_policy(uintptr_t base,size_t span){
    if(!base||(base&4095u)||span!=AF_FSYS406_LIBRARY_SPAN||base>UINTPTR_MAX-span)return AF_INVALID;
    static const uint8_t code0[16]={0xfd,0x7b,0xbd,0xa9,0x02,0xe7,0x84,0xd2,0xfd,0x03,0x00,0x91,0xf3,0x53,0x01,0xa9};
    if(!equal((const void *)(base+0x843bcu),code0,sizeof(code0)))return AF_STALE;
    static const uint8_t code1[16]={0xfd,0x7b,0xbd,0xa9,0xfd,0x03,0x00,0x91,0xf3,0x53,0x01,0xa9,0xb3,0x01,0x00,0x90};
    if(!equal((const void *)(base+0x85688u),code1,sizeof(code1)))return AF_STALE;
    static const uint8_t code2[16]={0x02,0x00,0x40,0x39,0x03,0x04,0x00,0x91,0xa2,0x01,0x38,0x36,0x5f,0x7c,0x03,0x71};
    if(!equal((const void *)(base+0x9445cu),code2,sizeof(code2)))return AF_STALE;
    static const uint8_t code3[16]={0x02,0x00,0x40,0x79,0xe6,0xff,0x9a,0x12,0x04,0x08,0x00,0x91,0x43,0x00,0x06,0x0b};
    if(!equal((const void *)(base+0x945c4u),code3,sizeof(code3)))return AF_STALE;
    static const uint8_t code4[16]={0xfd,0x7b,0xbe,0xa9,0xfd,0x03,0x00,0x91,0xa1,0x63,0x00,0x91,0x12,0x47,0xfe,0x97};
    if(!equal((const void *)(base+0x946ecu),code4,sizeof(code4)))return AF_STALE;
    static const uint8_t code5[16]={0x3f,0x04,0x00,0x71,0x00,0x1c,0x00,0x53,0xc0,0x00,0x00,0x54,0x61,0x00,0x00,0x34};
    if(!equal((const void *)(base+0x94714u),code5,sizeof(code5)))return AF_STALE;
    static const uint8_t code6[16]={0xfd,0x7b,0xbe,0xa9,0xfd,0x03,0x00,0x91,0xa1,0x63,0x00,0x91,0xa1,0x3f,0xfe,0x97};
    if(!equal((const void *)(base+0x94750u),code6,sizeof(code6)))return AF_STALE;
    static const uint8_t code7[8]={0x00,0x00,0x80,0x52,0xc0,0x03,0x5f,0xd6};
    if(!equal((const void *)(base+0x94778u),code7,sizeof(code7)))return AF_STALE;
    uintptr_t module=base+0xd4418u;
    if(u64((const uint8_t *)(base+0xb9e68u))!=module||u32((const uint8_t *)module)!=1u)return AF_STALE;
    static const uint32_t converter[6]={0x9445cu,0x945c4u,0x946ecu,0x94714u,0x94750u,0x94778u};
    for(unsigned i=0;i<6;++i)if(u64((const uint8_t *)(module+0x18u+8u*i))!=base+converter[i])return AF_STALE;
    return AF_OK;
}
