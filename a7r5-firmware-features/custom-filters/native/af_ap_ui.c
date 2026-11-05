/* 仅用于已校验4.06的隔离AP；实际客体初始化、页权限和完整界面仍须另验。 */
#include "af_ap_ui.h"
#include "af_ap_names.h"
#include "af_text.h"
#include "af_ap_browser.h"
#include "af_ap_media.h"
#include "af_ap_cards.h"

typedef uintptr_t Word;
extern void af_stock_register(void *, const void *, const void *);
extern Word af_stock_alias(uint32_t);
extern Word af_stock_alias_object(void *, uint32_t);
extern Word af_stock_name(void *, uint32_t);
extern Word af_stock_icon(void *, uint32_t);
extern Word af_stock_icon_alternate(void *, uint32_t);
extern Word af_stock_parent(void *, uint32_t);
extern Word af_stock_parameter_value(void *);
extern Word af_stock_parameter_disabled(void *);
extern Word af_stock_parameter_default(void *);
extern Word af_stock_base_available(void);
extern Word af_stock_base_label(uint32_t);
extern Word af_stock_base_icon(void *,uint32_t);
extern void af_stock_parameter_layout(void *);
extern Word af_stock_visible(void *, uint32_t);
extern void af_stock_display(void *, void *, void *, const void *);
extern Word af_stock_inhibited(void *);
extern Word af_stock_direct(void *, const void *);
extern void af_stock_select(uint32_t);
extern void af_stock_preview(void *, uint32_t);
extern void af_stock_preview_menu(uint32_t);
extern Word af_stock_refresh(void *);
extern void af_stock_reset(void *);
extern uint32_t af_stock_confirm(void *,void *);
extern void af_stock_parameter_init(void *);
extern void af_stock_base_cycle(void *, uint32_t);
extern int32_t af_original_normalize(uint32_t);
extern const uint32_t *af_original_bases(void);
extern void af_stock_step_0(void *, uint32_t);
extern void af_stock_step_1(void *, uint32_t);
extern void af_stock_step_2(void *, uint32_t);
extern void af_stock_step_3(void *, uint32_t);
extern void af_stock_step_4(void *, uint32_t);
extern void af_stock_step_5(void *, uint32_t);
extern void af_stock_step_6(void *, uint32_t);
extern void af_stock_step_7(void *, uint32_t);

static const Word getters[8] = {
    0x28c5544,0x28c556c,0x28c5594,0x28c55bc,
    0x28c55e4,0x28c560c,0x28c5634,0x28c565c
};
AfCatalog af_ap_catalog;
AfLabels af_ap_labels;
AfApManage af_ap_manager;
uint8_t af_ap_rows[33][128];
static Word additions[14][2];
static uint32_t prepared, enabled, layout_allowed, display_menu;
static uint32_t refresh_pending, refresh_menu;
static uint32_t initializer_active, initializer_base;
static Word ap_base, original_rows, original_current;
static uint32_t selected_valid,selected_menu,selected_selector,selected_native;
static uint32_t original_count;
/* 仅原UI拥有者使用；保存最新明确事件，不建立新的通信或成像版本。 */
typedef struct {
    uint32_t kind,slot,selector; /* 0空、1用户、2原厂、3退出覆盖。 */
    AfPreset preset;
} ImagingRequest;
static struct {
    AfApImagingBinding binding;
    uint32_t requested,busy,changed;
    int result;
    ImagingRequest pending;
} imaging;
/* state：0未登记、1发布中、2等UI/握手、3已绑定、4终止失败。 */
static struct {AfApImagingProvider binding;uint32_t state,busy;int result;} imaging_provider;

/* 默认构建保持基址0的既有匿名回归；动态构建必须先显式绑定。 */
static Word ap_address(Word offset) { return ap_base + offset; }
#ifdef AF_AP_DYNAMIC
/* 汇编只使用x16作为ABI临时寄存器；原参数、LR、NZCV及被重放的首指令不变。 */
__attribute__((visibility("hidden"))) Word af_ap_stock_targets[44];
static uint32_t bound;
typedef struct { uint32_t offset, word; } AfApCheck;
static const AfApCheck checks[] = {
    {0x16f6610,0x94166e21},{0x1bd8eb8,0xa9be7bfd},
    {0x1bd1ef8,0xa9bc7bfd},{0x1bd1b88,0xa9bb7bfd},
    {0x1bcfffc,0x5282bb03},{0x23fcd48,0xb9402060},
    {0x2209580,0xa9bc7bfd},{0x220933c,0xa9bd7bfd},
    {0x1c6f208,0xa9b97bfd},{0x25966cc,0xa9b97bfd},
    {0x1c956c8,0xa9bd7bfd},{0x1e97a24,0xa9bd7bfd},
    {0x220a7ac,0xa9b87bfd},{0x220ac74,0xa9b67bfd},
    {0x220a898,0x942eee32},{0x220a8c4,0x941aeb02},
    {0x2209918,0xa9bc7bfd},{0x2209a6c,0xa9bc7bfd},
    {0x2209bc0,0xa9bc7bfd},{0x2209d14,0xa9bc7bfd},
    {0x2209e68,0xa9bc7bfd},{0x2209fbc,0xa9bc7bfd},
    {0x220a110,0xa9bc7bfd},{0x220a264,0xa9bc7bfd},
    {0x17feac0,0xa9ba7bfd},{0x28a87e8,0xf002b2a0},
    {0x17ffd84,0xf0020c60},{0x28bfdcc,0x9002b200},
    {0x1af11f0,0xa9bf7bfd},{0x220929c,0xa9bf7bfd},
    {0x28c54cc,0xd002b1c0},{0x1c91e94,0xa9bc7bfd},
    {0x2dc6160,0x7100481f},{0x28c5544,0xd002b1c0},
    {0x28c556c,0xd002b1c0},{0x28c5594,0xd002b1c0},
    {0x28c55bc,0xd002b1c0},{0x28c55e4,0xd002b1c0},
    {0x28c560c,0xd002b1c0},{0x28c5634,0xd002b1c0},
    {0x28c565c,0xd002b1c0},
    {0x1bd18e8,0xa9bb7bfd},{0x1bd19e8,0xa9bb7bfd},
    {0x1bdb0b0,0x528566c2},
    {0x220b620,0xa9be7bfd},{0x220b51c,0xa9be7bfd},
    {0x220b708,0xa9bd7bfd},{0x220b4e0,0xa9bf7bfd},
    {0x220b89c,0xa9bc7bfd},{0x2209464,0xa9b97bfd},
    {0x220c87c,0x97e72317},{0x1bd54d8,0xa9be7bfd},
    {0x1af3cdc,0xa9be7bfd},{0x220c8dc,0x97fffbd7},
    {0x220b838,0x52923ec0},{0x1bd5508,0xa9be7bfd},
    {0x2208e8c,0x97e7319f},{0x220c8a0,0x97e7231a},{0x1885b38,0x97f9566e},
    {0x263d558,0xa9bc7bfd},{0x2e7d208,0xa9b97bfd},
    {0x28c5684,0xd002b1c0},{0x28c5698,0xd002b1c0},
    {0x220a6a4,0xa9bd7bfd},{0x220a670,0x39405001},{0x220920c,0xa9be7bfd},
    {0x1c91c40,0xa9bc7bfd},{0x1c935e0,0xa9bc7bfd},{0x1bd906c,0x91002002},
    {0x1bd924c,0xa9bc7bfd},{0x1bd9348,0xa9bc7bfd},
    {0x1c938a8,0xa9bc7bfd},{0x1c933ec,0xa9bc7bfd},{0x28b0464,0xf002b260},
    {0x1bd5720,0xa9be7bfd},{0x1cdbb08,0xf9400003},
    {0x28a8720,0xf002b2a0},{0x28a8734,0xf002b2a0},
    {0x21d68d8,0x39405001},{0x21d62a8,0xa9be7bfd},{0x21d62cc,0xa9be7bfd},
    {0x21f3ed8,0xa9bd7bfd},{0x21f3608,0xa9b67bfd},
    {0x21f3a4c,0x97ffe838},{0x21edb2c,0xaa0003e1},{0x21f99a4,0x97e76ed9},
    {0x1c05f18,0xa9bd7bfd},{0x28ae4b0,0xb002b280},
    {0x219750c,0x97ffff08},
    {0x2199cc4,0x97ffff0a},
    {0x219c1ac,0x97ffff04},
    {0x219e694,0x97ffff02},
    {0x2199510,0x97e8eff2},
    {0x219b9e0,0x97e8e6be},
    {0x219e07c,0x97e8dd17},
    {0x21a0520,0x97e8d3ee},
    {0x2197b5c,0xa9b87bfd},
    {0x219a2ec,0xa9b87bfd},
    {0x219c814,0xa9b87bfd},
    {0x219ed00,0xa9b87bfd},
    {0x2198040,0xa9b77bfd},
    {0x219a808,0xa9b77bfd},
    {0x219ccc0,0xa9b77bfd},
    {0x219f21c,0xa9b77bfd},
    {0x219712c,0xaa0003e1},
    {0x21998ec,0xaa0003e1},
    {0x219bdbc,0xaa0003e1},
    {0x219e29c,0xaa0003e1},
    {0x28cb488,0x9002b1a0},
    {0x28cb49c,0x9002b1a0},
    {0x28cb4b0,0x9002b1a0},
    {0x28cb4c4,0x9002b1a0},
    {0x28cb4d8,0x9002b1a0},
    {0x28cb4ec,0x9002b1a0},
    {0x28cb500,0x9002b1a0},
    {0x28cb514,0x9002b1a0},
    {0x28cb528,0x9002b1a0},
    {0x28cb53c,0x9002b1a0},
    {0x28cb550,0x9002b1a0},
    {0x28cb564,0x9002b1a0},
    {0x28cb578,0x9002b1a0},
    {0x28cb58c,0x9002b1a0},
    {0x28cb5a0,0x9002b1a0},
    {0x28cb5b4,0x9002b1a0},
    {0x23d5818,0xa9be7bfd},
    {0x23d583c,0xa9be7bfd},
    {0x3693c0c,0xa9ba7bfd},
    {0x3694f64,0xa9bc7bfd},
    {0x252d80c,0xa9bc7bfd},
    {0x219a5d8,0xa9bd7bfd},
    {0x23d58d0,0x39405001},
    {0x23d5b8c,0x39405001},
};
static const uint32_t targets[44] = {
    0x1bd8ebc,0x1bd1efc,0x1bd1b8c,0x1bd0000,0x23fcd4c,
    0x2209584,0x2209340,0x1c6f20c,0x25966d0,0x1c956cc,
    0x1e97a28,0x220a7b0,0x220ac78,
    0x220991c,0x2209a70,0x2209bc4,0x2209d18,0x2209e6c,
    0x2209fc0,0x220a114,0x220a268,
    0x1c91e94,0x2dc6160,0x28c54cc,
    0x1bd18ec,0x1bd19ec,0x1bdb0b4,
    0x220b624,0x220b520,0x220b70c,0x220b8a0,0x2209468,0x1bd54d8,0x220b838,0x263d55c,0x21f360c,
    0x2197b60,0x219a2f0,0x219c818,0x219ed04,0x2198044,0x219a80c,0x219ccc4,0x219f220
};
int af_ap_bind(const AfApBinding *binding) {
    static const uint8_t digest[32] = {
        0xd1,0x59,0x33,0xce,0xb5,0xff,0x9a,0xd0,
        0xb4,0xf7,0x89,0xcb,0xab,0xd6,0xff,0x0a,
        0x51,0x52,0x64,0x72,0xdd,0x35,0xc9,0x0d,
        0xb9,0x71,0x96,0xdd,0x22,0x78,0x20,0xe9
    };
    uint32_t i;
    Word base;
    if (bound || prepared) return AF_BUSY;
    if (!binding || binding->version != AF_AP_BIND_VERSION ||
        binding->bytes != sizeof(*binding) || binding->mapped_bytes != AF_AP_IMAGE_SPAN)
        return AF_INVALID;
    base = binding->base;
    if (!base || (base & 4095u) || base > UINTPTR_MAX-AF_AP_IMAGE_SPAN ||
        binding->application_init != base+0x17feac0) return AF_INVALID;
    for (i = 0; i < 32; ++i) if (binding->ap_sha256[i] != digest[i]) return AF_INVALID;
    /* 全部核对完才发布表；不在错误前像下留下部分有效目标。 */
    for (i = 0; i < sizeof(checks)/sizeof(checks[0]); ++i)
        if (*(const uint32_t *)(base+checks[i].offset) != checks[i].word) return AF_STALE;
    if (*(const uint32_t *)(base+0x5858b08+0x54) != 19 ||
        *(const Word *)(base+0x5858b08+0x58) != base+0x3f4a280 ||
        *(const Word *)(base+0x5858b08+0x78) != base+0x1c05f18) return AF_STALE;
    for (i = 0; i < 44; ++i) af_ap_stock_targets[i] = base+targets[i];
    ap_base = base;bound = 1;
    return AF_OK;
}
int af_ap_unbind(void) {
    uint32_t i;
    if (prepared || enabled || initializer_active) return AF_BUSY;
    for (i = 0; i < 44; ++i) af_ap_stock_targets[i] = 0;
    ap_base = 0;bound = 0;
    return AF_OK;
}
int af_ap_detach_allowed(void) {
    return prepared || enabled || initializer_active ? AF_BUSY : af_ap_names_detach_allowed();
}
#else
int af_ap_bind(const AfApBinding *binding) { (void)binding;return AF_INVALID; }
int af_ap_unbind(void) { return AF_INVALID; }
int af_ap_detach_allowed(void) { return AF_INVALID; }
#endif
uintptr_t af_ap_bound_base(void) { return ap_base; }

