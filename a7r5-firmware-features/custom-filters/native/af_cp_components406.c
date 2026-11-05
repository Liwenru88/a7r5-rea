/* 只在真实worker的租约视图内叠加；原函数始终完整执行，失败沿原厂输出。 */
#include "af_cp_components406.h"
#include "af_color406.h"
#include "af_joint.h"
#ifdef AF_CP_CAPTURE406
#include "af_cp_capture406.h"
#endif

static uint32_t word(const void *p){const uint8_t *b=p;return (uint32_t)b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;}
static void put(void *p,uint32_t n){uint8_t *b=p;for(unsigned i=0;i<4;++i)b[i]=(uint8_t)(n>>(8*i));}
static void copy(void *a,const void *b,size_t n){uint8_t *d=a;const uint8_t *s=b;for(size_t i=0;i<n;++i)d[i]=s[i];}
static int same(const void *a,const void *b,size_t n){const uint8_t *x=a,*y=b;for(size_t i=0;i<n;++i)if(x[i]!=y[i])return 0;return 1;}
static int separate(const void *a,size_t n,const void *b,size_t m){uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);}
size_t af_cp_components406_bytes(void){return sizeof(AfCpComponents406);}
static int get(AfCpComponents406 *,uint32_t,AfCpJobs406View *);
static void handoff_tone(AfCpGamma406Tone *t,const AfCpJobs406View *v,uint32_t epoch){
    t->version=v->input.version;t->input_source=v->input.source;t->input_epoch=v->input.epoch;
    t->snapshot_epoch=v->input.origin_snapshot_epoch;t->slot=v->input.slot;t->ticket=v->ticket;
    t->source_epoch=epoch;t->reserved=0;copy(t->tone,v->asset->native_tone,sizeof(t->tone));
}
static int handoff_matches(const AfCpGamma406Tone *t,const AfCpJobs406View *v){
    return t->version==v->input.version&&t->input_source==v->input.source&&t->input_epoch==v->input.epoch&&
        t->snapshot_epoch==v->input.origin_snapshot_epoch&&t->slot==v->input.slot&&t->ticket==v->ticket&&
        same(t->tone,v->asset->native_tone,sizeof(t->tone));
}
/* 仅保护小身份记录，不跨原调用持锁，不等待、不调用RTOS锁或保留asset引用。
 * 原写者争用不能安全串行化时关闭伴随身份；原厂写入仍完整执行。 */
