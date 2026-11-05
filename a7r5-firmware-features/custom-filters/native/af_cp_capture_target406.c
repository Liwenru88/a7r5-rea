/* 固定4.06原Capture调用包装；普通堆只在首次bind分配，不在拍摄热路径分配。 */
#include "af_cp_capture406.h"
#if defined(__arm__) && defined(AF_CP_CAPTURE406)
_Static_assert(sizeof(AfCpCapture406Record)==112u,"Capture record ARM ABI");
_Static_assert(AF_CP_CAPTURE406_COUNT*sizeof(AfCpCapture406Record)==54880u,"Capture bounded heap allocation");
static AfCpCapture406 capture;
static AfCpCaptureColor406 *capture_color;
static uint32_t heap_identity;
static uint32_t heap_now(void){return *(const volatile uint32_t *)(uintptr_t)0x195e254u;}
static int heap_same(void){
    if(!heap_identity||heap_now()!=heap_identity){
        if(capture.magic)__atomic_store_n(&capture.fault,1,__ATOMIC_RELEASE);
        return 0;
    }
    return 1;
}
static int read_original(void *context,uint32_t address,void *output,size_t bytes){
    (void)context;
    if(!address||!output||address>UINT32_MAX-bytes||!heap_same())return AF_IO;
    const volatile uint8_t *p=(const volatile uint8_t *)(uintptr_t)address;
    for(size_t i=0;i<bytes;++i)((uint8_t *)output)[i]=p[i];return AF_OK;
}
static int original_thread(void *context,uint32_t *out){
    (void)context;uint32_t thread=0;
    if(((int(*)(uint32_t *))(uintptr_t)0x5c88dcu)(&thread)||!thread)return AF_IO;
    *out=thread;return AF_OK;
}
static int shadow_original(void *context,AfCpGamma406Tone *tone,uint8_t image[84]){
    (void)context;return heap_same()?af_cp_components406_shadow_target(tone,image):AF_IO;
}
static int request_original(void *context,AfCpInput406Token *token,uint32_t *id){
    (void)context;if(!heap_same())return AF_IO;
    uint32_t before=*(const volatile uint32_t *)(uintptr_t)0x163f3c8u;
    int result=af_cp_override406_read_input(AF_CP_INPUT406_REQUEST,token);
    if(result==AF_OK&&before!=*(const volatile uint32_t *)(uintptr_t)0x163f3c8u)return AF_STALE;
    if(result==AF_OK)*id=before;return result;
}
static int r_matches_original(void *context,uint32_t r,const AfPreset *expected){
    (void)context;
    static const uint8_t wire[12]={0,3,2,1,16,15,17,18,5,13,19,20};
    unsigned index=expected->base<10?expected->base:expected->base-7u;
    uint32_t profile,mode;uint8_t color[2],sharp[3];
    if(index>=12||r>UINT32_MAX-0x1ccu||
       read_original(0,r+0x104,&profile,4)!=AF_OK||
       read_original(0,r+0x150,&mode,4)!=AF_OK||
       read_original(0,r+0x108,color,2)!=AF_OK||
       read_original(0,r+0x1c9,sharp,3)!=AF_OK)return AF_IO;
    /* 原4596F4仅复制这些私有颜色字段；不虚构其余Gamma参数在R中的位置。 */
    /* 与主域prefix+238==0合同一致；旧六款及未知模式保留原厂整组。 */
    return !mode&&profile==wire[index]&&color[0]==(uint8_t)expected->params[0]&&
        color[1]==(uint8_t)expected->params[4]&&sharp[0]==(uint8_t)expected->params[5]&&
        sharp[1]==(uint8_t)expected->params[6]&&sharp[2]==(uint8_t)expected->params[7]?AF_OK:AF_STALE;
}
int af_cp_capture406_bind_target(void){
    if(capture.magic)return af_cp_capture406_target_ready()?AF_OK:AF_IO;
    uint32_t heap=heap_now();size_t records_bytes=af_cp_capture406_records_bytes();
    size_t bytes=records_bytes+af_cp_capture_color406_bytes();
    if(!heap||!bytes||bytes>65536u)return AF_EXHAUSTED;
    void *records=((void *(*)(uint32_t))(uintptr_t)0x5ef69cu)((uint32_t)bytes);
    if(!records)return AF_EXHAUSTED;
    /* 分配后的堆身份未知时禁止向可能已退出的堆free。 */
    if(heap_now()!=heap)return AF_IO;
    heap_identity=heap;
    /* 普通heap不保证零值；仅首次拥有的尾部先清零，再交opaque init检查magic。 */
    for(size_t i=records_bytes;i<bytes;++i)((uint8_t *)records)[i]=0;
    const AfCpCapture406Ports ports={0,read_original,original_thread,shadow_original};
    int result=af_cp_capture406_init(&capture,&ports,records,records_bytes);
    if(result==AF_OK){
        capture_color=(AfCpCaptureColor406 *)((uint8_t *)records+records_bytes);
        const AfCpCaptureColor406Ports color_ports={0,request_original,original_thread,r_matches_original};
        result=af_cp_capture_color406_init(capture_color,bytes-records_bytes,&color_ports);
    }
    if(result!=AF_OK){
        /* 首个对象已发布magic时保留工作区并关闭，不能留下指向已free块的状态。 */
        if(capture.magic)__atomic_store_n(&capture.fault,1,__ATOMIC_RELEASE);
        else if(heap_same())((void(*)(void *))(uintptr_t)0x5ef73cu)(records);
        capture_color=0;
    }
    return result;
}
int af_cp_capture406_target_ready(void){return heap_same()&&af_cp_capture406_ready(&capture)&&
    capture_color&&af_cp_capture_color406_ready(capture_color);}