static void copy(uint8_t *to, const uint8_t *from, uint32_t bytes) {
    uint32_t i;
    for (i = 0; i < bytes; ++i) to[i] = from[i];
}
static void put32(uint8_t *p, uint32_t value) {
    uint32_t i;
    for (i = 0; i < 4; ++i) p[i] = (uint8_t)(value >> (8*i));
}
static uint32_t get32(const void *source) {
    const uint8_t *p = source;
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static int new_menu(uint32_t menu) { return menu >= AF_UI_NEW_FIRST && menu <= AF_UI_NEW_LAST; }
static uint32_t current_menu(void) {
    const uint32_t *(*get)(void) = (const uint32_t *(*)(void))ap_address(0x28a87e8);
    return *get();
}
static int restricted_layout(void) {
    uint32_t (*get)(void) = (uint32_t (*)(void))ap_address(0x17ffd84);
    const uint32_t *(*mode)(void) = (const uint32_t *(*)(void))ap_address(0x28bfdcc);
    /* 原厂0x220a410也读取该模型。研究分流额外拒绝未知非零值，避免旧快照放行。 */
    return get() == 1 || *mode() != 0;
}
static int user_menu(uint32_t menu) {
    AfUiRoute route;
    return af_ui_resolve(menu,&route) == AF_OK && route.kind == AF_UI_USER &&
        (route.slot>6 || af_ap_catalog.slots[route.slot-1].present);
}

static void request_refresh(uint32_t menu) {
    refresh_menu = menu;refresh_pending = 1;
}
int af_ap_imaging_bind(const AfApImagingBinding *b){
    if(imaging.binding.send || imaging.busy || selected_valid)return AF_BUSY;
    if(!prepared || !b || b->version!=AF_AP_IMAGING_VERSION || b->bytes!=sizeof(*b) ||
       !b->context || !b->capabilities || !b->send || !b->factory || !b->release)return AF_INVALID;
    if((b->capabilities(b->context)&AF_AP_IMAGING_REQUIRED)!=AF_AP_IMAGING_REQUIRED)return AF_BUSY;
    imaging.binding=*b;imaging.result=AF_EMPTY;return AF_OK;
}
int af_ap_imaging_result(void){return imaging.binding.send?imaging.result:AF_MANAGE_NOT_READY;}
int af_ap_imaging_provider_bind(const AfApImagingProvider *p){
    if(!p || p->version!=AF_AP_IMAGING_PROVIDER_VERSION || p->bytes!=sizeof(*p) ||
       !p->context || !p->resolve)return AF_INVALID;
    uint32_t expected=0;
    if(!__atomic_compare_exchange_n(&imaging_provider.state,&expected,1,0,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return AF_BUSY;
    /* 此处不读取UI选择状态；release/acquire只发布已完整复制的驻留回调。 */
    imaging_provider.binding=*p;imaging_provider.result=AF_BUSY;
    __atomic_store_n(&imaging_provider.state,2,__ATOMIC_RELEASE);return AF_OK;
}
int af_ap_imaging_provider_result(void){
    uint32_t state=__atomic_load_n(&imaging_provider.state,__ATOMIC_ACQUIRE);
    return !state?AF_MANAGE_NOT_READY:state<3?AF_BUSY:imaging_provider.result;
}
static void imaging_provider_poll(void *manager){
    if(__atomic_load_n(&imaging_provider.state,__ATOMIC_ACQUIRE)!=2 || imaging_provider.busy ||
       !prepared || !enabled || !ap_base || !manager ||
       *(const Word *)manager!=ap_address(0x58d2fb8))return;
    if(imaging.binding.send){
        imaging_provider.result=AF_OK;__atomic_store_n(&imaging_provider.state,3,__ATOMIC_RELEASE);return;
    }
    /* 与已有af_ap_imaging_bind相同的忙保护；不抹去或重放已激活选择。 */
    if(selected_valid || imaging.busy)return;
    imaging_provider.busy=1;AfApImagingBinding next={0};
    int result=imaging_provider.binding.resolve(imaging_provider.binding.context,&next);
    if(result==AF_OK){
        if(!prepared || !enabled)result=AF_STALE;
        else result=af_ap_imaging_bind(&next);
    }
    imaging_provider.result=result;
    if(result!=AF_BUSY)__atomic_store_n(&imaging_provider.state,result==AF_OK?3u:4u,__ATOMIC_RELEASE);
    imaging_provider.busy=0;
}
static int imaging_ready(void){
    return imaging.binding.send &&
        ((imaging.binding.capabilities(imaging.binding.context)&AF_AP_IMAGING_REQUIRED)==AF_AP_IMAGING_REQUIRED);
}
static int imaging_same(const AfPreset *a,const AfPreset *b){
    if(a->base!=b->base || a->kind!=b->kind)return 0;
    for(unsigned i=0;i<8;++i)if(a->params[i]!=b->params[i])return 0;
    for(unsigned i=0;i<32;++i)
        if(a->payload_sha256[i]!=b->payload_sha256[i] || a->lut_sha256[i]!=b->lut_sha256[i])return 0;
    return 1;
}
static int imaging_attempt(const ImagingRequest *request){
    if(!imaging_ready())return AF_BUSY;
    uint32_t capabilities=imaging.binding.capabilities(imaging.binding.context);
    int native_only=(capabilities&AF_AP_IMAGING_NATIVE_ONLY)!=0;
    if(request->kind==1){
        if(native_only)return AF_IO;
        AfUiRoute route;AfPreset current;
        /* 忙期间被清空、异值替换或换选的快照不得回放；仅保存不丢工作编辑。 */
        if(!enabled || restricted_layout() || !selected_valid ||
           af_ui_resolve(selected_menu,&route)!=AF_OK || route.kind!=AF_UI_USER || route.slot!=request->slot ||
           af_read(&af_ap_catalog,request->slot,0,&current)!=AF_OK ||
           !imaging_same(&request->preset,&current))return AF_STALE;
        if(request->preset.kind && (!(capabilities&AF_AP_IMAGING_FULL_RECIPE) ||
           (request->slot<=6 && !(capabilities&AF_AP_IMAGING_USER20))))return AF_MANAGE_NOT_READY;
        const uint32_t *(*native)(void)=(void *)ap_address(0x28ae4b0);
        uint32_t selector=*native();
        if(!(selector<=15 || selector==17 || selector==18))return AF_STALE;
        /* 发送失败也不能假定CP仍是原厂；原厂事件须能明确退出覆盖。 */
        imaging.requested=1;
        return imaging.binding.send(imaging.binding.context,request->slot,&request->preset);
    }
    int status,release_to_native=native_only || request->kind==3 || !enabled || restricted_layout();
    if(release_to_native)status=imaging.binding.release(imaging.binding.context);
    else{
        AfPreset preset={0};
        status=imaging.binding.factory(imaging.binding.context,request->selector,&preset);
        if(status==AF_OK && (af_validate(&preset)!=AF_OK || preset.kind || preset.base!=request->selector))status=AF_STALE;
        if(status==AF_OK)status=imaging.binding.send(imaging.binding.context,0,&preset);
    }
    /* 普通原厂输入仍可能pending；仅明确退出接受才清除本地覆盖请求。 */
    if(status==AF_OK && release_to_native)imaging.requested=0;
    return status;
}
static void imaging_dispatch(void){
    if(imaging.busy || !imaging.pending.kind)return;
    ImagingRequest request=imaging.pending;
    imaging.pending.kind=0;imaging.busy=1;imaging.changed=0;
    int result=imaging_attempt(&request);
    /* 回调内若出现新的明确事件，保留新请求，不用旧BUSY结果覆盖。 */
    if(!imaging.changed){
        if(result==AF_BUSY)imaging.pending=request;
        imaging.result=result;
    }
    imaging.busy=0;
}
static void imaging_pending_poll(void *manager){
    if(!prepared || !ap_base || !manager || *(const Word *)manager!=ap_address(0x58d2fb8))return;
    imaging_dispatch();
}
static void imaging_user(uint32_t slot){
    if(!imaging.binding.send)return;
    imaging.pending.kind=0;imaging.changed=1;
    AfPreset preset={0};
    if(af_read(&af_ap_catalog,slot,0,&preset)!=AF_OK || af_validate(&preset)!=AF_OK){
        imaging.result=AF_MANAGE_NOT_READY;return;
    }
    imaging.pending=(ImagingRequest){.kind=1,.slot=slot,.preset=preset};
    imaging.result=AF_BUSY;imaging_dispatch();
}
static void imaging_factory(uint32_t selector){
    if(!imaging.binding.send)return;
    /* 即使USER还未发出，原厂事件也必须撤销它，不能以后反扑。 */
    imaging.pending.kind=0;imaging.changed=1;
    if(!imaging.requested)return;
    imaging.pending=(ImagingRequest){.kind=selector<=9 || selector==17 || selector==18?2u:3u,.selector=selector};
    imaging.result=AF_BUSY;imaging_dispatch();
}

/* 原厂基底0..11与创意外观选择值不是同一个编号空间。 */
static uint32_t base_selector(uint32_t internal) {
    if (internal <= 9) return internal;
    return internal == 10 ? 17 : internal == 11 ? 18 : UINT32_MAX;
}
static uint32_t base_internal(uint32_t selector) {
    if (selector <= 9) return selector;
    return selector == 17 ? 10 : selector == 18 ? 11 : UINT32_MAX;
}
static uint32_t base_menu(uint32_t selector) {
    return selector<=5?0x84c + selector:selector<=9?0x84e + selector:
           selector==17?0x852:0x853;
}

/* 原基底UI属性的窄事务；结构及调用序与220adbc..220ae18保持一致。 */
static void publish_base_label(uint32_t selector) {
    struct Change { Word value,meta;uint32_t id;uint8_t changed,shadow;uint16_t reserved;Word journal; } change={0};
    _Static_assert(sizeof(struct Change)==32,"UI property transaction layout");
    Word scope[2]={0,0};uint32_t menu=base_menu(selector);
    void (*begin)(void *)=(void (*)(void *))ap_address(0x2e7d208);
    Word (*value)(void)=(Word (*)(void))ap_address(0x28c5684);
    Word (*meta)(void)=(Word (*)(void))ap_address(0x28c5698);
    void (*set)(void *,const void *)=(void (*)(void *,const void *))ap_address(0x220a6a4);
    void (*notify)(void *)=(void (*)(void *))ap_address(0x220a670);
    void (*finish)(void *)=(void (*)(void *))ap_address(0x220920c);
    begin(scope);change.value=value();change.meta=meta();change.id=0x1700;
    set(&change,&menu);notify(&change);finish(scope);
}
void af_ap_reset(void *transaction) {
    /* 启动预装和禁用阶段保持原委派；不能以尚未发布的菜单身份阻断原reset。 */
    if(!enabled){af_stock_reset(transaction);return;}
    uint32_t menu=current_menu();AfUiRoute route;
    /* 确认对话框的身份丢失时保守拒绝，不能借原0x690推断用户槽。 */
    if(af_ui_resolve(menu,&route)!=AF_OK)return;
    if(route.kind==AF_UI_USER && (new_menu(menu) || af_ap_catalog.slots[route.slot-1].present)) {
        AfPreset initial;
        if(!enabled || !layout_allowed || display_menu!=menu || restricted_layout() ||
           af_read(&af_ap_catalog,route.slot,0,&initial)!=AF_OK)return;
        if(af_restore(&af_ap_catalog,route.slot,1)==AF_OK) {
            initial=af_ap_catalog.slots[route.slot-1].initial;
            publish_base_label(initial.base);request_refresh(menu);imaging_user(route.slot);
        }
        return;
    }
    af_stock_reset(transaction);
    imaging_factory(UINT32_MAX);
}
int af_ap_label_refresh(uint32_t slot) {
    uint32_t menu;
    if(!slot || slot>AF_USERS)return AF_INVALID;
    if(!enabled)return AF_BUSY;
    menu=slot<=6?0x858+slot-1:AF_UI_NEW_FIRST+slot-7;
    if(current_menu()==menu && !restricted_layout())request_refresh(menu);
    return AF_OK;
}

/* 只替换初始化里的两个BL；私有索引0绝不指向原厂18项数组。 */
int32_t af_ap_init_index(uint32_t selector) {
    return initializer_active ? 0 : af_original_normalize(selector);
}
const uint32_t *af_ap_init_bases(void) {
    return initializer_active ? &initializer_base : af_original_bases();
}
void af_ap_parameter_init(void *object) {
    uint32_t menu = current_menu();
    AfUiRoute route;
    AfPreset preset;
    int user = af_ui_resolve(menu,&route) == AF_OK && route.kind == AF_UI_USER &&
        (route.slot>6 || af_ap_catalog.slots[route.slot-1].present);
    /* 原初始化也不能在尚未退出的私有上下文中重入。 */
    if (initializer_active) return;
    if ((enabled && user && !restricted_layout()) || new_menu(menu)) {
        if (!enabled || !user || restricted_layout() ||
            af_read(&af_ap_catalog,route.slot,0,&preset) != AF_OK) return;
        initializer_base = base_internal(preset.base);
        if (initializer_base == UINT32_MAX) return;
        initializer_active = 1;
        af_stock_parameter_init(object);
        initializer_active = 0;
        if (current_menu() == menu && !restricted_layout()) request_refresh(menu);
        return;
    }
    af_stock_parameter_init(object);
}
void af_ap_base_cycle(void *object, uint32_t direction) {
    uint32_t menu = current_menu();
    AfUiRoute route;AfPreset preset;uint32_t index,next;
    uint32_t (*focus)(void *)=(uint32_t (*)(void *))ap_address(0x1af11f0);
    uint32_t (*option)(void *)=(uint32_t (*)(void *))ap_address(0x220929c);
    if ((enabled && user_menu(menu) && !restricted_layout()) || new_menu(menu)) {
        if(!enabled || !object || direction>1 || initializer_active || !layout_allowed ||
           display_menu!=menu || restricted_layout() || af_ui_resolve(menu,&route)!=AF_OK ||
           af_read(&af_ap_catalog,route.slot,0,&preset)!=AF_OK || preset.kind ||
           focus((uint8_t *)object+0x1a0)!=0xf || option(object)!=0)return;
        for(index=0;index<AF_BUILTINS;index++)if((uint32_t)af_builtin_selector(index)==preset.base)break;
        if(index==AF_BUILTINS)return;
        next=direction?(index+1)%AF_BUILTINS:(index+AF_BUILTINS-1)%AF_BUILTINS;
        if(af_edit_base(&af_ap_catalog,route.slot,(uint32_t)af_builtin_selector(next))==AF_OK) {
            /* 复用隔离后的原初始化来更新UI基底属性；不执行原成像/基底数组写入。 */
            af_ap_parameter_init(object);
            if(current_menu()==menu && !restricted_layout()) {
                /* 原初始化按上次参数模型恢复焦点，连续切基底须恢复真实基底节点。 */
                void (*set_focus)(void *,uint32_t)=(void (*)(void *,uint32_t))ap_address(0x1af3cdc);
                set_focus((uint8_t *)object+0x1a0,0xf);
                request_refresh(menu);imaging_user(route.slot);
            }
        }
        return;
    }
    af_stock_base_cycle(object,direction);
    imaging_factory(UINT32_MAX);
}

/* 原D4还会在方向键、初始化和异步离页时自动调用+88，不能以它授权提交。
 * 入口只捕获真实ENTER；专用关闭调用点已通过原资格检查后才消费一次意图。 */
static void ui_manage_save_return(uint64_t previous_ticket);
static uint32_t confirm_active,confirm_consumed,confirm_group,confirm_menu;
static void *confirm_controller;
static int (*confirm_intent)(uint32_t);
static void (*confirm_action)(uint32_t);
uint32_t af_ap_confirm(void *controller,void *event) {
    int (*intent)(uint32_t)=0;void (*action)(uint32_t)=0;
    uint32_t group=0,menu=0;
    if(enabled && !confirm_active && controller &&
       *(const Word *)controller==ap_address(0x58da458)) {
        const uint32_t *(*get_group)(void)=(void *)ap_address(0x28a8720);
        group=*get_group();menu=current_menu();
        if(group==AF_MANAGE_MENU_ROOT && menu>AF_MANAGE_MENU_ROOT && af_ap_manage_menu_is_id(menu)) {
            intent=af_ap_manage_menu_intent;action=af_ap_manage_menu_action;
        } else if(group==AF_TARGETS_ROOT && menu>AF_TARGETS_ROOT && af_ap_targets_is_id(menu)) {
            intent=af_ap_targets_intent;action=af_ap_targets_action;
        } else if(group==AF_BROWSER_MENU_ROOT && menu>AF_BROWSER_MENU_ROOT && af_ap_browser_is_id(menu)) {
            intent=af_ap_browser_intent;action=af_ap_browser_action;
        } else if(group==AF_CARDS_MENU_ROOT && menu>AF_CARDS_MENU_ROOT && af_ap_cards_is_id(menu)) {
            intent=af_ap_cards_intent;action=af_ap_cards_action;
        }
    }
    if(!intent)return af_stock_confirm(controller,event);
    (void)af_ap_manage_menu_intent(0);(void)af_ap_targets_intent(0);(void)af_ap_browser_intent(0);
    (void)af_ap_cards_intent(0);
    confirm_active=1;confirm_consumed=0;confirm_group=group;confirm_menu=menu;
    confirm_controller=controller;confirm_intent=intent;confirm_action=action;
    uint32_t result=af_stock_confirm(controller,event);
    (void)af_ap_manage_menu_intent(0);(void)af_ap_targets_intent(0);(void)af_ap_browser_intent(0);
    (void)af_ap_cards_intent(0);
    confirm_active=0;confirm_consumed=0;
    confirm_controller=0;confirm_intent=0;confirm_action=0;return result;
}
void af_ap_confirm_close(void *controller) {
    /* 本BL只来自原ENTER默认关闭分支；不能以通用leave或返回值1代替这个证据。 */
    if(confirm_active && !confirm_consumed && enabled && controller==confirm_controller &&
       controller && *(const Word *)controller==ap_address(0x58da458)) {
        const uint32_t *(*get_group)(void)=(void *)ap_address(0x28a8720);
        if(*get_group()==confirm_group && current_menu()==confirm_menu && confirm_intent && confirm_action) {
            confirm_consumed=1;
            uint64_t previous_ticket=af_ap_manager.job.ticket;
            if(confirm_intent(confirm_menu)==AF_OK)confirm_action(confirm_menu);
            (void)confirm_intent(0);
            if(confirm_group==AF_MANAGE_MENU_ROOT && confirm_menu==AF_MANAGE_MENU_SAVE &&
               af_ap_manager.job.ticket!=previous_ticket)ui_manage_save_return(previous_ticket);
        }
    }
    ((void (*)(void *))ap_address(0x21edb2c))(controller);
}

static uint64_t manage_selection_generation,manage_ui_ticket;
/* 只保存这一次已确认的嵌套菜单状态；原manager消费队列以后才认定页面已打开。 */
static uint32_t manage_ui_stage,manage_ui_op,manage_ui_root,manage_ui_page,manage_ui_prepared,manage_ui_from_root;
static uint32_t manage_ui_physical=UINT32_MAX;
static int manage_ui_result;
/* 已读文件的同代模板；目标选择后重取并逐字节核对，不接收后来变更的来源。 */
static AfApManageRequest manage_ui_import;
static uint32_t manage_ui_import_valid;
static struct {
    uint64_t epoch,owner_epoch;
    void *owner;
    uint32_t phase,slot,models,done,expected,old_bytes,new_bytes,tainted;
    int result;
    AfApManageSlot snapshot;
    uint8_t saved[548];
    char old_name[64],new_name[64];
} rename_ui;
static int rename_begin(uint32_t),rename_prepare(void),rename_finish(uint32_t);
static void rename_abort(void);
static void ui_manage_save_return(uint64_t previous_ticket) {
    if(manage_ui_stage || af_ap_manager.phase!=AF_MANAGE_QUEUED ||
       af_ap_manager.job.request.op!=AF_MANAGE_SAVE)return;
    /* 保存仍由唯一后端完成；原关闭后自动重开同一管理页展示真实回读结果。 */
    manage_ui_op=AF_MANAGE_SAVE;manage_ui_ticket=previous_ticket;
    manage_ui_root=AF_MANAGE_MENU_ROOT;manage_ui_from_root=AF_MANAGE_MENU_ROOT;
    manage_ui_prepared=1;manage_ui_stage=1;manage_ui_result=AF_OK;
}
uint32_t af_ap_manage_ui_state(void) {return manage_ui_stage;}
uint32_t af_ap_manage_ui_screen(void) {return manage_ui_physical;}
int af_ap_manage_ui_result(void) {return manage_ui_result;}
/* 原创意外观的实际selector才是当前身份；最近显示context不能代替它。 */
static uint32_t ui_active_user_slot(void) {
    if(!prepared || !enabled || restricted_layout())return UINT32_MAX;
    uint32_t selector=af_ap_current();
    for(uint32_t row=0;row<AF_UI_ROWS;++row) {
        AfUiRoute route;
        if(af_ui_item(row,&route)==AF_OK && route.selector==selector)
            return route.kind==AF_UI_USER?route.slot:route.kind==AF_UI_BUILTIN?0:UINT32_MAX;
    }
    return UINT32_MAX;
}
int af_ap_manage_ui_open(void *context,uint32_t op,uint32_t source_slot) {
    if(context!=&af_ap_catalog || (op!=AF_MANAGE_COPY && op!=AF_MANAGE_CREATE && op!=AF_MANAGE_IMPORT && op!=AF_MANAGE_CLEAR && op!=AF_MANAGE_RENAME && op!=AF_MANAGE_EXPORT))return AF_INVALID;
    if(manage_ui_stage)return AF_BUSY;
    const uint32_t *(*group)(void)=(void *)ap_address(0x28a8720);
    if(*group()!=AF_MANAGE_MENU_ROOT || current_menu()!=af_ap_manage_menu_for_op(op))return AF_STALE;
    if(op!=AF_MANAGE_COPY && source_slot)return AF_INVALID;
    if(op==AF_MANAGE_IMPORT)manage_ui_import_valid=0;
    int result=AF_OK;
    if(op==AF_MANAGE_IMPORT && af_ap_media_card_available()) {
        if(manage_selection_generation==UINT64_MAX)return AF_EXHAUSTED;
        result=af_ap_cards_begin(++manage_selection_generation);
    } else if(op==AF_MANAGE_RENAME) {
        result=rename_begin(ui_active_user_slot());
        if(result!=AF_OK)return result;
    } else if(op!=AF_MANAGE_IMPORT) {
        if(manage_selection_generation==UINT64_MAX)return AF_EXHAUSTED;
        /* begin仅捕获内存快照；目录扫描等I/O延后到原确认栈返回Main以后。 */
        uint64_t generation=++manage_selection_generation;
        result=op==AF_MANAGE_CLEAR?af_ap_targets_begin_clear(ui_active_user_slot(),generation):
               op==AF_MANAGE_EXPORT?af_ap_targets_begin_export(ui_active_user_slot(),generation):
                                   af_ap_targets_begin(op,source_slot,generation);
    }
    if(result!=AF_OK)return result;
    manage_ui_op=op;manage_ui_ticket=af_ap_manager.job.ticket;
    manage_ui_root=op==AF_MANAGE_IMPORT?(af_ap_media_card_available()?AF_CARDS_MENU_ROOT:AF_BROWSER_MENU_ROOT):AF_TARGETS_ROOT;
    manage_ui_prepared=op!=AF_MANAGE_IMPORT;manage_ui_from_root=AF_MANAGE_MENU_ROOT;manage_ui_stage=1;manage_ui_result=AF_OK;return AF_OK;
}
static uint32_t ui_model(Word getter) {
    const uint32_t *(*get)(void)=(void *)ap_address(getter);return *get();
}
static void ui_word(void *to,Word value,size_t bytes) {
    uint8_t *out=to;for(size_t i=0;i<bytes;++i)out[i]=(uint8_t)(value>>(8*i));
}
static int ui_group(uint32_t root) {
    Word scope[2]={0,0};_Alignas(8) uint8_t change[32]={0};
    const uint32_t *(*get)(void)=(void *)ap_address(0x28a8720);
    void *(*meta)(void)=(void *)ap_address(0x28a8734);
    ((void (*)(void *))ap_address(0x21d62a8))(scope);
    ui_word(change,(Word)get(),8);ui_word(change+8,(Word)meta(),8);
    ui_word(change+0x10,0x3b2,4);ui_word(change+0x18,scope[1],8);
    ((void (*)(void *,uint32_t))ap_address(0x21f3ed8))(change,root);
    ((void (*)(void *))ap_address(0x21d68d8))(change);
    ((void (*)(void *))ap_address(0x21d62cc))(scope);
    return *get()==root?AF_OK:AF_IO;
}
static int ui_main(uint32_t screen) {
    return screen==0x2d4 || screen==0x2d5 || screen==0x2d6 || screen==0x2ed;
}
static int ui_open_d4(void *manager,uint32_t root) {
    uint32_t from=get32((uint8_t *)manager+0x3b8);
    if(!ui_main(from) || current_menu()!=0x2b36)return AF_BUSY;
    if(ui_model(0x28a8720)!=manage_ui_from_root)return AF_STALE;
    uint32_t to=((uint32_t (*)(uint32_t))ap_address(0x1bd5720))(root);
    if(to!=0xd4)return AF_STALE;
    int result=ui_group(root);if(result)return result;
    /* 原3参数wrapper仅排20字节请求；不留manager/controller指针。 */
    ((void (*)(void *,const uint32_t *,const uint32_t *))ap_address(0x1cdbb08))(manager,&from,&to);
    return AF_OK;
}
static void ui_manage_failed(int result) {
    if(manage_ui_op==AF_MANAGE_RENAME)rename_abort();
    else if(manage_ui_op==AF_MANAGE_IMPORT) {
        if(manage_ui_root==AF_TARGETS_ROOT)(void)af_ap_targets_cancel();
        if(manage_ui_root==AF_CARDS_MENU_ROOT)(void)af_ap_cards_cancel();
        /* 新票据已持有输入时，父页打开失败不能清除尚未start的导入选择。 */
        if(af_ap_manager.job.ticket==manage_ui_ticket)(void)af_ap_media_cancel();
        manage_ui_import_valid=0;
    } else (void)af_ap_targets_cancel();
    /* 页面打开失败不能把已经提交的新票据改报为写入失败。 */
    if(af_ap_manager.job.ticket==manage_ui_ticket)(void)af_ap_manage_menu_notice(manage_ui_op,result);
    manage_ui_result=result;manage_ui_prepared=0;manage_ui_stage=0;
}
static int ui_manage_poll(void *manager) {
    if(!manager || !ap_base || *(const Word *)manager!=ap_address(0x58d2fb8))return 0;
    manage_ui_physical=get32((uint8_t *)manager+0x3b8);
    if(!manage_ui_stage)return 0;
    /* 已确认选卡但尚未离开关闭栈时禁用扩展，不得在后续刷新偷偷切卡/扫描。 */
    if(manage_ui_op==AF_MANAGE_IMPORT&&!enabled){ui_manage_failed(AF_STALE);return 1;}
    if(manage_ui_op==AF_MANAGE_RENAME) {
        uint32_t root=ui_model(0x28a8720),physical=manage_ui_physical;
        if(manage_ui_stage==1) {
            if(!ui_main(physical) || current_menu()!=0x2b36)return 0;
            if(root!=AF_MANAGE_MENU_ROOT){ui_manage_failed(AF_STALE);return 1;}
            int result=rename_prepare();
            if(result!=AF_OK){ui_manage_failed(result);return 1;}
            uint32_t next=0xcd;
            ((void (*)(void *,const uint32_t *,const uint32_t *))ap_address(0x1cdbb08))(manager,&physical,&next);
            manage_ui_stage=5;return 1;
        }
        if(manage_ui_stage==5) {
            /* 原init和leave可能同批完成，刷新未必见到中间键盘页面。 */
            if(rename_ui.phase==3){manage_ui_stage=6;return 1;}
            if(physical>=0xcc && physical<=0xcf && rename_ui.phase==2){manage_ui_stage=6;return 1;}
            return 0;
        }
        if(manage_ui_stage==6) {
            if(rename_ui.phase!=3 || (physical>=0xcc && physical<=0xcf) || physical==0x259 || physical==0x1e2)return 0;
            if(root!=AF_MANAGE_MENU_ROOT || !ui_main(physical) || current_menu()!=0x2b36) {
                (void)rename_finish(UINT32_MAX);manage_ui_stage=0;
                (void)af_ap_manage_menu_notice(AF_MANAGE_RENAME,AF_STALE);return 1;
            }
            manage_ui_from_root=root;
            int result=ui_open_d4(manager,AF_MANAGE_MENU_ROOT);
            if(result==AF_OK)manage_ui_stage=7;
            else if(result!=AF_BUSY){(void)rename_finish(UINT32_MAX);manage_ui_stage=0;}
            return result==AF_OK;
        }
        if(manage_ui_stage==7 && physical==0xd4) {
            /* 已见真实D4回执，父组失配也须拒绝并恢复，不能继续悬挂临时模型。 */
            int result=rename_finish(root==AF_MANAGE_MENU_ROOT?ui_active_user_slot():UINT32_MAX);
            if(result!=AF_OK)(void)af_ap_manage_menu_notice(AF_MANAGE_RENAME,result);
            manage_ui_result=result;manage_ui_stage=0;return 1;
        }
        return 0;
    }
    if(manage_ui_stage==2 || manage_ui_stage==4) {
        if(manage_ui_physical==0xd4 && ui_model(0x28a8720)==manage_ui_root) {
            if(manage_ui_stage==4){manage_ui_stage=0;return 1;}
            if(manage_ui_root==AF_TARGETS_ROOT && af_ap_targets_stage()==AF_TARGETS_CONFIRM_WAIT) {
                int result=af_ap_targets_presented();
                if(result!=AF_OK){ui_manage_failed(result);return 1;}
            }
            manage_ui_stage=3;manage_ui_page=af_ap_browser_page();return 1;
        }
        return 0;
    }
    if(!ui_main(manage_ui_physical) || current_menu()!=0x2b36)return 0;
    if(manage_ui_stage==3) {
        uint32_t returned_group=ui_model(0x28a8720);
        /* 原Main恢复保存的父组；不能要求已经关闭的选择器仍占用3b2。 */
        if(returned_group!=manage_ui_root && returned_group!=AF_MANAGE_MENU_ROOT) {
            ui_manage_failed(AF_STALE);return 1;
        }
        manage_ui_from_root=returned_group;
        if(manage_ui_root==AF_CARDS_MENU_ROOT) {
            AfApCardSelection selection;
            int result=af_ap_cards_result();
            if(result==AF_OK)result=af_ap_cards_take(manage_selection_generation,&selection);
            if(result==AF_OK && (selection.generation!=manage_selection_generation || selection.slot>1 || selection.reserved))result=AF_STALE;
            if(result==AF_OK)result=af_ap_media_card_select(selection.slot);
            if(result==AF_OK){manage_ui_root=AF_BROWSER_MENU_ROOT;manage_ui_prepared=0;}
            else {
                (void)af_ap_cards_cancel();
                if(af_ap_manager.job.ticket==manage_ui_ticket)(void)af_ap_media_cancel();
                if(result==AF_EMPTY || result==AF_CARDS_CANCELLED)result=AF_MANAGE_CANCEL;
                (void)af_ap_manage_menu_notice(AF_MANAGE_IMPORT,result);
                manage_ui_result=result;manage_ui_import_valid=0;manage_ui_root=AF_MANAGE_MENU_ROOT;
            }
            manage_ui_stage=1;
        } else if(manage_ui_root==AF_BROWSER_MENU_ROOT) {
            int result=af_ap_browser_result();
            if(result==AF_EMPTY && af_ap_browser_page()!=manage_ui_page) {
                (void)af_ap_media_finish();manage_ui_root=AF_BROWSER_MENU_ROOT;manage_ui_stage=1;
            } else {
                if(result==AF_EMPTY)(void)af_ap_media_cancel();else (void)af_ap_media_finish();
                result=af_ap_media_result();
                if(result==AF_OK) {
                    AfApManageRequest request;
                    result=af_ap_media_import_request(&request);
                    if(result==AF_OK) {
                        if(manage_selection_generation==UINT64_MAX)result=AF_EXHAUSTED;
                        else result=af_ap_targets_begin(AF_MANAGE_IMPORT,0,++manage_selection_generation);
                    }
                    if(result==AF_OK){manage_ui_import=request;manage_ui_import_valid=1;}
                }
                if(result==AF_OK)manage_ui_root=AF_TARGETS_ROOT;
                else {
                    (void)af_ap_manage_menu_notice(AF_MANAGE_IMPORT,result);
                    (void)af_ap_media_cancel();manage_ui_import_valid=0;manage_ui_root=AF_MANAGE_MENU_ROOT;
                }
                manage_ui_stage=1;
            }
        } else {
            int result=af_ap_targets_result();
            if(result==AF_TARGETS_CONFIRM_REQUIRED && af_ap_targets_stage()==AF_TARGETS_CONFIRM_WAIT) {
                /* 第一次确认只准备两行表；原Main返回后再重开默认取消的确认页。 */
                manage_ui_root=AF_TARGETS_ROOT;manage_ui_stage=1;
            } else {
                if(!af_ap_targets_disabled()) {
                    (void)af_ap_targets_cancel();
                    if(result==AF_EMPTY)result=AF_MANAGE_CANCEL;
                }
                if(result==AF_TARGETS_CANCELLED)result=AF_MANAGE_CANCEL;
                if(result!=AF_OK)(void)af_ap_manage_menu_notice(manage_ui_op,result);
                if(manage_ui_op==AF_MANAGE_IMPORT) {
                    if(result!=AF_OK)(void)af_ap_media_cancel();
                    manage_ui_import_valid=0;
                }
                manage_ui_root=AF_MANAGE_MENU_ROOT;manage_ui_stage=1;
            }
        }
    }
    if(manage_ui_root==AF_BROWSER_MENU_ROOT && !manage_ui_prepared) {
        int result=af_ap_media_prepare();
        if(result!=AF_OK) {
            manage_ui_result=result;(void)af_ap_manage_menu_notice(AF_MANAGE_IMPORT,result);
            manage_ui_root=AF_MANAGE_MENU_ROOT;
        } else manage_ui_prepared=1;
    }
    int result=ui_open_d4(manager,manage_ui_root);manage_ui_result=result;
    if(result==AF_OK)manage_ui_stage=manage_ui_root==AF_MANAGE_MENU_ROOT?4:2;
    else if(result!=AF_BUSY)ui_manage_failed(result);
    return result==AF_OK;
}
static int ui_equal(const void *a,const void *b,size_t bytes) {
    const uint8_t *x=a,*y=b;for(size_t i=0;i<bytes;++i)if(x[i]!=y[i])return 0;return 1;
}
static int ui_pure_snapshot(const AfApManageSlot *snapshot,const AfSlot *slot) {
    if(snapshot->reserved || snapshot->present>1 || slot->pending.request ||
       snapshot->present!=slot->present || snapshot->revision!=slot->saved_revision)return 0;
    return !slot->present || (!snapshot->initial.kind && !snapshot->saved.kind && !snapshot->working.kind &&
           af_validate(&snapshot->initial)==AF_OK && af_validate(&snapshot->saved)==AF_OK && af_validate(&snapshot->working)==AF_OK &&
           ui_equal(&snapshot->initial,&slot->initial,sizeof(AfPreset)) &&
           ui_equal(&snapshot->saved,&slot->saved,sizeof(AfPreset)) &&
           ui_equal(&snapshot->working,&slot->working,sizeof(AfPreset)));
}
static int ui_slot_snapshot(const AfApManageSlot *snapshot,const AfSlot *slot) {
    if(ui_pure_snapshot(snapshot,slot))return 1;
    if(snapshot->reserved || snapshot->present!=1 || !slot->present || slot->pending.request ||
       snapshot->revision!=slot->saved_revision)return 0;
    const AfPreset *a=&snapshot->initial,*b=&snapshot->saved,*c=&snapshot->working;
    return a->kind==1 && b->kind==1 && c->kind==1 &&
           af_validate(a)==AF_OK && af_validate(b)==AF_OK && af_validate(c)==AF_OK &&
           a->base==b->base && a->base==c->base &&
           ui_equal(a->payload_sha256,b->payload_sha256,32) && ui_equal(a->payload_sha256,c->payload_sha256,32) &&
           ui_equal(a->lut_sha256,b->lut_sha256,32) && ui_equal(a->lut_sha256,c->lut_sha256,32) &&
           ui_equal(a,&slot->initial,sizeof(*a)) && ui_equal(b,&slot->saved,sizeof(*b)) && ui_equal(c,&slot->working,sizeof(*c));
}
/* 只有私有会话复用原键盘；原设置路径和四个完整leave始终委派。 */
static const struct {uint32_t getter,meta,value,bytes;} rename_models[8]={
    {0x28cb488,0x28cb49c,0x7f83560,256},{0x28cb4b0,0x28cb4c4,0x7f83770,256},
    {0x28cb4d8,0x28cb4ec,0x7f83980,4},{0x28cb500,0x28cb514,0x7f839a0,4},
    {0x28cb528,0x28cb53c,0x7f839c0,4},{0x28cb550,0x28cb564,0x7f839e0,4},
    {0x28cb578,0x28cb58c,0x7f83a00,4},{0x28cb5a0,0x28cb5b4,0x7f83a48,16}
};
static const uint32_t rename_layouts[4]={0xcc,0xcd,0xcf,0xce};
static const uint32_t rename_controllers[4]={0x58d8308,0x58d8370,0x58d83d8,0x58d8440};
static const uint32_t rename_close[4]={0x219712c,0x21998ec,0x219bdbc,0x219e29c};
static void *rename_value(unsigned i) {
    return ((void *(*)(void))ap_address(rename_models[i].getter))();
}
static int rename_models_valid(void) {
    for(unsigned i=0;i<8;++i)if((Word)rename_value(i)!=ap_address(rename_models[i].value))return 0;
    return 1;
}
static void rename_assign(unsigned i,const void *value) {
    Word scope[2]={0,0};
    ((void (*)(void *))ap_address(0x23d5818))(scope);
    uint8_t *live=rename_value(i);
    void *meta=((void *(*)(void))ap_address(rename_models[i].meta))();
    uint32_t id=0x19ae + i;
    if(i<2) {
        /* 原文本模型按完整256字节保存；不把旧Unicode名送去字节截断。 */
        ((void (*)(Word,uint32_t))ap_address(0x3693c0c))(scope[1],id);
        copy(live,value,256);
        ((void (*)(uint32_t))ap_address(0x252d80c))(id);
    } else {
        struct Change {Word live,meta;uint32_t id;uint8_t dirty,shadow;uint16_t reserved;Word journal;} c={0};
        c.live=(Word)live;c.meta=(Word)meta;c.id=id;c.journal=scope[1];
        if(i<7) {
            ((void (*)(void *,uint32_t))ap_address(0x219a5d8))(&c,get32(value));
            ((void (*)(void *))ap_address(0x23d58d0))(&c);
        } else {
            Word shadow=*(const Word *)meta;
            ((void (*)(Word,uint32_t,const void *,const void *,size_t))ap_address(0x3694f64))
                (scope[1],id,shadow?(const void *)shadow:live,value,16);
            if(shadow){copy((void *)shadow,value,16);c.shadow=1;}
            copy(live,value,16);c.dirty=1;
            ((void (*)(void *))ap_address(0x23d5b8c))(&c);
        }
    }
    ((void (*)(void *))ap_address(0x23d583c))(scope);
}
static int rename_unchanged(void) {
    const AfSlot *slot=&af_ap_catalog.slots[rename_ui.slot-1];
    const AfLabel *label=&af_ap_labels.slots[rename_ui.slot-1];
    return ui_slot_snapshot(&rename_ui.snapshot,slot) && label->generation==rename_ui.snapshot.revision &&
        label->bytes==rename_ui.old_bytes && ui_equal(label->text,rename_ui.old_name,rename_ui.old_bytes+1);
}
static int rename_begin(uint32_t slot) {
    const char *name;size_t bytes;
    if(rename_ui.phase)return AF_BUSY;
    if(rename_ui.epoch==UINT64_MAX)return AF_EXHAUSTED;
    if(!slot || slot>AF_USERS)return AF_INVALID;
    const AfSlot *s=&af_ap_catalog.slots[slot-1];
    AfApManageSlot snapshot={0};snapshot.present=s->present;snapshot.revision=s->saved_revision;
    snapshot.initial=s->initial;snapshot.saved=s->saved;snapshot.working=s->working;
    if(!s->present || !s->saved_revision || !ui_slot_snapshot(&snapshot,s))return AF_INVALID;
    if(af_labels_read(&af_ap_labels,slot,&name,&bytes)!=AF_OK || af_ap_labels.slots[slot-1].generation!=s->saved_revision)return AF_STALE;
    rename_ui.snapshot=(AfApManageSlot){0};rename_ui.snapshot.present=1;rename_ui.snapshot.revision=s->saved_revision;
    rename_ui.snapshot.initial=s->initial;rename_ui.snapshot.saved=s->saved;rename_ui.snapshot.working=s->working;
    rename_ui.slot=slot;rename_ui.old_bytes=(uint32_t)bytes;copy((uint8_t *)rename_ui.old_name,(const uint8_t *)name,(uint32_t)bytes+1);
    ++rename_ui.epoch;rename_ui.owner=0;rename_ui.owner_epoch=0;rename_ui.expected=0xcd;
    rename_ui.phase=1;rename_ui.models=rename_ui.done=rename_ui.new_bytes=rename_ui.tainted=0;rename_ui.result=AF_MANAGE_CANCEL;
    return AF_OK;
}
static int rename_prepare(void) {
    if(rename_ui.phase!=1)return AF_INVALID;
    if(rename_ui.models)return AF_OK;
    if(!rename_unchanged() || !rename_models_valid())return AF_STALE;
    Word scope[2]={0,0};unsigned offset=0;
    ((void (*)(void *))ap_address(0x23d5818))(scope);
    for(unsigned i=0;i<8;++i){copy(rename_ui.saved+offset,rename_value(i),rename_models[i].bytes);offset+=rename_models[i].bytes;}
    ((void (*)(void *))ap_address(0x23d583c))(scope);
    uint8_t empty[256]={0};uint32_t purpose=11;int editable=rename_ui.old_bytes<=46;
    for(unsigned i=0;i<rename_ui.old_bytes;++i)if((uint8_t)rename_ui.old_name[i]<32 || (uint8_t)rename_ui.old_name[i]>126)editable=0;
    if(editable)copy(empty,(const uint8_t *)rename_ui.old_name,rename_ui.old_bytes);
    rename_ui.models=1;rename_assign(0,empty);rename_assign(6,&purpose);return AF_OK;
}
static void rename_restore(void) {
    if(rename_ui.models) {
        unsigned offsets[8],offset=0;
        for(unsigned i=0;i<8;++i){offsets[i]=offset;offset+=rename_models[i].bytes;}
        /* 用途最后恢复；到此四布局原leave已结束，私有管理D4已真正呈现。 */
        for(unsigned i=0;i<6;++i)rename_assign(i,rename_ui.saved+offsets[i]);
        rename_assign(7,rename_ui.saved+offsets[7]);rename_assign(6,rename_ui.saved+offsets[6]);
        rename_ui.models=0;
    }
}
static void rename_abort(void) {
    if(rename_ui.phase==1){rename_restore();rename_ui.phase=0;}
}
static int rename_identity(void *controller,unsigned layout) {
    return rename_ui.phase==2 && rename_ui.models && controller && rename_ui.owner==controller &&
        rename_ui.owner_epoch==rename_ui.epoch &&
        *(const Word *)controller==ap_address(rename_controllers[layout]) &&
        get32((uint8_t *)controller+0x178)==rename_layouts[layout];
}
static int rename_qualified(void) {
    return ui_model(0x28a8720)==AF_MANAGE_MENU_ROOT && get32(rename_value(6))==11;
}
static int rename_owner(void *controller,unsigned layout) {
    return rename_identity(controller,layout) && !rename_ui.tainted && rename_qualified();
}
static void rename_protect_lifecycle(void) {
    if(!rename_qualified()) {
        /* 身份仍属于本会话时，资格丢失只能取消；不能把另一用途交原设置分支。 */
        rename_ui.tainted=1;rename_ui.done=0;rename_ui.result=AF_STALE;
        if(get32(rename_value(6))!=11){uint32_t purpose=11;rename_assign(6,&purpose);}
    }
}
static void rename_done_close(void *controller,unsigned layout) {
    int own=rename_owner(controller,layout);
    void *manager=own?*(void **)((uint8_t *)controller+0x180):0;
    uint32_t before=manager?get32((uint8_t *)manager+0x1e8):UINT32_MAX;
    if(own) {
        const uint8_t *text=rename_value(1);unsigned n=0;
        while(n<256 && text[n])++n;
        int valid=n && n<=46;
        for(unsigned i=0;i<n && i<256;++i)if(text[i]<32 || text[i]>126)valid=0;
        rename_ui.done=0;rename_ui.result=AF_INVALID;
        if(valid && af_text_name_valid((const char *)text,n)) {
            copy((uint8_t *)rename_ui.new_name,text,n);rename_ui.new_name[n]=0;rename_ui.new_bytes=n;
            if(n==rename_ui.old_bytes && ui_equal(text,rename_ui.old_name,n))rename_ui.result=AF_MANAGE_CANCEL;
            else {rename_ui.done=1;rename_ui.result=AF_OK;}
        }
    }
    /* 此BL仅在原Done弱校验成功后执行；非私有会话原样关闭，不读写会话模型。 */
    ((void (*)(void *))ap_address(rename_close[layout]))(controller);
    if(own && (before!=0x4cf || !manager || *(const Word *)manager!=ap_address(0x58d2fb8) ||
       get32((uint8_t *)manager+0x1e8)!=rename_layouts[layout])) {
        rename_ui.done=0;rename_ui.result=AF_STALE;
    }
}
#define RENAME_DONE(n) void af_ap_rename_done_##n(void *c){rename_done_close(c,n);}
RENAME_DONE(0) RENAME_DONE(1) RENAME_DONE(2) RENAME_DONE(3)
#define RENAME_LEAVE(n) \
extern void af_stock_rename_leave_##n(void *,const uint32_t *); \
void af_ap_rename_leave_##n(void *c,const uint32_t *next){ \
    int own=rename_identity(c,n);uint32_t ds=next?*next:UINT32_MAX; \
    if(own)rename_protect_lifecycle(); \
    af_stock_rename_leave_##n(c,next); \
    if(own){ \
        rename_ui.owner=0;rename_ui.owner_epoch=0; \
        if(ds>=0xcc && ds<=0xcf){rename_ui.done=0;if(!rename_ui.tainted)rename_ui.result=AF_MANAGE_CANCEL;rename_ui.expected=ds;} \
        else if(ds==0x259 || ds==0x1e2){rename_ui.done=0;if(!rename_ui.tainted)rename_ui.result=AF_MANAGE_CANCEL;} \
        else {rename_ui.phase=3; \
            if(rename_ui.tainted || (!ui_main(ds) && ds!=0xd4)){rename_ui.done=0;rename_ui.result=AF_STALE;} \
        } \
    } \
}
RENAME_LEAVE(0) RENAME_LEAVE(1) RENAME_LEAVE(2) RENAME_LEAVE(3)
#define RENAME_INIT(n) \
extern void af_stock_rename_init_##n(void *,const uint32_t *); \
void af_ap_rename_init_##n(void *c,const uint32_t *previous){ \
    int own=rename_ui.models && (rename_ui.phase==1 || rename_ui.phase==2) && !rename_ui.owner && \
        rename_ui.expected==rename_layouts[n] && c && *(const Word *)c==ap_address(rename_controllers[n]) && \
        get32((uint8_t *)c+0x178)==rename_layouts[n]; \
    if(own)rename_protect_lifecycle(); \
    af_stock_rename_init_##n(c,previous); \
    if(own){rename_ui.owner=c;rename_ui.owner_epoch=rename_ui.epoch;rename_ui.phase=2;} \
}
RENAME_INIT(0) RENAME_INIT(1) RENAME_INIT(2) RENAME_INIT(3)

uint32_t af_ap_rename_title(uint32_t group) {
    if(rename_ui.phase && rename_ui.models && group==AF_MANAGE_MENU_ROOT && get32(rename_value(6))==11)return AF_AP_NAMES_FILTER_TITLE;
    return ((uint32_t (*)(uint32_t))ap_address(0x1bd54d8))(group);
}
uint32_t af_ap_rename_state(void) {return rename_ui.phase;}
static int rename_finish(uint32_t current) {
    if(rename_ui.phase!=3)return AF_BUSY;
    int result=rename_ui.result;
    if(rename_ui.done && !ui_equal(rename_value(1),rename_ui.new_name,rename_ui.new_bytes+1))result=AF_MANAGE_CANCEL;
    rename_restore();
    if(current!=rename_ui.slot || !rename_unchanged())result=AF_STALE;
    if(result==AF_OK && rename_ui.done) {
        AfApManageRequest request={0};request.op=AF_MANAGE_RENAME;
        request.source_slot=request.target_slot=rename_ui.slot;request.name_bytes=rename_ui.new_bytes;
        copy((uint8_t *)request.name,(const uint8_t *)rename_ui.new_name,request.name_bytes);
        result=af_ap_manage_submit(&af_ap_manager,&af_ap_catalog,&request);
    }
    rename_ui.owner=0;rename_ui.owner_epoch=0;rename_ui.phase=rename_ui.done=0;return result;
}

int af_ap_manage_ui_chosen(void *context,const AfApTargetChoice *choice) {
    AfApManageRequest request={0};AfPreset zero={0};
    if(context!=&af_ap_catalog || !choice || choice->version!=AF_AP_TARGET_CHOICE_VERSION ||
       choice->bytes!=sizeof(*choice) || !choice->generation || choice->overwrite>1 ||
       !choice->target_slot || choice->target_slot>AF_USERS ||
       (choice->op!=AF_MANAGE_COPY && choice->op!=AF_MANAGE_CREATE && choice->op!=AF_MANAGE_CLEAR && choice->op!=AF_MANAGE_EXPORT && choice->op!=AF_MANAGE_IMPORT))return AF_INVALID;
    if(manage_ui_stage!=3 || manage_ui_root!=AF_TARGETS_ROOT || manage_ui_op!=choice->op ||
       manage_selection_generation!=choice->generation)return AF_STALE;
    if(choice->op!=AF_MANAGE_CREATE?!ui_slot_snapshot(&choice->target,&af_ap_catalog.slots[choice->target_slot-1]):
       !ui_pure_snapshot(&choice->target,&af_ap_catalog.slots[choice->target_slot-1]))return AF_STALE;
    if(choice->op==AF_MANAGE_EXPORT?(choice->overwrite || !choice->target.present):
       (choice->target_slot<=6 && choice->op!=AF_MANAGE_CLEAR?!choice->overwrite:
        choice->overwrite!=choice->target.present))return AF_INVALID;
    if(choice->op==AF_MANAGE_CLEAR) {
        uint32_t current=ui_active_user_slot();
        if(!choice->target.present || !choice->overwrite || current==UINT32_MAX ||
           choice->target_slot==current)return AF_STALE;
    }
    if(choice->op==AF_MANAGE_COPY || choice->op==AF_MANAGE_EXPORT) {
        if(!choice->source_slot || choice->source_slot>AF_USERS || !choice->source.present ||
           (choice->op==AF_MANAGE_COPY?choice->source_slot==choice->target_slot:
            (choice->source_slot!=choice->target_slot || ui_active_user_slot()!=choice->source_slot)))return AF_INVALID;
        if(!ui_slot_snapshot(&choice->source,&af_ap_catalog.slots[choice->source_slot-1]))return AF_STALE;
    } else if(choice->source_slot || choice->source.present || choice->source.revision || choice->source.reserved ||
              !ui_equal(&choice->source.initial,&zero,sizeof(zero)) || !ui_equal(&choice->source.saved,&zero,sizeof(zero)) ||
              !ui_equal(&choice->source.working,&zero,sizeof(zero)))return AF_INVALID;
    if(choice->op==AF_MANAGE_IMPORT) {
        if(!prepared || !enabled || restricted_layout() || !manage_ui_import_valid)return AF_STALE;
        int status=af_ap_media_import_request(&request);
        if(status!=AF_OK)return status;
        if(!ui_equal(&request,&manage_ui_import,sizeof(request)))return AF_STALE;
    }
    request.op=choice->op;request.source_slot=choice->source_slot;request.target_slot=choice->target_slot;request.overwrite=choice->overwrite;
    if(choice->op!=AF_MANAGE_CLEAR && choice->op!=AF_MANAGE_EXPORT && choice->op!=AF_MANAGE_IMPORT) {
    const uint32_t *(*language)(void)=(void *)ap_address(0x28b0464);
    if(*language()==25) {
        const char prefix[]="自定义";for(unsigned i=0;i<sizeof(prefix)-1;++i)request.name[request.name_bytes++]=prefix[i];
    }
    request.name[request.name_bytes++]='C';request.name[request.name_bytes++]=(char)('0'+choice->target_slot/10);
    request.name[request.name_bytes++]=(char)('0'+choice->target_slot%10);request.initial.params[6]=3;
    }
    int result=af_ap_manage_submit(&af_ap_manager,&af_ap_catalog,&request);
    if(result!=AF_OK)(void)af_ap_manage_menu_notice(choice->op,result);
    return result;
}

/* 清空排队后若用户切到目标槽，完成失败回执且不调用存储pump。 */
static void ui_clear_before_pump(void) {
    if(af_ap_manager.phase!=AF_MANAGE_QUEUED)return;
    uint32_t op=af_ap_manager.job.request.op;
    if(op!=AF_MANAGE_CLEAR && op!=AF_MANAGE_RENAME && op!=AF_MANAGE_EXPORT)return;
    uint32_t current=ui_active_user_slot(),target=af_ap_manager.job.request.target_slot;
    if(op==AF_MANAGE_CLEAR?(current!=UINT32_MAX && target!=current):(current==target && target>=1 && target<=AF_USERS &&
        ui_slot_snapshot(&af_ap_manager.job.target,&af_ap_catalog.slots[target-1])))return;
    AfApManageJob job;AfApManageReceipt receipt={0};
    if(af_ap_manage_take(&af_ap_manager,&job)!=AF_OK)return;
    receipt.ticket=job.ticket;receipt.result=AF_STALE;
    if(af_ap_manage_finish(&af_ap_manager,&af_ap_catalog,&receipt)==AF_OK)
        (void)af_ap_manage_menu_notice(op,AF_STALE);
}
/* 不保留呈现器指针，不碰全局属性脏位或成像/存储订阅。 */
Word af_ap_refresh(void *manager) {
    /* 只有既有原UI刷新拥有者解析成像接口，启动登记不在别的线程偷偷绑定。 */
    imaging_provider_poll(manager);
    /* 通信推进仍由原后端拥有者完成；此处每次刷新仅尝试最新明确请求一次。 */
    imaging_pending_poll(manager);
    /* 真实UI拥有者串行执行一个管理任务；成功只由持久化后端回读回执确认。 */
    int nested_refresh=ui_manage_poll(manager);
    ui_clear_before_pump();
    (void)af_ap_manage_service_poll();
    int target_refresh=af_ap_targets_refresh(),browser_refresh=af_ap_browser_refresh(),cards_refresh=af_ap_cards_refresh();
    int media_refresh=af_ap_media_refresh();
    Word original = af_stock_refresh(manager);
    if(af_ap_manage_menu_refresh() || target_refresh || browser_refresh || cards_refresh || media_refresh || nested_refresh)return 1;
    uint32_t i;
    const Word *views = (const Word *)((const uint8_t *)manager+0x338);
    if (!refresh_pending) return original;
    if (!enabled || current_menu() != refresh_menu || restricted_layout()) {
        refresh_pending = 0;return original;
    }
    for (i = 0; i < 15; ++i) {
        if (views[i]) {
            Word table = *(const Word *)views[i];
            /* 同包主页面和调参页虚表的实际地址点，不能接受任意相似对象。 */
            if (table == ap_address(0x58ca670) || table == ap_address(0x58ca720)) return 1;
        }
    }
    return original;
}

/* 只替换已扩展描述符的current；不改原690或任何其他页面的getter。 */
uint32_t af_ap_current(void) {
    AfUiRoute route;int value;
    if(!prepared)return UINT32_MAX;
    const uint32_t *(*native)(void)=(void *)ap_address(0x28ae4b0);
    if(enabled && selected_valid && !restricted_layout() && *native()==selected_native &&
       af_ui_resolve(selected_menu,&route)==AF_OK && route.kind==AF_UI_USER &&
       route.selector==selected_selector && user_menu(selected_menu) &&
       af_ui_read(&af_ap_catalog,selected_menu,0,&value)==AF_OK)return selected_selector;
    selected_valid=0;
    return ((uint32_t (*)(void))original_current)();
}

static int isolate_selection(uint32_t selector) {
    AfUiRoute route;
    uint32_t menu = current_menu();
    int value;
    int user = af_ui_resolve(menu,&route) == AF_OK && route.kind == AF_UI_USER &&
        (route.slot>6 || af_ap_catalog.slots[route.slot-1].present);
    if (selector >= 19 || (enabled && user && !restricted_layout())) {
        if(restricted_layout())imaging_factory(UINT32_MAX);
        if (enabled && user && route.selector == selector && !restricted_layout() &&
            af_ui_read(&af_ap_catalog,menu,0,&value) == AF_OK) {
            const uint32_t *(*native)(void)=(void *)ap_address(0x28ae4b0);
            selected_menu=menu;selected_selector=selector;selected_native=*native();selected_valid=1;
            request_refresh(menu);imaging_user(route.slot);
        }
        /* 任何扩展值均不委派；不把界面选中当作成像提交成功。 */
        return 1;
    }
    return 0;
}

void af_ap_select(uint32_t selector) {
    if (!isolate_selection(selector)) {selected_valid=0;af_stock_select(selector);imaging_factory(selector);}
}
void af_ap_preview(void *context, uint32_t selector) {
    if (!isolate_selection(selector)) {selected_valid=0;af_stock_preview(context,selector);imaging_factory(selector);}
}
void af_ap_preview_menu(uint32_t menu) {
    AfUiRoute route;
    if (af_ui_resolve(menu,&route) == AF_OK && route.kind == AF_UI_USER &&
        (new_menu(menu) || (enabled && user_menu(menu) && !restricted_layout()))) {
        /* 外层消息封装也会通知0x3ced，必须在封装之前分流用户预览。 */
        if (menu == current_menu()) (void)isolate_selection(route.selector);
        return;
    }
    selected_valid=0;af_stock_preview_menu(menu);
    imaging_factory(af_ui_resolve(menu,&route)==AF_OK?route.selector:UINT32_MAX);
}

/* 自然原登记已完成后的附加入口；绝不重放原5591项range。调用者仍须完成产品准入。 */
int af_ap_after_original_registration(const AfApRegistration *receipt) {
    uint32_t i;
#ifdef AF_AP_DYNAMIC
    if (!bound) return AF_INVALID;
#endif
    if (!receipt || (uintptr_t)receipt%_Alignof(AfApRegistration) || !receipt->registry ||
        (receipt->registry&7u) || receipt->version!=1 || receipt->bytes!=sizeof(*receipt) ||
        receipt->base!=ap_base || receipt->constructor_index!=104 ||
        receipt->phase!=AF_AP_LIFE_RECORDED || receipt->serial!=1 || receipt->rows!=5591 ||
        receipt->begin!=ap_address(0x5030590) || receipt->end!=ap_address(0x5046300)) return AF_INVALID;
    if (prepared) return AF_BUSY;
    void *registry=(void *)receipt->registry;
    if (registry!=*(void **)ap_address(0x5915b80) ||
        *(const Word *)((const uint8_t *)registry+0x28)!=5591) return AF_STALE;
    original_rows = *(const Word *)ap_address(0x5858b08+0x58);
    original_count = *(const uint32_t *)ap_address(0x5858b08+0x54);
    original_current = *(const Word *)ap_address(0x5858b08+0x78);
    if (original_rows != ap_address(0x3f4a280) || original_count != 19 ||
        original_current!=ap_address(0x1c05f18)) return AF_STALE;
    copy(&af_ap_rows[0][0],(const uint8_t *)ap_address(0x3f4a280),18*128);
    for (i = 0; i < 14; ++i) {
        uint8_t *row = af_ap_rows[18+i];
        copy(row,(const uint8_t *)ap_address(0x3f4ab00),128);
        put32(row,AF_UI_NEW_FIRST+i);put32(row+4,AF_UI_NEW_FIRST+i);
        put32(row+8,0x0200abde + i);put32(row+0x34,19+i);
        /* 五类空哨兵：动作、动态类型、资格、替代资格、附加数据。 */
        put32(row+0x70,0x00550029);put32(row+0x74,0x00121086);
        put32(row+0x78,0x4f);put32(row+0x7c,0);
        additions[i][0] = AF_UI_NEW_FIRST+i;
        additions[i][1] = (Word)row;
    }
    copy(af_ap_rows[32],(const uint8_t *)ap_address(0x3f4ab80),128);
    af_stock_register(registry,additions,additions+14);
    af_catalog_init(&af_ap_catalog);
    af_ap_manage_init(&af_ap_manager);
    prepared = 1;
    return AF_OK;
}

/* 既有前置BL接法保持原登记一次；所有附加逻辑复用post-original入口。 */
void af_ap_register(void *registry, const void *begin, const void *end) {
    af_stock_register(registry,begin,end);
    if (prepared || begin!=(const void *)ap_address(0x5030590) ||
        end!=(const void *)ap_address(0x5046300) || registry!=*(void **)ap_address(0x5915b80)) return;
    AfApRegistration receipt={1,sizeof(receipt),ap_base,(uintptr_t)registry,(uintptr_t)begin,
        (uintptr_t)end,*(const Word *)((const uint8_t *)registry+0x28),1,104,AF_AP_LIFE_RECORDED};
    (void)af_ap_after_original_registration(&receipt);
}

/* 离线研究开关；不接机身菜单，不代表相机可部署。禁用恢复原描述符。 */
int af_ap_research_enable(uint32_t value) {
    if(rename_ui.phase)return AF_BUSY;
    if(!value && imaging.requested)return AF_BUSY;
    Word current_rows,current_getter;
    uint32_t current_count;
    if (!prepared || value > 1) return AF_INVALID;
    current_rows = *(const Word *)ap_address(0x5858b08+0x58);
    current_count = *(const uint32_t *)ap_address(0x5858b08+0x54);
    current_getter = *(const Word *)ap_address(0x5858b08+0x78);
    if (current_rows != (enabled ? (Word)af_ap_rows : original_rows) ||
        current_count != (enabled ? 33u : original_count) ||
        current_getter != (enabled ? (Word)af_ap_current : original_current)) return AF_STALE;
    *(Word *)ap_address(0x5858b08+0x58) = value ? (Word)af_ap_rows : original_rows;
    *(uint32_t *)ap_address(0x5858b08+0x54) = value ? 33 : original_count;
    *(Word *)ap_address(0x5858b08+0x78) = value ? (Word)af_ap_current : original_current;
    selected_valid=0;enabled = value;layout_allowed = 0;display_menu = 0;refresh_pending = 0;
    return AF_OK;
}

Word af_ap_alias(uint32_t menu) {
    if(enabled && (af_ap_manage_menu_is_id(menu) || af_ap_targets_is_id(menu) || af_ap_browser_is_id(menu) || af_ap_cards_is_id(menu)))return menu;
    if (enabled && new_menu(menu)) return menu;
    return af_stock_alias(menu);
}
Word af_ap_alias_object(void *object, uint32_t menu) {
    if(enabled && (af_ap_manage_menu_is_id(menu) || af_ap_targets_is_id(menu) || af_ap_browser_is_id(menu) || af_ap_cards_is_id(menu)))return menu;
    if (enabled && new_menu(menu)) return menu;
    return af_stock_alias_object(object,menu);
}
Word af_ap_name(void *object, uint32_t menu) {
    if(enabled && af_ap_manage_menu_is_id(menu))return af_ap_names_compact(menu);
    if(enabled && af_ap_targets_is_id(menu))return af_ap_names_compact(menu);
    if(enabled && af_ap_browser_is_id(menu))return af_ap_names_compact(menu);
    if(enabled && af_ap_cards_is_id(menu))return af_ap_names_compact(menu);
    if (enabled && new_menu(menu)) return 0x0200abde + menu-AF_UI_NEW_FIRST;
    return af_stock_name(object,menu);
}
/* 新身份使用原图形资源末尾追加的独立编号图标，不能进入旧六槽图标表。
 * 原图标列表布局不会绘制文字回退，不能仅把-1当作完整新槽呈现。
 * 调用者须提供已校验的六份UXD；禁用时拒绝新ID，旧身份全部委派。 */
Word af_ap_icon(void *object, uint32_t menu) {
    if(af_ap_manage_menu_is_id(menu) || af_ap_targets_is_id(menu) || af_ap_browser_is_id(menu) || af_ap_cards_is_id(menu))return UINT32_MAX;
    if (new_menu(menu)) return enabled ? 0x02001ea4+menu-AF_UI_NEW_FIRST : UINT32_MAX;
    return af_stock_icon(object,menu);
}
Word af_ap_icon_alternate(void *object, uint32_t menu) {
    if(af_ap_manage_menu_is_id(menu) || af_ap_targets_is_id(menu) || af_ap_browser_is_id(menu) || af_ap_cards_is_id(menu))return UINT32_MAX;
    if (new_menu(menu)) return enabled ? 0x02001ea4+menu-AF_UI_NEW_FIRST : UINT32_MAX;
    return af_stock_icon_alternate(object,menu);
}
/* 原父页面树只含已有身份。新ID须先映射到同一创意外观描述符，
 * 否则原索引/导航会落到默认页面；不写原父页面缓存或冒用旧槽身份。 */
Word af_ap_parent(void *object, uint32_t menu) {
    if(enabled && af_ap_manage_menu_is_id(menu))return af_ap_manage_menu_parent(menu);
    if(enabled && af_ap_targets_is_id(menu))return af_ap_targets_parent(menu);
    if(enabled && af_ap_browser_is_id(menu))return af_ap_browser_parent(menu);
    if(enabled && af_ap_cards_is_id(menu))return af_ap_cards_parent(menu);
    if (enabled && new_menu(menu)) return 0x1e6;
    return af_stock_parent(object,menu);
}
/* 调参呈现器与主页面分别读取参数，不能只挂钩主页面快照。
 * 原呈现器+0x3b18是当前身份副本；原焦点查询不访问18项成像数组。 */
static int parameter_snapshot(void *object,AfUiRoute *route,AfPreset *preset,uint32_t *option) {
    uint32_t menu=current_menu();
    int user=af_ui_resolve(menu,route)==AF_OK && route->kind==AF_UI_USER;
    uint32_t (*focus)(void *)=(uint32_t (*)(void *))ap_address(0x220b4e0);
    if(!new_menu(menu) && !(enabled && user && !restricted_layout()))return AF_UI_NATIVE;
    if(!new_menu(menu) && route->slot<=6 && !af_ap_catalog.slots[route->slot-1].present)return AF_UI_NATIVE;
    if(!enabled || !user || restricted_layout() || !object ||
       get32((const uint8_t *)object+0x3b18)!=menu ||
       af_read(&af_ap_catalog,route->slot,0,preset)!=AF_OK)return AF_INVALID;
    *option=focus(object);
    return *option<=8?AF_OK:AF_INVALID;
}
Word af_ap_parameter_value(void *object) {
    AfUiRoute route;AfPreset preset;uint32_t option;
    int result=parameter_snapshot(object,&route,&preset,&option);
    if(result==AF_UI_NATIVE)return af_stock_parameter_value(object);
    if(result!=AF_OK)return 0;
    return option?(uint32_t)(int32_t)preset.params[option-1]:base_internal(preset.base);
}
Word af_ap_parameter_disabled(void *object) {
    AfUiRoute route;AfPreset preset;uint32_t option;
    int result=parameter_snapshot(object,&route,&preset,&option);
    if(result==AF_UI_NATIVE)return af_stock_parameter_disabled(object);
    return result!=AF_OK || (option==0 && preset.kind!=0);
}
Word af_ap_parameter_default(void *object) {
    AfUiRoute route;AfPreset preset;uint32_t option;
    int result=parameter_snapshot(object,&route,&preset,&option);
    if(result==AF_UI_NATIVE)return af_stock_parameter_default(object);
    if(result!=AF_OK)return 0;
    if(option==0)return base_internal(af_ap_catalog.slots[route.slot-1].initial.base);
    return (uint32_t)(int32_t)af_ap_catalog.slots[route.slot-1].initial.params[option-1];
}
Word af_ap_base_available(void) {
    uint32_t menu=current_menu();AfUiRoute route;AfPreset preset;
    if(new_menu(menu) || (enabled && user_menu(menu) && !restricted_layout())) {
        return enabled && !restricted_layout() && af_ui_resolve(menu,&route)==AF_OK &&
            af_read(&af_ap_catalog,route.slot,0,&preset)==AF_OK && preset.kind==0;
    }
    return af_stock_base_available();
}
/* 这是参数页顶行的逻辑组标题，不是底部基底名称。
 * 私有槽保持CreativeLook组；基底图形由下一独立入口按leaf查询。 */
Word af_ap_base_label(uint32_t menu) {
    uint32_t current=current_menu();AfUiRoute route;AfPreset preset;
    if(enabled && user_menu(current) && !restricted_layout()) {
        if(af_ui_resolve(current,&route)!=AF_OK || af_read(&af_ap_catalog,route.slot,0,&preset)!=AF_OK)
            return UINT32_MAX;
        menu=0x1e6;
    }
    return af_stock_base_label(menu);
}
/* 原底部基底图标按标题资源走有限表。新槽标题不在该表，
 * 在这一个BL处改用工作基底的原名称，再交原映射器选择原图形。 */
Word af_ap_base_icon(void *object,uint32_t resource) {
    uint32_t current=current_menu();AfUiRoute route;AfPreset preset;
    if(enabled && user_menu(current) && !restricted_layout()) {
        uint32_t (*name)(uint32_t)=(uint32_t (*)(uint32_t))ap_address(0x1bd5508);
        if(af_ui_resolve(current,&route)!=AF_OK || af_read(&af_ap_catalog,route.slot,0,&preset)!=AF_OK)
            return UINT32_MAX;
        resource=name(base_menu(preset.base));
    }
    return af_stock_base_icon(object,resource);
}
void af_ap_parameter_layout(void *object) {
    static const uint32_t offsets[4]={0x80,0x90,0xf0,0x280};
    static const uint32_t kinds[4]={0,0,0x11,0};
    Word targets[4],records;uint32_t menu=current_menu(),i;
    af_stock_parameter_layout(object);
    if(!enabled || !new_menu(menu) || restricted_layout() ||
       *(const Word *)object!=ap_address(0x58ca720) ||
       get32((const uint8_t *)object+0x3b18)!=menu)return;
    records=*(const Word *)((const uint8_t *)object+0x90);
    if(!records)return;
    /* 原呈现器使用相同记录和+0x2c可见标志；先检查四项，避免部分发布。 */
    for(i=0;i<4;i++) {
        const uint8_t *record=(const uint8_t *)(records+offsets[i]);
        if(get32(record)!=kinds[i] || !(targets[i]=*(const Word *)(record+8)))return;
    }
    for(i=0;i<4;i++)*(uint8_t *)(targets[i]+0x2c)=i!=1;
}
Word af_ap_visible(void *object, uint32_t menu) {
    if(af_ap_manage_menu_is_id(menu) || af_ap_targets_is_id(menu) || af_ap_browser_is_id(menu) || af_ap_cards_is_id(menu))return enabled?1:0;
    /* 新ID不能索引旧全局缓存；暂借原C06的页面资格，尚需独立机身规则。 */
    if (new_menu(menu)) return enabled ? af_stock_visible(object,0x85d) : 0;
    return af_stock_visible(object,menu);
}

static void hide_parameters(void *output) {
    uint32_t i;
    uint8_t *out = output;
    for (i = 0; i < 8; ++i) {
        put32(out+0x34+12*i,UINT32_MAX);
        put32(out+0x38+12*i,0);out[0x3c+12*i] = 1;
    }
    put32(out+0x94,0);
}

void af_ap_display(void *context, void *output, void *changed, const void *snapshot) {
    uint32_t selector = get32((const uint8_t *)snapshot+0x20);
    uint32_t menu = current_menu();
    uint8_t flags[8] = {0,0,0,0,0,0,0,0};
    AfUiRoute selected;
    if(enabled && af_ui_resolve(menu,&selected)==AF_OK && selected.kind==AF_UI_USER)
        (void)af_ap_manage_menu_context(selected.slot);
    layout_allowed = enabled && get32(snapshot) == 0 && !restricted_layout();
    display_menu = menu;
    if (refresh_menu == menu) refresh_pending = 0;
    if (enabled && user_menu(menu) && layout_allowed) {
        if (af_ui_snapshot(&af_ap_catalog,menu,flags,output) != AF_OK) hide_parameters(output);
        return;
    }
    /* 扩展选择值任何情况下都不能进入18项数组；旧六槽非目标布局保持原路径。 */
    if (selector >= 19 || (enabled && new_menu(menu))) {hide_parameters(output);return;}
    af_stock_display(context,output,changed,snapshot);
}

static int selected_option(void *object) {
    uint32_t (*focus)(void *) = (uint32_t (*)(void *))ap_address(0x1af11f0);
    uint32_t (*get)(void *) = (uint32_t (*)(void *))ap_address(0x220929c);
    uint32_t component = focus((uint8_t *)object+0x1a0), option;
    if (component < 0xf || component > 0x1f) return -1;
    option = get(object);
    return option<=8?(int)option:-1;
}
static int selected_parameter(void *object) {
    int option=selected_option(object);
    return option>=1?option-1:-1;
}

Word af_ap_inhibited(void *object) {
    int value;
    uint32_t menu = current_menu();
    if (enabled && user_menu(menu) && layout_allowed && !restricted_layout()) {
        int option = selected_option(object);
        AfUiRoute route;AfPreset preset;
        if(menu!=display_menu || option<0)return 1;
        if(option==0)return af_ui_resolve(menu,&route)!=AF_OK ||
            af_read(&af_ap_catalog,route.slot,0,&preset)!=AF_OK || preset.kind!=0;
        return af_ui_read(&af_ap_catalog,menu,(uint32_t)option-1,&value)!=AF_OK;
    }
    if (new_menu(menu)) return 1;
    return af_stock_inhibited(object);
}

Word af_ap_direct(void *object, const void *event) {
    uint32_t menu = current_menu();
    if (!event) return 0;
    if (get32((const uint8_t *)event+0xc) == 0xd &&
        ((enabled && user_menu(menu) && layout_allowed && !restricted_layout()) || new_menu(menu))) {
        if (af_ap_inhibited(object) == 0) {
            int before, value, parameter = selected_parameter(object);
            uint32_t byte = ((const uint8_t *)event)[0x30];
            int signed_value = byte < 128 ? (int)byte : (int)byte-256;
            if (af_ui_read(&af_ap_catalog,menu,(uint32_t)parameter,&before) == AF_OK &&
                af_ui_assign(&af_ap_catalog,menu,(uint32_t)parameter,signed_value,&value) == AF_OK &&
                before != value) {AfUiRoute route;request_refresh(menu);
                    if(af_ui_resolve(menu,&route)==AF_OK)imaging_user(route.slot);}
        }
        /* 原厂返回1表示消息已处理，不表示保存、刷新或成像成功。 */
        return 1;
    }
    Word result=af_stock_direct(object,event);
    if(get32((const uint8_t *)event+0xc)==0xd)imaging_factory(UINT32_MAX);
    return result;
}

static void step(void *object, uint32_t direction, uint32_t parameter,
                 void (*stock)(void *,uint32_t)) {
    uint32_t menu = current_menu();
    int before, value;
    if (enabled && user_menu(menu) && layout_allowed && !restricted_layout()) {
        if (menu == display_menu && af_ui_read(&af_ap_catalog,menu,parameter,&before) == AF_OK &&
            af_ui_step(&af_ap_catalog,menu,parameter,direction,&value) == AF_OK &&
            before != value) {AfUiRoute route;request_refresh(menu);
                if(af_ui_resolve(menu,&route)==AF_OK)imaging_user(route.slot);}
        /* 刷新只请求原厂界面调度，CP仍未接入。 */
        return;
    }
    if (new_menu(menu)) return;
    stock(object,direction);
    /* 原厂明确调参后沿原状态消费，不能滞留上一完整factory pending。 */
    imaging_factory(UINT32_MAX);
}
#define STEP(N) void af_ap_step_##N(void *object,uint32_t direction) { \
    step(object,direction,N,af_stock_step_##N); }
STEP(0) STEP(1) STEP(2) STEP(3) STEP(4) STEP(5) STEP(6) STEP(7)

/* 前六槽迁移留给原厂模型就绪后的适配；初始化期不读取尚未就绪的BSS。 */
int af_ap_native_seed(uint32_t slot) {
    AfPreset preset = {0};
    uint32_t p, selector;
    const uint32_t *(*base)(void) = (const uint32_t *(*)(void))ap_address(0x28c54cc);
    if (!prepared || slot < 1 || slot > 6) return AF_INVALID;
    /* 外部调用者还必须证明模型就绪，此入口不自动在构造期执行。 */
    selector = base()[slot+9];
    selector = base_selector(selector);
    if (selector == UINT32_MAX) return AF_INVALID;
    preset.base = (uint8_t)selector;
    for (p = 0; p < 8; ++p) {
        const int32_t *(*get)(void) = (const int32_t *(*)(void))ap_address(getters[p]);
        int32_t value = get()[slot+9];
        if (value < -128 || value > 127) return AF_INVALID;
        preset.params[p] = (int8_t)value;
    }
    return af_install(&af_ap_catalog,slot,&preset,0);
}