static int handoff_lock(AfCpComponents406 *s,int writer){
    uint32_t zero=0;
    if(!__atomic_compare_exchange_n(&s->gamma_handoff.guard,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED)){
        if(writer)__atomic_store_n(&s->gamma_handoff.fault,1,__ATOMIC_RELEASE);
        return 0;
    }
    return 1;
}
static void handoff_unlock(AfCpComponents406 *s){__atomic_store_n(&s->gamma_handoff.guard,0,__ATOMIC_RELEASE);}
static int handoff_fault(AfCpComponents406 *s){return __atomic_load_n(&s->gamma_handoff.fault,__ATOMIC_ACQUIRE)!=0;}
static uint32_t source_begin(AfCpComponents406 *s,int reset){
    uint32_t epoch=0;
    if(!handoff_lock(s,1))return 0;
    s->gamma_handoff.source_ready=0;
    s->gamma_handoff.identity_ready=0;
    if(reset)s->gamma_handoff.shadow_ready=0;
    if(s->gamma_handoff.building||s->gamma_handoff.epoch==UINT32_MAX)
        __atomic_store_n(&s->gamma_handoff.fault,1,__ATOMIC_RELEASE);
    if(!handoff_fault(s)){
        epoch=++s->gamma_handoff.epoch;s->gamma_handoff.building=1;
    }
    handoff_unlock(s);return epoch;
}
static void source_end(AfCpComponents406 *s,uint32_t epoch,const AfCpJobs406View *v){
    if(!handoff_lock(s,1))return;
    if(epoch&&s->gamma_handoff.epoch==epoch){
        s->gamma_handoff.building=0;
        if(v&&!handoff_fault(s)){
            handoff_tone(&s->gamma_handoff.source,v,epoch);s->gamma_handoff.identity_ready=1;
        }
    }
    handoff_unlock(s);
}
uint32_t af_cp_components406_gamma_source(AfCpComponents406 *s,const void *p){
    if(!s||!s->ports.gamma_source)return 0;
    AfCpJobs406View v;int qualified=get(s,2,&v)&&s->ports.current(s->ports.context,&v)==AF_OK;
    uint32_t epoch=source_begin(s,0),result=s->ports.gamma_source(s->ports.context,p);
    if(qualified&&s->ports.current(s->ports.context,&v)!=AF_OK)qualified=0;
    source_end(s,epoch,qualified?&v:0);return result;
}
uint32_t af_cp_components406_gamma_reset(AfCpComponents406 *s,const void *p){
    if(!s||!s->ports.gamma_reset)return 0;
#ifdef AF_CP_CAPTURE406
    /* 原AA6412也清第二域两套formatter/输出，必须在原写入前撤销在途scope。 */
    af_cp_capture406_reset_target();
#endif
    uint32_t epoch=source_begin(s,1),result=s->ports.gamma_reset(s->ports.context,p);
    source_end(s,epoch,0);return result;
}
static uint32_t gamma_handoff_begin(AfCpComponents406 *s){
    uint32_t epoch=0;
    if(!handoff_lock(s,1))return 0;
    s->gamma_handoff.source_ready=0;
    if(s->gamma_handoff.epoch==UINT32_MAX)__atomic_store_n(&s->gamma_handoff.fault,1,__ATOMIC_RELEASE);
    if(!handoff_fault(s)&&!s->gamma_handoff.building&&s->gamma_handoff.identity_ready&&s->gamma_handoff.epoch)epoch=++s->gamma_handoff.epoch;
    handoff_unlock(s);return epoch;
}
static void gamma_handoff_publish(AfCpComponents406 *s,uint32_t epoch,
    const AfCpJobs406View *v,const uint8_t image[84]){
    if(!epoch||!handoff_lock(s,1))return;
    if(!handoff_fault(s)&&!s->gamma_handoff.building&&s->gamma_handoff.identity_ready&&
       s->gamma_handoff.epoch==epoch&&handoff_matches(&s->gamma_handoff.source,v)){
        AfCpGamma406Tone *t=&s->gamma_handoff.source;
        handoff_tone(t,v,epoch);copy(s->gamma_handoff.image,image,84);
        s->gamma_handoff.source_ready=1;
    }
    handoff_unlock(s);
}
int af_cp_components406_gamma_copy(AfCpComponents406 *s,void *d,const void *p,size_t n,
    uint32_t destination,uint32_t source,uint32_t lr){
    AfCpGamma406Tone tone;uint8_t image[84];uint32_t epoch=0;int result=AF_EMPTY,claimed=0;
    if(!s||!s->ports.copy)return AF_INVALID;
    int exact=d&&p&&destination==AF_CP_COMPONENTS406_SHADOW&&source==AF_CP_COMPONENTS406_SOURCE&&
        n==84&&lr==AF_CP_COMPONENTS406_SHADOW_LR&&separate(d,n,s,sizeof(*s))&&separate(p,n,s,sizeof(*s));
    if(destination==AF_CP_COMPONENTS406_SHADOW&&handoff_lock(s,1)){
        s->gamma_handoff.shadow_ready=0;
        if(s->gamma_handoff.shadow_busy)__atomic_store_n(&s->gamma_handoff.fault,1,__ATOMIC_RELEASE);
        else{s->gamma_handoff.shadow_busy=1;claimed=1;}
        if(exact&&!handoff_fault(s)&&!s->gamma_handoff.building&&s->gamma_handoff.source_ready){
            epoch=s->gamma_handoff.epoch;copy(&tone,&s->gamma_handoff.source,sizeof(tone));
            copy(image,s->gamma_handoff.image,84);
        }
        handoff_unlock(s);
    }
    /* 拒绝、构造在途及版本竞争均不省略或重试原copy。 */
    s->ports.copy(s->ports.context,d,p,n);
    if(!handoff_lock(s,1))return AF_BUSY;
    if(claimed)s->gamma_handoff.shadow_busy=0;
    if(!exact){handoff_unlock(s);return AF_INVALID;}
    if(epoch){
        result=AF_STALE;
        if(!handoff_fault(s)&&!s->gamma_handoff.building&&s->gamma_handoff.source_ready&&
           s->gamma_handoff.epoch==epoch&&same(&tone,&s->gamma_handoff.source,sizeof(tone))&&
           same(image,p,84)&&same(image,d,84)){
            copy(&s->gamma_handoff.shadow,&tone,sizeof(tone));copy(s->gamma_handoff.shadow_image,image,84);
            s->gamma_handoff.shadow_ready=1;result=AF_OK;
        }
    }
    handoff_unlock(s);return result;
}
int af_cp_components406_gamma_shadow(AfCpComponents406 *s,AfCpGamma406Tone *out){
    int result=AF_EMPTY;
    if(!s||!out||!separate(out,sizeof(*out),s,sizeof(*s)))return AF_INVALID;
    if(!handoff_lock(s,0))return AF_BUSY;
    if(!handoff_fault(s)&&s->gamma_handoff.shadow_ready){copy(out,&s->gamma_handoff.shadow,sizeof(*out));result=AF_OK;}
    handoff_unlock(s);return result;
}
int af_cp_components406_gamma_snapshot(AfCpComponents406 *s,AfCpGamma406Tone *out,uint8_t image[84]){
    AfCpGamma406Tone tone;uint8_t expected[84],actual[84];int result=AF_EMPTY;
    if(!s||!s->ports.read||!separate(out,sizeof(*out),s,sizeof(*s))||!separate(image,84,s,sizeof(*s))||
       !separate(out,sizeof(*out),image,84))return AF_INVALID;
    if(!handoff_lock(s,0))return AF_BUSY;
    if(!handoff_fault(s)&&s->gamma_handoff.shadow_ready&&!s->gamma_handoff.shadow_busy){
        copy(&tone,&s->gamma_handoff.shadow,sizeof(tone));copy(expected,s->gamma_handoff.shadow_image,84);result=AF_OK;
    }
    handoff_unlock(s);if(result)return result;
    if(s->ports.read(s->ports.context,AF_CP_COMPONENTS406_SHADOW,actual,84)!=AF_OK)return AF_IO;
    if(!handoff_lock(s,0))return AF_BUSY;
    if(handoff_fault(s)||s->gamma_handoff.shadow_busy||!s->gamma_handoff.shadow_ready||
       !same(&tone,&s->gamma_handoff.shadow,sizeof(tone))||
       !same(expected,s->gamma_handoff.shadow_image,84)||!same(expected,actual,84))result=AF_STALE;
    else{copy(out,&tone,sizeof(tone));copy(image,expected,84);}
    handoff_unlock(s);return result;
}
int af_cp_components406_init(AfCpComponents406 *s,const AfCpComponents406Ports *p){
    if(!s||!p||!separate(s,sizeof(*s),p,sizeof(*p))||s->ports.view||s->gamma_busy||
       !p->view||!p->current||!p->read||!p->matrix||!p->cc1||!p->gamma||!p->gamma_record)return AF_INVALID;
    copy(&s->ports,p,sizeof(*p));return AF_OK;
}
static int get(AfCpComponents406 *s,uint32_t identity,AfCpJobs406View *v){
    return s&&s->ports.view&&s->ports.current&&s->ports.read&&
        s->ports.view(s->ports.context,identity,v)==AF_OK&&v->identity==identity&&
        v->asset&&v->asset==v->lease.asset&&v->asset->native_mode==1&&
        v->input.version&&v->input.version==v->lease.version&&v->prefix&&
        !word(v->prefix+0x238)&&v->input.actual.base==v->asset->base;
}
int af_cp_components406_prepare(AfCpComponents406 *s,uint32_t identity){
    AfCpJobs406View v;
    if(identity!=2&&identity!=3)return AF_EMPTY;
    if(!get(s,identity,&v))return AF_EMPTY;
    /* 已准入照片路线还要求source238为0；此字段本身不证明照片身份，
     * 实际组件仍核原mode/profile/主formatter，非零时沿原厂规则。
     * 原id3正常dispatch固定调用719EF6→231EB8/71D37C，不按八值相等跳过。
     * 原0/1/20等旁路不会为了私有配方被强改成另一运行状态。 */
    if(word(v.prefix+0x238))return AF_EMPTY;
    return s->ports.current(s->ports.context,&v);
}
int af_cp_components406_shot_after(AfCpComponents406 *s,void *actual,uint32_t destination,
    uint32_t source,size_t n,uint32_t lr){
    AfCpJobs406View v;uint8_t a,b,old,next=0;int private_run;
    if(!s||!actual||destination!=AF_CP_COMPONENTS406_SHOT||source!=AF_CP_COMPONENTS406_SHOT_BASELINE||
       n!=AF_CP_COMPONENTS406_SHOT_BYTES||lr!=AF_CP_COMPONENTS406_SHOT_COPY_LR||
       !s->ports.worker||!s->ports.read||!separate(actual,n,s,sizeof(*s)))return AF_INVALID;
    if(s->ports.worker(s->ports.context,2)!=AF_OK)return AF_EMPTY;
    private_run=get(s,2,&v);
    if(!private_run&&!s->gamma_private_mask)return AF_EMPTY;
    /* 85914A..16E按shot+D03选第1参数1F0D2F0的两个actual来源。
     * 同时与两者不同，避免猜测本次模式；不写第2参数的共享aux+6A。 */
    if(s->ports.read(s->ports.context,0x1f0dd80u,&a,1)!=AF_OK||
       s->ports.read(s->ports.context,0x1f0ddb2u,&b,1)!=AF_OK)return AF_IO;
    if(private_run&&s->ports.current(s->ports.context,&v)!=AF_OK)return AF_STALE;
    while(next==a||next==b)++next;
    old=((uint8_t *)actual)[0x920];((uint8_t *)actual)[0x920]=next;
    if(private_run&&s->ports.current(s->ports.context,&v)!=AF_OK){((uint8_t *)actual)[0x920]=old;return AF_STALE;}
    return AF_OK;
}
static int read_word(AfCpComponents406 *s,uint32_t address,uint32_t *out){
    uint8_t b[4];if(s->ports.read(s->ports.context,address,b,4)!=AF_OK)return 0;*out=word(b);return 1;
}
/* root[0]是operation，operation+4才是C4；绝不把root+4校准对象当C4。 */
static int root_matches(AfCpComponents406 *s,const AfCpJobs406View *v,const void *root){
    uint32_t operation,c4,prefix;
    if(!root)return 0;operation=word(root);
    return operation&&operation<=UINT32_MAX-8&&read_word(s,operation+4,&c4)&&c4==v->c4_address&&
        read_word(s,c4,&prefix)&&prefix==v->prefix_address&&
        s->ports.current(s->ports.context,v)==AF_OK;
}
static int output_ok(AfCpComponents406 *s,const AfCpJobs406View *v,const void *out,size_t n){
    return separate(out,n,s,sizeof(*s))&&separate(out,n,v->asset,sizeof(*v->asset))&&
        separate(out,n,v->prefix,AF_CP_INPUT406_COPY_BYTES);
}
typedef struct {
    const AfCpRuntimeAsset406 *asset;
    uint32_t capture;
    union {AfCpJobs406View native;
#ifdef AF_CP_CAPTURE406
        AfCpCaptureColor406View color;
#endif
    } view;
} ColorSource;
#ifdef AF_CP_CAPTURE406
/* Capture局部operation不是C4；来源由独立request/R-copy scope授予。 */
static int capture_root(AfCpComponents406 *s,const AfCpCaptureColor406View *v,const void *root){
    uint8_t operation[12];uint32_t a;
    return root&&(a=word(root))&&a<=UINT32_MAX-sizeof(operation)&&
        s->ports.read(s->ports.context,a,operation,sizeof(operation))==AF_OK&&
        operation[1]==1&&!word(operation+4)&&word(operation+8)==v->token.a+0x20u&&
        af_cp_capture406_color_current_target(v)==AF_OK;
}
#endif
static int color_source(AfCpComponents406 *s,void *root,ColorSource *source){
    source->capture=0;
    if(get(s,3,&source->view.native)&&root_matches(s,&source->view.native,root)){
        source->asset=source->view.native.asset;return 1;
    }
#ifdef AF_CP_CAPTURE406
    if(s&&s->ports.read&&af_cp_capture406_color_view_target(&source->view.color)==AF_OK&&
       source->view.color.asset&&source->view.color.asset->native_mode==1&&
       capture_root(s,&source->view.color,root)){
        source->capture=1;source->asset=source->view.color.asset;return 1;
    }
#endif
    return 0;
}
static int color_current(AfCpComponents406 *s,const ColorSource *source,void *root){
#ifdef AF_CP_CAPTURE406
    if(source->capture)return capture_root(s,&source->view.color,root);
#endif
    return root_matches(s,&source->view.native,root);
}
static int color_output(AfCpComponents406 *s,const ColorSource *source,void *out,size_t n){
#ifdef AF_CP_CAPTURE406
    if(source->capture)return separate(out,n,s,sizeof(*s))&&
        separate(out,n,source->asset,sizeof(*source->asset))&&
        separate(out,n,source->view.color.preset,sizeof(*source->view.color.preset));
#endif
    return output_ok(s,&source->view.native,out,n);
}
/* 原232FE0正常外观映射；函数profile不是AfPreset.base。单色矩阵另走
 * 71ECCC的9项构造，不能借本27项端点施加增量。ST的49变体还须核原模式。 */