void af_cp_capture406_reset_target(void){if(capture.magic&&heap_same())(void)af_cp_capture406_reset(&capture);}
uint32_t af_cp_capture406_birth_target(uint32_t pool){
    uint32_t a=((uint32_t(*)(uint32_t))(uintptr_t)0xae0317u)(pool);
    if(a&&af_cp_capture406_target_ready()){
        (void)af_cp_capture406_birth(&capture,a);(void)af_cp_capture_color406_a_birth(capture_color,a);
    }
    return a;
}
uint32_t af_cp_capture406_release_target(uint32_t a){
    if(af_cp_capture406_target_ready()){
        (void)af_cp_capture_color406_a_release(capture_color,a);(void)af_cp_capture406_release(&capture,a);
    }
    return ((uint32_t(*)(uint32_t))(uintptr_t)0xae0361u)(a);
}
uint32_t af_cp_capture406_pool_target(uint32_t force){
    int tracked=capture.magic&&heap_same();
    if(tracked){(void)af_cp_capture_color406_pool_reset(capture_color);(void)af_cp_capture406_pool_begin(&capture);}
    uint32_t result=((uint32_t(*)(uint32_t))(uintptr_t)0xae07e1u)(force);
    if(tracked&&heap_same())(void)af_cp_capture406_pool_end(&capture);
    return result;
}
uint32_t af_cp_capture406_rebuild_target(uint32_t a){
    AfCpCapture406Token token={0};
    if(af_cp_capture406_target_ready())(void)af_cp_capture406_write_begin(&capture,a,AF_CP_CAPTURE406_NORMAL,&token);
    uint32_t result=((uint32_t(*)(uint32_t))(uintptr_t)0xaebdc3u)(a);
    if(token.birth&&heap_same())(void)af_cp_capture406_write_end(&capture,&token,AF_CP_CAPTURE406_NORMAL);
    return result;
}
uint32_t af_cp_capture406_restore_target(uint32_t b,uint32_t r,uint32_t p,uint32_t mode,uint32_t extra){
    AfCpCapture406Token token={0};
    if(b>AF_CP_CAPTURE406_B&&capture_color&&heap_same())
        (void)af_cp_capture_color406_a_invalidate(capture_color,b-AF_CP_CAPTURE406_B);
    if(b>AF_CP_CAPTURE406_B&&af_cp_capture406_target_ready())
        (void)af_cp_capture406_write_begin(&capture,b-AF_CP_CAPTURE406_B,AF_CP_CAPTURE406_RESTORE,&token);
    uint32_t result=((uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t))(uintptr_t)0x833cb5u)(b,r,p,mode,extra);
    if(token.birth&&heap_same())(void)af_cp_capture406_write_end(&capture,&token,AF_CP_CAPTURE406_RESTORE);
    return result;
}
uint32_t af_cp_capture406_reverse_target(uint32_t d){
    AfCpCapture406Reverse record={0};
    if(af_cp_capture406_target_ready())(void)af_cp_capture406_reverse_begin(&capture,d,&record);
    uint32_t result=((uint32_t(*)(uint32_t))(uintptr_t)0x845cf5u)(d);
    if(record.token.birth&&heap_same())(void)af_cp_capture406_reverse_end(&capture,d,&record);
    return result;
}
uint32_t af_cp_capture406_gamma_target(uint32_t g){
    AfCpCapture406Token token={0};
    /* 不合资格的调用也登记写者，防它并发改写另一在途scope的formatter。 */
    if(capture.magic&&heap_same())(void)af_cp_capture406_scope_begin(&capture,g,&token);
    uint32_t result=((uint32_t(*)(uint32_t))(uintptr_t)0x845db9u)(g);
    if(token.serial&&heap_same())(void)af_cp_capture406_scope_end(&capture,&token);
    return result;
}
uint32_t af_cp_capture406_format_target(uint32_t d,uint32_t formatter){
    AfCpCapture406Token token={0};
    if(capture.magic&&heap_same())(void)af_cp_capture406_format_begin(&capture,d,formatter,&token);
    uint32_t result=((uint32_t(*)(uint32_t,uint32_t))(uintptr_t)0xaa81cbu)(d,formatter);
    if(token.serial&&heap_same())(void)af_cp_capture406_format_end(&capture,d,formatter,&token);
    return result;
}
void af_cp_capture406_request_invalidate_target(void){
    if(capture_color&&heap_same())(void)af_cp_capture_color406_request_invalidate(capture_color);
}
int af_cp_capture406_request_publish_target(const AfCpInput406Token *token,uint32_t id,const AfCpRuntimeAsset406 *asset){
    return af_cp_capture406_target_ready()?af_cp_capture_color406_request_publish(capture_color,token,id,asset):AF_EMPTY;
}
uint32_t af_cp_capture406_rsource_target(uint32_t r,uint32_t source,uint32_t arg2,uint32_t arg3){
    AfCpCaptureColor406Write write={0};
    if(r>=0x20&&r<=UINT32_MAX-0x6668u&&af_cp_capture406_target_ready()){
        uint32_t id=*(const volatile uint32_t *)(uintptr_t)0x163f3c8u;
        uint32_t a_id=0;
        if(source==AF_CP_INPUT406_REQUEST&&read_original(0,r-0x20+0x5ae8,&a_id,4)==AF_OK&&id==a_id){
            (void)af_cp_capture_color406_r_begin(capture_color,r-0x20,&write);
            /* 绑定本A已核请求号；begin内部若换到另一请求，end走现有STALE撤销。 */
            if(write.token.mark)write.request_id=a_id;
        }else (void)af_cp_capture_color406_a_invalidate(capture_color,r-0x20);
    }
    uint32_t result=((uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t))(uintptr_t)0x4596f5u)(r,source,arg2,arg3);
    if(write.token.mark&&heap_same())(void)af_cp_capture_color406_r_end(capture_color,&write);
    return result;
}
uint32_t af_cp_capture406_color_target(uint32_t root,uint32_t pipe,uint32_t arg2,uint32_t arg3){
    AfCpCaptureColor406Scope scope={0};uint32_t operation=0;uint8_t image[12];
    /* 共用719EF6入口覆盖普通Capture的后续重建；主取景operation保持原worker域。 */
    if(capture_color&&heap_same()&&read_original(0,root,&operation,4)==AF_OK&&
       read_original(0,operation,image,sizeof(image))==AF_OK&&image[1]==1){
        uint32_t c4=0,r=0;for(unsigned i=0;i<4;++i){c4|=(uint32_t)image[4+i]<<(8*i);r|=(uint32_t)image[8+i]<<(8*i);}
        (void)af_cp_capture_color406_scope_begin(capture_color,!c4?r:0,&scope);
    }
    uint32_t result=((uint32_t(*)(uint32_t,uint32_t,uint32_t,uint32_t))(uintptr_t)0x719ef7u)(root,pipe,arg2,arg3);
    if(scope.serial&&heap_same())(void)af_cp_capture_color406_scope_end(capture_color,&scope);
    return result;
}
int af_cp_capture406_color_view_target(AfCpCaptureColor406View *view){
    return af_cp_capture406_target_ready()?af_cp_capture_color406_view(capture_color,view):AF_EMPTY;
}
int af_cp_capture406_color_current_target(const AfCpCaptureColor406View *view){
    return af_cp_capture406_target_ready()?af_cp_capture_color406_current(capture_color,view):AF_EMPTY;
}
int af_cp_capture406_color_scope_target(uint32_t r){
    AfCpCaptureColor406Scope scope;
    return capture_color&&heap_same()?af_cp_capture_color406_scope_observe(capture_color,r,&scope):AF_EMPTY;
}
int af_cp_capture406_read_target(uint32_t formatter,uint32_t output,AfCpGamma406Tone *tone,
    AfCpCapture406Token *token,uint8_t image[AF_CP_CAPTURE406_FORMATTER_BYTES]){
    return af_cp_capture406_target_ready()?af_cp_capture406_scope_read(&capture,formatter,output,tone,token,image):AF_EMPTY;
}
int af_cp_capture406_current_target(const AfCpCapture406Token *token){
    return af_cp_capture406_target_ready()?af_cp_capture406_scope_current(&capture,token):AF_EMPTY;
}
#else
int af_cp_capture406_bind_target(void){return AF_INVALID;}
int af_cp_capture406_target_ready(void){return 0;}
void af_cp_capture406_reset_target(void){}
uint32_t af_cp_capture406_birth_target(uint32_t p){(void)p;return 0;}
uint32_t af_cp_capture406_release_target(uint32_t p){(void)p;return 0;}
uint32_t af_cp_capture406_pool_target(uint32_t p){(void)p;return 0;}
uint32_t af_cp_capture406_rebuild_target(uint32_t p){(void)p;return 0;}
uint32_t af_cp_capture406_restore_target(uint32_t b,uint32_t r,uint32_t p,uint32_t m,uint32_t e){(void)b;(void)r;(void)p;(void)m;(void)e;return 0;}
uint32_t af_cp_capture406_reverse_target(uint32_t p){(void)p;return 0;}
uint32_t af_cp_capture406_gamma_target(uint32_t p){(void)p;return 0;}
uint32_t af_cp_capture406_format_target(uint32_t p,uint32_t f){(void)p;(void)f;return 0;}
uint32_t af_cp_capture406_rsource_target(uint32_t r,uint32_t s,uint32_t a,uint32_t b){(void)r;(void)s;(void)a;(void)b;return 0;}
uint32_t af_cp_capture406_color_target(uint32_t r,uint32_t s,uint32_t a,uint32_t b){(void)r;(void)s;(void)a;(void)b;return 0;}
void af_cp_capture406_request_invalidate_target(void){}
int af_cp_capture406_request_publish_target(const AfCpInput406Token *t,uint32_t i,const AfCpRuntimeAsset406 *a){(void)t;(void)i;(void)a;return AF_EMPTY;}
int af_cp_capture406_color_view_target(AfCpCaptureColor406View *v){(void)v;return AF_EMPTY;}
int af_cp_capture406_color_current_target(const AfCpCaptureColor406View *v){(void)v;return AF_EMPTY;}
int af_cp_capture406_color_scope_target(uint32_t r){(void)r;return AF_EMPTY;}
int af_cp_capture406_read_target(uint32_t f,uint32_t o,AfCpGamma406Tone *t,AfCpCapture406Token *v,uint8_t i[AF_CP_CAPTURE406_FORMATTER_BYTES]){(void)f;(void)o;(void)t;(void)v;(void)i;return AF_EMPTY;}
int af_cp_capture406_current_target(const AfCpCapture406Token *t){(void)t;return AF_EMPTY;}
#endif