static int color_profile(AfCpComponents406 *s,const ColorSource *source,const void *root,
                         uint32_t profile,int matrix){
    static const uint8_t profiles[19]={0,6,2,1,42,41,43,44,53,53,
                                     255,255,255,255,255,255,255,54,55};
    uint32_t base=source->asset->base;
    if(base>=sizeof(profiles)||profiles[base]==255||(matrix&&profiles[base]==53))return 0;
    if(base)return profile==profiles[base];
    uint32_t operation=word(root);uint8_t mode;
    return operation&&operation<=UINT32_MAX-0x34u&&
        s->ports.read(s->ports.context,operation+0x34u,&mode,1)==AF_OK&&
        profile==(mode==3?49u:0u);
}
uint32_t af_cp_components406_matrix(AfCpComponents406 *s,void *out,uint32_t sector,void *root,uint32_t profile){
    ColorSource source;int16_t delta[27],result[27];
    int allowed=color_source(s,root,&source)&&color_profile(s,&source,root,profile,1)&&color_output(s,&source,out,54);
    if(!s||!s->ports.matrix)return 0;
    uint32_t native=s->ports.matrix(s->ports.context,out,sector,root,profile);
    if(allowed&&af_cp_runtime_asset406_matrix(source.asset,sector,delta)==AF_OK&&
       af_color406_add(out,delta,27,result)==AF_OK&&color_current(s,&source,root)&&
       color_profile(s,&source,root,profile,1))copy(out,result,54);
    return native;
}
uint32_t af_cp_components406_cc1(AfCpComponents406 *s,void *out,uint32_t profile,void *root){
    ColorSource source;int16_t result[24];
    int allowed=color_source(s,root,&source)&&color_profile(s,&source,root,profile,0)&&color_output(s,&source,out,48);
    if(!s||!s->ports.cc1)return 0;
    uint32_t native=s->ports.cc1(s->ports.context,out,profile,root);
    if(allowed)for(unsigned i=0;i<24;++i)if(source.asset->recipe.cc1[i]<-1024||source.asset->recipe.cc1[i]>1024)allowed=0;
    if(allowed&&af_color406_add(out,source.asset->recipe.cc1,24,result)==AF_OK&&color_current(s,&source,root)&&
       color_profile(s,&source,root,profile,0))copy(out,result,48);
    return native;
}
static int matrix9_profile(AfCpComponents406 *s,const void *root){
    uint32_t calibration=word((const uint8_t *)root+4);uint8_t profile;
    return calibration&&calibration<=UINT32_MAX-0x25u&&
        s->ports.read(s->ports.context,calibration+0x25u,&profile,1)==AF_OK&&profile==53;
}
uint32_t af_cp_components406_matrix9(AfCpComponents406 *s,void *out,const void *src,void *root,
                                    uint32_t sector,AfCpComponents406Matrix9 original){
    ColorSource source;int16_t delta[27],result[9];
    if(!original)return 0;
    int allowed=sector<16&&color_source(s,root,&source)&&
        (source.asset->base==8||source.asset->base==9)&&color_profile(s,&source,root,53,0)&&
        matrix9_profile(s,root)&&color_output(s,&source,out,18)&&separate(out,18,src,18)&&
        af_joint_matrix_native406_representable(source.asset->base,source.asset->matrix_mode,
            source.asset->recipe.matrix,source.asset->sector_matrix)==AF_OK;
    uint32_t native=original(out,src);
    if(allowed&&af_cp_runtime_asset406_matrix(source.asset,sector,delta)==AF_OK&&
       same(delta,delta+9,18)&&same(delta,delta+18,18)){
        /* 与原增量端点一致的半字算术；仅写9项，不借54B接口越界读写。 */
        for(unsigned i=0;i<9;++i){
            uint32_t value=(uint32_t)((int32_t)((const int16_t *)out)[i]+delta[i])&65535u;
            result[i]=(int16_t)(value<32768u?(int32_t)value:(int32_t)value-65536);
        }
        if(color_current(s,&source,root)&&matrix9_profile(s,root))copy(out,result,18);
    }
    return native;
}
static int gamma_bank(AfCpComponents406 *s,uint32_t mode,uint32_t params,const void *out){
    uint32_t address;
    if(mode||params!=AF_CP_COMPONENTS406_FORMATTER||!s->ports.worker||
       s->ports.worker(s->ports.context,2)!=AF_OK||!s->ports.address||
       s->ports.address(s->ports.context,out,AF_CP_COMPONENTS406_GAMMA_PACKED_BYTES,&address)!=AF_OK)return -1;
    return address==AF_CP_COMPONENTS406_GAMMA_PACKED0?0:address==AF_CP_COMPONENTS406_GAMMA_PACKED1?1:-1;
}
static int gamma_output_valid(const void *out){
    const uint8_t *p=(const uint8_t *)out+0x24c;uint32_t previous=0;
    for(unsigned i=0;i<129;++i){uint32_t y=word(p+4*i);if(y>0x3ffffu||(i?y<previous:y!=0))return 0;previous=y;}
    return previous!=0;
}
static uint32_t gamma_native(AfCpComponents406 *s,uint32_t mode,const void *params,void *out,int bank){
    uint32_t result=s->ports.gamma(s->ports.context,mode,params,out);
    /* 固定stock CFG的正常return必经五个完整129点写循环之一，原stock实际
     * 返回才是覆盖事件；数值检查只是额外保守条件，不是覆盖发生的证明。
     * 不把query、dirty、私有版本或原模式未构造视作原厂恢复。 */
    if(bank>=0&&gamma_output_valid(out))s->gamma_private_mask&=~(1u<<(unsigned)bank);
    return result;
}
/* 修改4.06继承的FL2/FL3记录不全在普通RO段：只接受原选表的精确位置，
 * 不放开整块RAM或helper代码区。实际曲线仍由原表选出、原core构造。 */
static int gamma_record_source(uint32_t route,uint32_t column,uint32_t record){
    if(route>=51u||column>=7u||(record&3u))return 0;
    if(record>=AF_CP_COMPONENTS406_RO_BEGIN&&record<=AF_CP_COMPONENTS406_RO_END-576u)return 1;
    if(route==47u)return record==(column==6u?0x1a39dbcu:0x1195080u);
    if(route==48u)return record==(column==6u?0xbefdc0u:0xbefb80u);
    return 0;
}
#ifdef AF_CP_CAPTURE406
static uint32_t gamma_capture(AfCpComponents406 *s,const void *params,uint32_t address,void *out){
    AfCpCapture406Token token;AfCpGamma406Tone tone;
    uint8_t formatter[AF_CP_CAPTURE406_FORMATTER_BYTES],after[AF_CP_CAPTURE406_FORMATTER_BYTES];
    uint32_t out_address=0,route,column,record,result;
    if(!params||!out||!s->ports.address||!s->ports.gamma_record||
       s->ports.address(s->ports.context,out,AF_CP_COMPONENTS406_GAMMA_PACKED_BYTES,&out_address)!=AF_OK||
       af_cp_capture406_read_target(address,out_address,&tone,&token,formatter)!=AF_OK||
       !separate(params,sizeof(formatter),s,sizeof(*s))||!separate(out,AF_CP_COMPONENTS406_GAMMA_PACKED_BYTES,s,sizeof(*s))||
       __atomic_exchange_n(&s->gamma_busy,1,__ATOMIC_ACQUIRE))return gamma_native(s,1,params,out,-1);
    route=word(formatter+0x30);column=formatter[0x38];
    if(route>=51||column>=7||!read_word(s,AF_CP_COMPONENTS406_GAMMA_TABLE+route*28+column*4,&record)||
       !gamma_record_source(route,column,record)||
       s->ports.read(s->ports.context,record,s->original,576)!=AF_OK)goto original_capture;
    for(unsigned i=0;i<129;++i)s->gamma_before[i]=word(s->original+4*i);
    if(af_joint_gamma_work(s->gamma_before,tone.tone,s->gamma_work,s->gamma_after)!=AF_OK||
       af_cp_capture406_current_target(&token)!=AF_OK)goto original_capture;
    copy(s->adjusted,s->original,576);
    for(unsigned i=0;i<129;++i)put(s->adjusted+4*i,s->gamma_after[i]);
    put(s->adjusted+0x220,s->gamma_after[128]);
    /* 仍经原选表记录进入真实core；返回到原413DF0后处理，不重写最终bank。 */
    result=s->ports.gamma_record(s->ports.context,1,params,out,s->adjusted);
    if(af_cp_capture406_current_target(&token)!=AF_OK||
       s->ports.read(s->ports.context,address,after,sizeof(after))!=AF_OK||!same(formatter,after,sizeof(after)))
        result=gamma_native(s,1,params,out,-1);
    __atomic_store_n(&s->gamma_busy,0,__ATOMIC_RELEASE);return result;
original_capture:
    __atomic_store_n(&s->gamma_busy,0,__ATOMIC_RELEASE);return gamma_native(s,1,params,out,-1);
}
#endif
uint32_t af_cp_components406_gamma(AfCpComponents406 *s,uint32_t mode,const void *params,uint32_t address,void *out){
    AfCpJobs406View v;uint32_t route,column,record,handoff_epoch=0;uint8_t source_image[84];
    if(!s||!s->ports.gamma)return 0;
#ifdef AF_CP_CAPTURE406
    if(mode==1)return gamma_capture(s,params,address,out);
#endif
    int bank=out?gamma_bank(s,mode,address,out):-1;
    if(bank>=0)handoff_epoch=gamma_handoff_begin(s);
    if(mode||!params||!out||bank<0||!get(s,2,&v)||
       !output_ok(s,&v,out,AF_CP_COMPONENTS406_GAMMA_PACKED_BYTES)||!separate(params,0x4e,s,sizeof(*s))||
       __atomic_exchange_n(&s->gamma_busy,1,__ATOMIC_ACQUIRE))
        return gamma_native(s,mode,params,out,bank);
    /* AA843E..84A4核普通route<51；旧六51..62仍由旧outer独立处理。
     * AA831C所写route来自原双列表，不能用Creative Look wire推算。 */
    route=word((const uint8_t *)params+0x30);column=((const uint8_t *)params)[0x38];
    if(route>=51||column>=7||!read_word(s,AF_CP_COMPONENTS406_GAMMA_TABLE+route*28+column*4,&record)||
       !gamma_record_source(route,column,record)||
       s->ports.read(s->ports.context,record,s->original,576)!=AF_OK)goto original;
    for(unsigned i=0;i<129;++i)s->gamma_before[i]=word(s->original+4*i);
    if(af_joint_gamma_work(s->gamma_before,v.asset->native_tone,s->gamma_work,s->gamma_after)!=AF_OK||
       s->ports.current(s->ports.context,&v)!=AF_OK)goto original;
    copy(s->adjusted,s->original,576);
    for(unsigned i=0;i<129;++i)put(s->adjusted+4*i,s->gamma_after[i]);
    put(s->adjusted+0x220,s->gamma_after[128]);
    if(handoff_epoch&&s->ports.read(s->ports.context,AF_CP_COMPONENTS406_SOURCE,source_image,84)!=AF_OK)handoff_epoch=0;
    {
        uint32_t result=s->ports.gamma_record(s->ports.context,mode,params,out,s->adjusted);
        if(s->ports.current(s->ports.context,&v)!=AF_OK)
            result=gamma_native(s,mode,params,out,bank);
        else{s->gamma_private_mask|=1u<<(unsigned)bank;gamma_handoff_publish(s,handoff_epoch,&v,source_image);}
        __atomic_store_n(&s->gamma_busy,0,__ATOMIC_RELEASE);return result;
    }
original:
    __atomic_store_n(&s->gamma_busy,0,__ATOMIC_RELEASE);
    return gamma_native(s,mode,params,out,bank);
}

static uint8_t *mapped(AfCpComponents406 *s,uint32_t a,size_t n){
    return a&&a<=UINT32_MAX-n?s->ports.map(s->ports.context,a,n):0;
}
uint32_t af_cp_components406_grid_enter(AfCpComponents406 *s,void *root,void *pipe,uint32_t *saved_lr){
    ColorSource source;uint8_t *operation,*calibration,*state,*context,*stage;
    uint32_t packed,base,stage_index,raw_address=0,index=4,free_index=4,zero=0;
    int private_run,legacy,capture=0,observed=0;
    if(!s||!s->ports.map||!s->ports.grid_query||!s->ports.grid_pack||!s->ports.grid_cleanup||!s->ports.worker||
       !root||!pipe||!saved_lr||!*saved_lr)return 0;
    /* 原主worker与Capture可跨任务；独占本次LR/暂借raw，绝不覆盖另一调用。 */
    if(!__atomic_compare_exchange_n(&s->grid.active,&zero,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return 0;
    operation=mapped(s,word(root),0x360);calibration=mapped(s,word((uint8_t *)root+4),16);
    state=mapped(s,word((uint8_t *)pipe+8),0x18a);context=mapped(s,word((uint8_t *)pipe+12),0x6b4);
    stage=mapped(s,word((uint8_t *)pipe+16),12);
    if(!operation||!calibration||!state||!context||!stage||calibration[6])goto delegate;
    stage_index=stage[11];
    if(!operation[1]&&!stage_index){if(s->ports.worker(s->ports.context,3)!=AF_OK)goto delegate;observed=1;}
#ifdef AF_CP_CAPTURE406
    else if(operation[1]==1&&!word(operation+4)&&stage_index==1){
        stage=mapped(s,word((uint8_t *)pipe+16),13);
        /* 原230DA8按native+0C重写stage；普通Capture的第二次mode6也用stage1。
         * 未核native==11或最终stage==1时不能沿默认stage3授予私有网格。 */
        if(!stage||(stage[12]!=6&&stage[12]!=11)||calibration[12]!=11)goto delegate;
        capture=1;observed=af_cp_capture406_color_scope_target(word(operation+8))==AF_OK;
    }
#endif
    else goto delegate;
    base=word(context+0x6b0);if(!base||base>UINT32_MAX-stage_index*1620u)goto delegate;
    packed=base+stage_index*1620u;if(!mapped(s,packed,1620))goto delegate;
    for(unsigned i=0;i<4;++i){if(s->grid_banks[i].packed==packed)index=i;if(!s->grid_banks[i].packed&&free_index==4)free_index=i;}
    legacy=operation[0x2e]>=249&&operation[0x2e]<=254;
    private_run=observed&&!legacy&&color_source(s,root,&source)&&source.capture==(uint32_t)capture&&
        operation[0x2f]>=1&&operation[0x2f]<=8;
    if(private_run&&(!s->ports.address||s->ports.address(s->ports.context,source.asset->recipe.grid,AF_GRID_BYTES,&raw_address)!=AF_OK||!raw_address))private_run=0;
    if(index==4){if(!private_run||free_index==4)goto delegate;index=free_index;}
    if(!private_run&&!s->grid_banks[index].private_packed)goto delegate;
    /* fault/无view时只能清已追踪的同stage packed；结构本身不授私有配方。 */
    s->grid.original_lr=*saved_lr;s->grid.raw=word(state+0x184);
    s->grid.type=state[0x188];s->grid.format=state[0x189];s->grid.state=state;s->grid.context=context;
    s->grid.bank=index;s->grid.private_run=(uint32_t)private_run;s->grid.query_result=0;
    s->grid.native_selector=(uint32_t)legacy;s->grid_banks[index].packed=packed;
    if(legacy){context[0x54+stage_index]=255;*saved_lr=s->ports.grid_cleanup;return 0;}
    if(private_run){put(state+0x184,raw_address);state[0x188]=1;state[0x189]=2;}
    context[0x54+stage_index]=255;*saved_lr=s->ports.grid_cleanup;
    uint32_t query=s->ports.grid_query(s->ports.context,root,pipe);s->grid.query_result=query;
    if(query==1){
        if(private_run&&!color_current(s,&source,root)){
            put(state+0x184,s->grid.raw);state[0x188]=s->grid.type;state[0x189]=s->grid.format;
            s->grid.private_run=0;context[0x54+stage_index]=255;
        }
        /* 原packer按stage选择base+stage*654，405个word覆盖同一原1620B段。
         * 原raw最后CPU读在2318B2；本次原controller返回前仍保持cache借用。 */
        s->ports.grid_pack(s->ports.context,root,pipe);
        s->grid_banks[index].private_packed=s->grid.private_run;return 0x230f23u;
    }
    put(state+0x184,s->grid.raw);state[0x188]=s->grid.type;state[0x189]=s->grid.format;
    context[0x54+stage_index]=255;return 0x230f63u;
delegate:
    __atomic_store_n(&s->grid.active,0,__ATOMIC_RELEASE);return 0;
}
uint32_t af_cp_components406_grid_leave(AfCpComponents406 *s){
    if(!s||!__atomic_load_n(&s->grid.active,__ATOMIC_ACQUIRE))return 0;
    uint32_t lr=s->grid.original_lr;
    if(!s->grid.native_selector){put(s->grid.state+0x184,s->grid.raw);s->grid.state[0x188]=s->grid.type;s->grid.state[0x189]=s->grid.format;}
    if(!s->grid.state[0x18])s->grid_banks[s->grid.bank].private_packed=0;
    if(!s->grid_banks[s->grid.bank].private_packed)s->grid_banks[s->grid.bank].packed=0;
    __atomic_store_n(&s->grid.active,0,__ATOMIC_RELEASE);return lr;
}

#if defined(AF_CP_COMPONENTS406_TARGET) && defined(__arm__)
static AfCpComponents406 target;
static int target_view(void *c,uint32_t id,AfCpJobs406View *v){(void)c;return af_cp_jobs406_current_target(id,v);}
static int target_current(void *c,const AfCpJobs406View *v){(void)c;return af_cp_jobs406_current_matches_target(v);}
static int target_read(void *c,uint32_t at,void *out,size_t n){(void)c;if(!at||at>UINT32_MAX-n)return AF_INVALID;copy(out,(const void *)(uintptr_t)at,n);return AF_OK;}
static uint32_t target_matrix(void *c,void *out,uint32_t sector,void *root,uint32_t profile){(void)c;return ((uint32_t(*)(void *,uint32_t,void *,uint32_t))(uintptr_t)0xbef719)(out,sector,root,profile);}
static uint32_t target_cc1(void *c,void *out,uint32_t profile,void *root){(void)c;return ((uint32_t(*)(void *,uint32_t,void *))(uintptr_t)0xbef779)(out,profile,root);}
static uint32_t target_gamma(void *c,uint32_t mode,const void *params,void *out){(void)c;return ((uint32_t(*)(uint32_t,const void *,void *))(uintptr_t)0xbef8e1)(mode,params,out);}
static uint32_t target_gamma_record(void *c,uint32_t mode,const void *params,void *out,const void *record){(void)c;return af_cp_components406_gamma_inner(mode,params,out,record);}
static uint32_t target_gamma_source(void *c,const void *p){(void)c;return ((uint32_t(*)(const void *))(uintptr_t)0xaacb17u)(p);}
static uint32_t target_gamma_reset(void *c,const void *p){(void)c;return ((uint32_t(*)(const void *))(uintptr_t)0xaa6413u)(p);}
static void target_copy(void *c,void *d,const void *p,size_t n){(void)c;((void(*)(void *,const void *,size_t))(uintptr_t)0x5f51bcu)(d,p,n);}
static void *target_map(void *c,uint32_t a,size_t n){(void)c;return a&&a<=UINT32_MAX-n?(void *)(uintptr_t)a:0;}
static uint32_t target_query(void *c,void *r,void *p){(void)c;return ((uint32_t(*)(void *,void *))(uintptr_t)0x231235)(r,p);}
static void target_pack(void *c,void *r,void *p){(void)c;((void(*)(void *,void *))(uintptr_t)0x231655)(r,p);}
static int target_address(void *c,const void *p,size_t n,uint32_t *out){(void)c;uintptr_t a=(uintptr_t)p;if(!a||a>UINT32_MAX-n)return AF_INVALID;*out=(uint32_t)a;return AF_OK;}
static int target_worker(void *c,uint32_t identity){
    uint32_t task=0,queue=0;(void)c;
    /* 两个原ABI均为ARM模式int(out_u32*)，不是猜测RTOS TLS或SVC。 */
    if((identity!=2&&identity!=3)||((int(*)(uint32_t *))(uintptr_t)0x5c88dc)(&task)||task!=(identity==2?0x55u:0x4bu)||
       ((int(*)(uint32_t *))(uintptr_t)0x5dcfdc)(&queue)||queue!=(identity==2?0x172d308u:0x16bac50u))return AF_EMPTY;
    return AF_OK;
}
int af_cp_components406_bind_target(void){static const AfCpComponents406Ports p={0,target_view,target_current,target_read,target_matrix,target_cc1,target_gamma,target_gamma_record,target_map,target_query,target_pack,(uint32_t)(uintptr_t)af_cp_components406_grid_cleanup,target_address,target_worker,target_gamma_source,target_gamma_reset,target_copy};return af_cp_components406_init(&target,&p);}
int af_cp_components406_prepare_target(uint32_t id){return af_cp_components406_prepare(&target,id);}
int af_cp_components406_shot_after_target(void *d,const void *src,size_t n,uint32_t lr){return af_cp_components406_shot_after(&target,d,(uint32_t)(uintptr_t)d,(uint32_t)(uintptr_t)src,n,lr);}
uint32_t af_cp_components406_matrix_target(void *o,uint32_t sector,void *r,uint32_t profile){return target.ports.matrix?af_cp_components406_matrix(&target,o,sector,r,profile):target_matrix(0,o,sector,r,profile);}
uint32_t af_cp_components406_cc1_target(void *o,uint32_t profile,void *r){return target.ports.cc1?af_cp_components406_cc1(&target,o,profile,r):target_cc1(0,o,profile,r);}
uint32_t af_cp_components406_matrix9_target(uint32_t out,uint32_t src,uint32_t root,uint32_t sector){
    return af_cp_components406_matrix9(&target,(void *)(uintptr_t)out,(const void *)(uintptr_t)src,
        (void *)(uintptr_t)root,sector,(AfCpComponents406Matrix9)(uintptr_t)0x71eccdu);
}
uint32_t af_cp_components406_gamma_target(uint32_t mode,const void *p,void *o){return target.ports.gamma?af_cp_components406_gamma(&target,mode,p,(uint32_t)(uintptr_t)p,o):target_gamma(0,mode,p,o);}
uint32_t af_cp_components406_gamma_source_target(const void *p){return target.ports.gamma_source?af_cp_components406_gamma_source(&target,p):target_gamma_source(0,p);}
uint32_t af_cp_components406_gamma_reset_target(const void *p){return target.ports.gamma_reset?af_cp_components406_gamma_reset(&target,p):target_gamma_reset(0,p);}
int af_cp_components406_shadow_target(AfCpGamma406Tone *tone,uint8_t image[84]){return af_cp_components406_gamma_snapshot(&target,tone,image);}
void af_cp_components406_gamma_copy_target(void *d,const void *p,size_t n,uint32_t lr){
    if(target.ports.copy)(void)af_cp_components406_gamma_copy(&target,d,p,n,(uint32_t)(uintptr_t)d,(uint32_t)(uintptr_t)p,lr);
    else target_copy(0,d,p,n);
}
uint32_t af_cp_components406_grid_enter_target(void *r,void *p,uint32_t *lr){return af_cp_components406_grid_enter(&target,r,p,lr);}
uint32_t af_cp_components406_grid_leave_target(void){return af_cp_components406_grid_leave(&target);}
#else
int af_cp_components406_bind_target(void){return AF_INVALID;}
int af_cp_components406_prepare_target(uint32_t id){(void)id;return AF_INVALID;}
int af_cp_components406_shot_after_target(void *d,const void *src,size_t n,uint32_t lr){(void)d;(void)src;(void)n;(void)lr;return AF_INVALID;}
uint32_t af_cp_components406_matrix_target(void *o,uint32_t sector,void *r,uint32_t profile){(void)o;(void)sector;(void)r;(void)profile;return 0;}
uint32_t af_cp_components406_cc1_target(void *o,uint32_t profile,void *r){(void)o;(void)profile;(void)r;return 0;}
uint32_t af_cp_components406_matrix9_target(uint32_t o,uint32_t src,uint32_t r,uint32_t sector){(void)o;(void)src;(void)r;(void)sector;return 0;}
uint32_t af_cp_components406_gamma_target(uint32_t mode,const void *p,void *o){(void)mode;(void)p;(void)o;return 0;}
uint32_t af_cp_components406_gamma_source_target(const void *p){(void)p;return 0;}
uint32_t af_cp_components406_gamma_reset_target(const void *p){(void)p;return 0;}
int af_cp_components406_shadow_target(AfCpGamma406Tone *tone,uint8_t image[84]){(void)tone;(void)image;return AF_EMPTY;}
void af_cp_components406_gamma_copy_target(void *d,const void *p,size_t n,uint32_t lr){(void)d;(void)p;(void)n;(void)lr;}
uint32_t af_cp_components406_grid_enter_target(void *r,void *p,uint32_t *lr){(void)r;(void)p;(void)lr;return 0;}
uint32_t af_cp_components406_grid_leave_target(void){return 0;}
#endif
