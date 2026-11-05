/* 创建/另存为/清空的原D4目标选择；所有存储行为由显式chosen回调的拥有者负责。 */
#include "af_ap_targets.h"
static struct {
    uintptr_t base;const AfCatalog *catalog;void *context;
    int (*chosen)(void *,const AfApTargetChoice *);
    uint32_t registered,enabled,active,delivering,serial,focus,refresh,op,source,intent,stage,target,protected_slot;
    uint64_t generation;int result;
    AfSlot snapshot[AF_USERS];
    uint8_t records[22][128],confirmation[2][128],descriptor[192];
    char confirmation_title[64],confirmation_action[32];
    char labels[AF_USERS][24];
} native;
static void copy(void *a,const void *b,size_t n) {uint8_t *x=a;const uint8_t *y=b;while(n--)*x++=*y++;}
static void put32(void *a,uint32_t v) {copy(a,&v,4);}
static void putptr(void *a,uintptr_t v) {copy(a,&v,sizeof(v));}
static uintptr_t va(uintptr_t off) {return native.base+off;}
static int apart(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;return x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static int same_bytes(const void *a,const void *b,size_t n) {const uint8_t *x=a,*y=b;while(n--)if(*x++!=*y++)return 0;return 1;}
static int preset_same(const AfPreset *a,const AfPreset *b) {
    return a->base==b->base && a->kind==b->kind && same_bytes(a->params,b->params,AF_PARAMETERS) &&
           same_bytes(a->payload_sha256,b->payload_sha256,32) && same_bytes(a->lut_sha256,b->lut_sha256,32);
}
static int slot_same(const AfSlot *a,const AfSlot *b) {
    return a->present==b->present && a->saved_revision==b->saved_revision &&
           !a->pending.request && !b->pending.request && preset_same(&a->initial,&b->initial) &&
           preset_same(&a->saved,&b->saved) && preset_same(&a->working,&b->working);
}
static int pure_slot(const AfSlot *slot) {
    return slot->present && !slot->initial.kind && !slot->saved.kind && !slot->working.kind &&
           af_validate(&slot->initial)==AF_OK && af_validate(&slot->saved)==AF_OK && af_validate(&slot->working)==AF_OK;
}
static int managed_slot(const AfSlot *slot) {
    if(pure_slot(slot))return 1;
    const AfPreset *a=&slot->initial,*b=&slot->saved,*c=&slot->working;
    return slot->present && a->kind==1 && b->kind==1 && c->kind==1 &&
           af_validate(a)==AF_OK && af_validate(b)==AF_OK && af_validate(c)==AF_OK &&
           a->base==b->base && a->base==c->base &&
           same_bytes(a->payload_sha256,b->payload_sha256,32) && same_bytes(a->payload_sha256,c->payload_sha256,32) &&
           same_bytes(a->lut_sha256,b->lut_sha256,32) && same_bytes(a->lut_sha256,c->lut_sha256,32);
}
static void capture(AfApManageSlot *to,const AfSlot *from) {
    uint8_t *out=(uint8_t *)to;for(size_t i=0;i<sizeof(*to);++i)out[i]=0;
    to->revision=from->saved_revision;to->present=from->present;
    if(from->present){to->initial=from->initial;to->saved=from->saved;to->working=from->working;}
}
static int source_valid(void) {
    return native.op==AF_TARGETS_CREATE || native.op==AF_TARGETS_CLEAR || native.op==AF_TARGETS_IMPORT ||
           (native.source>0 && native.source<=AF_USERS && managed_slot(&native.catalog->slots[native.source-1]) &&
            slot_same(&native.snapshot[native.source-1],&native.catalog->slots[native.source-1]));
}
static uint32_t token(uint32_t low) {return AF_TARGETS_TEXT_FIRST+(native.serial<<8)+low;}
static uint32_t admitted(void) {return 1;}
static uint32_t action_menu(void) {return native.op==AF_TARGETS_IMPORT?AF_MANAGE_MENU_IMPORT:native.op==AF_TARGETS_EXPORT?AF_MANAGE_MENU_EXPORT:native.op==AF_TARGETS_CLEAR?AF_MANAGE_MENU_CLEAR:
    native.op==AF_TARGETS_COPY?AF_MANAGE_MENU_COPY:AF_MANAGE_MENU_CREATE;}
int af_ap_targets_is_id(uint32_t menu) {return menu>=AF_TARGETS_ROOT && menu<=AF_TARGETS_CANCEL;}
uint32_t af_ap_targets_parent(uint32_t menu) {
    return menu==AF_TARGETS_ROOT?0x15e7u:af_ap_targets_is_id(menu)?AF_TARGETS_ROOT:UINT32_MAX;
}
uint32_t af_ap_targets_name(uint32_t menu) {
    return menu==AF_TARGETS_ROOT?AF_TARGETS_TEXT_FIRST:
           af_ap_targets_is_id(menu) && native.serial?token(menu-AF_TARGETS_ROOT):UINT32_MAX;
}
int af_ap_targets_is_token(uint32_t value) {return (value&0xffff0000u)==AF_TARGETS_TEXT_FIRST;}
int af_ap_targets_available(uint32_t menu) {
    if(!native.enabled || !native.active || !source_valid() || menu<AF_TARGETS_SLOT_FIRST || menu>=AF_TARGETS_SLOT_FIRST+AF_USERS)return 0;
    uint32_t index=menu-AF_TARGETS_SLOT_FIRST;
    return (native.op!=AF_TARGETS_EXPORT || index+1==native.source) && !(native.op==AF_TARGETS_COPY && index+1==native.source) &&
           !(native.op==AF_TARGETS_CLEAR && (index+1==native.protected_slot || !native.snapshot[index].present)) &&
           slot_same(&native.snapshot[index],&native.catalog->slots[index]) &&
           (!native.snapshot[index].present || (native.op!=AF_TARGETS_CREATE?
            (managed_slot(&native.snapshot[index]) && managed_slot(&native.catalog->slots[index])):
            (pure_slot(&native.snapshot[index]) && pure_slot(&native.catalog->slots[index]))));
}
static int chinese(void) {
    if(!native.base)return 0;
    const uint32_t *(*get)(void)=(void *)va(0x28b0464);const uint32_t *language=get();return language && *language==25u;
}
static const char *confirm_text(int title) {
    char *out=title?native.confirmation_title:native.confirmation_action;
    const char *prefix=native.op==AF_TARGETS_EXPORT?
        (chinese()?(title?"导出已保存 ":"导出 "):(title?"Export saved ":"Export ")):
        native.op==AF_TARGETS_CLEAR?
        (chinese()?(title?"确认清空 ":"清空 "):(title?"Clear ":"Clear ")):
        (chinese()?(title?"确认覆盖 ":"覆盖 "):(title?"Overwrite ":"Replace "));
    size_t n=0;while(prefix[n]){out[n]=prefix[n];++n;}
    out[n++]='C';out[n++]=(char)('0'+native.target/10);out[n++]=(char)('0'+native.target%10);
    if(title)out[n++]='?';out[n]=0;return out;
}
const char *af_ap_targets_command_text(uint32_t menu) {
    if(!native.enabled || !native.active || native.stage<AF_TARGETS_CONFIRM_WAIT)return 0;
    if(menu==AF_TARGETS_CANCEL)return chinese()?"取消":"Back";
    return native.target && menu==AF_TARGETS_SLOT_FIRST+native.target-1?(chinese()?(native.op==AF_TARGETS_EXPORT?"导出":native.op==AF_TARGETS_CLEAR?"清空":"覆盖"):"Yes"):0;
}
const char *af_ap_targets_text(uint32_t value) {
    if(!af_ap_targets_is_token(value))return 0;
    int chinese=0;
    if(native.base) {
        const uint32_t *(*get)(void)=(void *)va(0x28b0464);
        const uint32_t *language=get();chinese=language && *language==25u;
    }
    if(value==AF_TARGETS_TEXT_FIRST && native.active && native.stage>=AF_TARGETS_CONFIRM_WAIT)return confirm_text(1);
    if(value==AF_TARGETS_TEXT_FIRST && native.op==AF_TARGETS_IMPORT)return chinese?"导入LUT：选择槽位":"Import LUT: target";
    if(value==AF_TARGETS_TEXT_FIRST && native.op==AF_TARGETS_CLEAR)return chinese?"清空：选择槽位":"Clear: target";
    if(value==AF_TARGETS_TEXT_FIRST)return native.op==AF_TARGETS_COPY?
        (chinese?"另存为：选择槽位":"Save As: target"):(chinese?"新建：选择槽位":"Create: target");
    if(!native.enabled || (value&0xff00u)!=(native.serial<<8) || !native.serial)return chinese?"选择已变化":"Selection changed";
    uint32_t low=value&255u;if(low==21)return chinese?"取消":"Cancel";
    if(native.active && native.stage>=AF_TARGETS_CONFIRM_WAIT)return low==native.target?confirm_text(0):(chinese?"选择已变化":"Selection changed");
    if(low<1 || low>AF_USERS)return chinese?"选择已变化":"Selection changed";
    unsigned index=low-1;char *label=native.labels[index];
    copy(label,"C00",4);label[1]=(char)('0'+low/10);label[2]=(char)('0'+low%10);
    const char *suffix=index<6&&!native.catalog->slots[index].present?(chinese?"（原厂）":" (Original)"):
                       native.op==AF_TARGETS_CLEAR && low==native.protected_slot?(chinese?"（使用中）":" (Active)"):
                       native.op==AF_TARGETS_COPY && low==native.source?(chinese?"（源槽）":" (Source)"):
                       native.catalog->slots[index].present?(af_ap_targets_available(AF_TARGETS_SLOT_FIRST+index)?(chinese?"（已占用）":" (Occupied)"):(chinese?"（不可用）":" (Unavailable)")):
                       af_ap_targets_available(AF_TARGETS_SLOT_FIRST+index)?(chinese?"（空闲）":" (Empty)"):
                                                                                          (chinese?"（不可用）":" (Unavailable)");
    size_t n=0;while(suffix[n])++n;copy(label+3,suffix,n+1);return label;
}
int af_ap_targets_bind(const AfApTargetsBinding *binding) {
    static const struct {uintptr_t off;uint32_t word;} checks[]={
        {0x1c91c40,0xa9bc7bfd},{0x1c91e94,0xa9bc7bfd},{0x1c935e0,0xa9bc7bfd},{0x1c938a8,0xa9bc7bfd},
        {0x1bd906c,0x91002002},{0x1bd924c,0xa9bc7bfd},{0x1bd9348,0xa9bc7bfd},
        {0x28a87e8,0xf002b2a0},{0x28a87fc,0xf002b2a0},{0x28a88ac,0xf002b2a0},{0x28a88c0,0xf002b2a0},
        {0x21edb44,0xa9be7bfd},{0x21edb68,0xa9be7bfd},{0x21f3ed8,0xa9bd7bfd},{0x21f4130,0xa9bd7bfd},
        {0x21f0864,0x39405001},{0x21f0830,0x39405001},
        {0x1bdb214,0xa9be7bfd},{0x1bd6384,0xa9be7bfd},{0x28b0464,0xf002b260}};
    if(native.base)return AF_BUSY;
    if(!binding || binding->version!=AF_AP_TARGETS_VERSION || binding->bytes!=sizeof(*binding) ||
       !binding->ap_base || (binding->ap_base&4095u) || binding->ap_base>UINTPTR_MAX-0x8e84000u ||
       !binding->catalog || !binding->context || !binding->chosen ||
       ((uintptr_t)binding->catalog%_Alignof(AfCatalog)) || !apart(binding->catalog,sizeof(*binding->catalog),&native,sizeof(native)))return AF_INVALID;
    uintptr_t base=binding->ap_base;
    for(unsigned i=0;i<sizeof(checks)/sizeof(checks[0]);++i)if(*(const uint32_t *)(base+checks[i].off)!=checks[i].word)return AF_STALE;
    if(*(const uint32_t *)(base+0x5845f28+0x20)!=0xd4 || *(const uint32_t *)(base+0x5845f28+0x54)!=8 ||
       *(const uintptr_t *)(base+0x5845f28+0x58)!=base+0x3f52680)return AF_STALE;
    native.base=base;native.catalog=binding->catalog;native.context=binding->context;native.chosen=binding->chosen;
    native.result=AF_EMPTY;return AF_OK;
}
int af_ap_targets_register(void) {
    uintptr_t rows,descriptors,parents,secondary,pairs[22][2],descriptor[2];uint32_t secondary_rows[22][2];
    uint32_t parent[2]={AF_TARGETS_ROOT,AF_TARGETS_DESCRIPTOR};
    if(!native.base)return AF_INVALID;if(native.registered)return AF_BUSY;
    rows=*(const uintptr_t *)va(0x5915b80);descriptors=*(const uintptr_t *)va(0x59611f8);
    parents=*(const uintptr_t *)va(0x593fbd8);secondary=*(const uintptr_t *)va(0x59430d0);
    if(!rows || !descriptors || !parents || !secondary)return AF_EMPTY;
    int (*contains)(void *,const uint32_t *)=(void *)va(0x1bd906c);
    for(uint32_t key=AF_TARGETS_ROOT;key<=AF_TARGETS_CANCEL;++key)
        if(contains((void *)rows,&key) || contains((void *)secondary,&key))return AF_EXISTS;
    if(contains((void *)descriptors,parent+1) || contains((void *)parents,parent))return AF_EXISTS;
    for(unsigned i=0;i<22;++i) {
        uint8_t *row=native.records[i];copy(row,(const void *)va(i?0x3f52680:0x3fe4a00),128);
        put32(row,AF_TARGETS_ROOT+i);put32(row+4,AF_TARGETS_ROOT+i);put32(row+8,AF_TARGETS_TEXT_FIRST);
        put32(row+0x10,UINT32_MAX);put32(row+0x30,0);put32(row+0x34,0);
        /* 这是新私有记录的产品型号半字表，原厂记录保持。不是拍摄模式表。 */
        for(unsigned j=0;j<20;++j){uint16_t value=1;copy(row+0x44+j*2,&value,2);}
        put32(row+0x70,0x00550029);put32(row+0x74,0x00121086);put32(row+0x78,0x4f);put32(row+0x7c,0);
        pairs[i][0]=AF_TARGETS_ROOT+i;pairs[i][1]=(uintptr_t)row;secondary_rows[i][0]=secondary_rows[i][1]=AF_TARGETS_ROOT+i;
    }
    copy(native.descriptor,(const void *)va(0x5845f28),192);
    put32(native.descriptor,AF_TARGETS_TEXT_FIRST);put32(native.descriptor+0xc,UINT32_MAX);
    put32(native.descriptor+0x54,21);putptr(native.descriptor+0x58,(uintptr_t)native.records[1]);
    putptr(native.descriptor+0x70,(uintptr_t)admitted);putptr(native.descriptor+0x78,(uintptr_t)af_ap_targets_current);
    putptr(native.descriptor+0x80,(uintptr_t)af_ap_targets_focus);putptr(native.descriptor+0x88,(uintptr_t)af_ap_targets_action);
    putptr(native.descriptor+0x98,0);putptr(native.descriptor+0xa0,0);putptr(native.descriptor+0xa8,(uintptr_t)af_ap_targets_disabled);
    descriptor[0]=AF_TARGETS_DESCRIPTOR;descriptor[1]=(uintptr_t)native.descriptor;
    ((void (*)(void *,const void *,const void *))va(0x1c91e94))((void *)rows,pairs,pairs+22);
    ((void (*)(void *,const void *,const void *))va(0x1c91c40))((void *)descriptors,descriptor,descriptor+2);
    ((void (*)(void *,const void *,const void *))va(0x1c935e0))((void *)parents,parent,parent+2);
    ((void (*)(void *,const void *,const void *))va(0x1c938a8))((void *)secondary,secondary_rows,secondary_rows+22);
    native.registered=1;return AF_OK;
}
int af_ap_targets_enable(uint32_t value) {
    if(!native.registered || value>1)return AF_INVALID;if(native.delivering)return AF_BUSY;
    if(!value)(void)af_ap_targets_cancel();native.enabled=value;return AF_OK;
}
int af_ap_targets_begin(uint32_t op,uint32_t source_slot,uint64_t generation) {
    if(!native.registered || !native.enabled || !generation || (op!=AF_TARGETS_COPY && op!=AF_TARGETS_CREATE && op!=AF_TARGETS_IMPORT) ||
       (op==AF_TARGETS_COPY?(!source_slot || source_slot>AF_USERS):source_slot!=0))return AF_INVALID;
    if(native.active || native.delivering)return AF_BUSY;
    if(generation<=native.generation)return AF_STALE;if(native.serial==255)return AF_EXHAUSTED;
    if(op==AF_TARGETS_COPY) {
        const AfSlot *source=&native.catalog->slots[source_slot-1];
        if(!source->present)return AF_EMPTY;if(source->pending.request)return AF_BUSY;
        if(!managed_slot(source))return AF_INVALID;
    }
    copy(native.snapshot,native.catalog->slots,sizeof(native.snapshot));native.op=op;native.source=source_slot;native.protected_slot=0;
    native.generation=generation;++native.serial;native.active=1;native.focus=0;native.target=0;native.stage=AF_TARGETS_SELECT;
    native.result=AF_EMPTY;native.refresh=1;
    for(unsigned i=1;i<22;++i){put32(native.records[i]+8,token(i));put32(native.records[i]+0x34,token(i));}
    put32(native.descriptor+0x54,21);putptr(native.descriptor+0x58,(uintptr_t)native.records[1]);
    return AF_OK;
}
int af_ap_targets_begin_clear(uint32_t protected_slot,uint64_t generation) {
    if(protected_slot>AF_USERS)return AF_INVALID;
    /* 复用同一会话初始化；此调用不接受未保护的CLEAR通用begin。 */
    int result=af_ap_targets_begin(AF_TARGETS_CREATE,0,generation);
    if(result==AF_OK){native.op=AF_TARGETS_CLEAR;native.protected_slot=protected_slot;}
    return result;
}
int af_ap_targets_begin_export(uint32_t source_slot,uint64_t generation) {
    if(source_slot<1 || source_slot>AF_USERS)return AF_INVALID;
    int result=af_ap_targets_begin(AF_TARGETS_COPY,source_slot,generation);
    if(result!=AF_OK)return result;
    native.op=AF_TARGETS_EXPORT;native.target=source_slot;native.stage=AF_TARGETS_CONFIRM_WAIT;
    copy(native.confirmation[0],native.records[21],128);
    copy(native.confirmation[1],native.records[source_slot],128);
    put32(native.descriptor+0x54,2);putptr(native.descriptor+0x58,(uintptr_t)native.confirmation);
    return AF_OK;
}
static uint32_t model(uintptr_t getter) {
    const uint32_t *(*get)(void)=(void *)va(getter);return *get();
}
static uint32_t parent_of(uint32_t menu) {return ((uint32_t (*)(uint32_t))va(0x1bdb214))(menu);}
static uint32_t screen_of(uint32_t menu) {return ((uint32_t (*)(uint32_t))va(0x1bd6384))(menu);}
static uint32_t route(uint32_t menu) {
    static const uintptr_t values[2]={0x28a87e8,0x28a88ac},metadata[2]={0x28a87fc,0x28a88c0};
    static const uintptr_t setters[2]={0x21f3ed8,0x21f4130},notifiers[2]={0x21f0864,0x21f0830};
    /* 3bc是原行的目标screen；+7c=0的私有行由原查询自然返回335。 */
    uint32_t screen=screen_of(menu),next[2]={menu,screen};
    for(unsigned i=0;i<2;++i) {
        uintptr_t scope[2]={0,0};_Alignas(8) uint8_t change[32]={0};
        void *(*value)(void)=(void *)va(values[i]);void *(*meta)(void)=(void *)va(metadata[i]);
        ((void (*)(void *))va(0x21edb44))(scope);
        putptr(change,(uintptr_t)value());putptr(change+8,(uintptr_t)meta());
        put32(change+0x10,i?0x3bc:0x3b7);putptr(change+0x18,scope[1]);
        ((void (*)(void *,uint32_t))va(setters[i]))(change,next[i]);
        ((void (*)(void *))va(notifiers[i]))(change);
        ((void (*)(void *))va(0x21edb68))(scope);
    }
    return screen;
}
static uint32_t first_menu(void) {
    /* 原生旧六不是空槽；优先真正空槽，其次已管理overlay，最后原生替换。 */
    for(unsigned i=6;i<AF_USERS;++i)if(!native.snapshot[i].present && af_ap_targets_available(AF_TARGETS_SLOT_FIRST+i))return AF_TARGETS_SLOT_FIRST+i;
    for(unsigned i=0;i<AF_USERS;++i)if(native.snapshot[i].present && af_ap_targets_available(AF_TARGETS_SLOT_FIRST+i))return AF_TARGETS_SLOT_FIRST+i;
    for(unsigned i=0;i<6;++i)if(af_ap_targets_available(AF_TARGETS_SLOT_FIRST+i))return AF_TARGETS_SLOT_FIRST+i;
    return AF_TARGETS_CANCEL;
}
int af_ap_targets_show(void) {
    if(!native.enabled || !native.active || native.stage!=AF_TARGETS_SELECT)return AF_INVALID;
    uint32_t menu=model(0x28a87e8),parent=parent_of(menu),first;
    if(!((parent==0x15e7 && menu==action_menu()) ||
         (parent==AF_TARGETS_ROOT && af_ap_targets_is_id(menu))))return AF_STALE;
    if(!source_valid())return AF_STALE;first=first_menu();
    if(parent_of(first)!=AF_TARGETS_ROOT)return AF_STALE;
    uint32_t screen=route(first);
    if(model(0x28a87e8)!=first || model(0x28a88ac)!=screen)return AF_STALE;
    native.focus=af_ap_targets_name(first);native.refresh=1;return AF_OK;
}
int af_ap_targets_back(void) {
    if(!native.enabled || native.active || native.delivering)return AF_INVALID;
    uint32_t menu=model(0x28a87e8);
    if(!af_ap_targets_is_id(menu) || parent_of(menu)!=AF_TARGETS_ROOT || parent_of(action_menu())!=0x15e7)return AF_STALE;
    uint32_t screen=route(action_menu());
    if(model(0x28a87e8)!=action_menu() || model(0x28a88ac)!=screen)return AF_STALE;
    native.refresh=1;return AF_OK;
}
uint32_t af_ap_targets_current(void) {
    if(!native.active)return 0;
    return native.focus?native.focus:af_ap_targets_name(native.stage>=AF_TARGETS_CONFIRM_WAIT?AF_TARGETS_CANCEL:first_menu());
}
uint32_t af_ap_targets_stage(void) {return native.active?native.stage:0;}
int af_ap_targets_presented(void) {
    if(!native.enabled || !native.active)return AF_INVALID;
    if(native.stage==AF_TARGETS_SELECT || native.stage==AF_TARGETS_CONFIRM)return AF_OK;
    if(native.stage!=AF_TARGETS_CONFIRM_WAIT || model(0x28a87e8)!=AF_TARGETS_CANCEL || parent_of(AF_TARGETS_CANCEL)!=AF_TARGETS_ROOT)return AF_STALE;
    native.stage=AF_TARGETS_CONFIRM;native.result=AF_EMPTY;return AF_OK;
}
void af_ap_targets_focus(uint32_t value) {
    if(!native.enabled || !native.active)return;native.focus=0;
    if((value&0xffffff00u)!=(AF_TARGETS_TEXT_FIRST+(native.serial<<8)))return;
    uint32_t low=value&255u;
    if(low>0 && low<=21 && (native.stage==AF_TARGETS_SELECT || low==21 || low==native.target))native.focus=value;
}
/* 源变化只禁用目标，不锁死Cancel；否则用户可能无法退出选择页。 */
uint32_t af_ap_targets_disabled(void) {return !native.enabled || !native.active;}
int af_ap_targets_intent(uint32_t menu) {
    if(!menu){native.intent=0;return AF_OK;}
    if(native.intent || native.delivering)return AF_BUSY;
    if(!native.enabled || !native.active || menu==AF_TARGETS_ROOT || !af_ap_targets_is_id(menu))return AF_INVALID;
    if(model(0x28a87e8)!=menu)return AF_STALE;
    if(native.stage==AF_TARGETS_CONFIRM_WAIT && menu!=AF_TARGETS_CANCEL)return AF_BUSY;
    native.intent=menu;return AF_OK;
}
void af_ap_targets_action(uint32_t menu) {
    if(!menu || native.intent!=menu)return;
    native.intent=0;
    if(!native.enabled || !native.active || native.delivering)return;native.result=AF_STALE;
    /* 一次性许可已消费，仍只接当前真实行，不把预览当作确认。 */
    if(model(0x28a87e8)!=menu || !af_ap_targets_is_id(menu) || parent_of(menu)!=AF_TARGETS_ROOT)return;
    if(menu==AF_TARGETS_CANCEL){(void)af_ap_targets_cancel();return;}
    if(!source_valid())return;
    if(menu>=AF_TARGETS_SLOT_FIRST && menu<AF_TARGETS_SLOT_FIRST+AF_USERS &&
       !slot_same(&native.snapshot[menu-AF_TARGETS_SLOT_FIRST],&native.catalog->slots[menu-AF_TARGETS_SLOT_FIRST]))return;
    if(!af_ap_targets_available(menu)) {native.result=AF_EXISTS;return;}
    uint32_t target=menu-AF_TARGETS_SLOT_FIRST+1;
    /* 旧六没有overlay仍是原生槽；不能按文件不存在当作可直接写入的空槽。 */
    if(native.stage==AF_TARGETS_SELECT && (native.snapshot[target-1].present || target<=6)) {
        if(native.serial==255){native.result=AF_EXHAUSTED;return;}
        native.target=target;++native.serial;native.focus=0;native.stage=AF_TARGETS_CONFIRM_WAIT;
        for(unsigned i=1;i<22;++i){put32(native.records[i]+8,token(i));put32(native.records[i]+0x34,token(i));}
        copy(native.confirmation[0],native.records[21],128);copy(native.confirmation[1],native.records[target],128);
        put32(native.descriptor+0x54,2);putptr(native.descriptor+0x58,(uintptr_t)native.confirmation);
        native.result=AF_TARGETS_CONFIRM_REQUIRED;native.refresh=1;return;
    }
    if(native.stage==AF_TARGETS_CONFIRM_WAIT ||
       (native.stage==AF_TARGETS_CONFIRM && (target!=native.target ||
        (!native.snapshot[target-1].present && !(target<=6 &&
         (native.op==AF_TARGETS_COPY || native.op==AF_TARGETS_CREATE || native.op==AF_TARGETS_IMPORT))))))return;
    AfApTargetChoice choice={0};choice.version=AF_AP_TARGET_CHOICE_VERSION;choice.bytes=sizeof(choice);
    choice.generation=native.generation;choice.op=native.op;choice.source_slot=native.source;choice.target_slot=target;
    choice.overwrite=native.stage==AF_TARGETS_CONFIRM && native.op!=AF_TARGETS_EXPORT;
    if(native.source)capture(&choice.source,&native.snapshot[native.source-1]);
    capture(&choice.target,&native.snapshot[target-1]);
    native.active=0;native.delivering=1;
    native.result=native.chosen(native.context,&choice);
    native.delivering=0;native.refresh=1;
}
int af_ap_targets_cancel(void) {
    if(!native.registered)return AF_INVALID;if(native.delivering)return AF_BUSY;
    native.intent=0;native.active=0;native.focus=0;native.result=AF_TARGETS_CANCELLED;native.refresh=1;return AF_OK;
}
int af_ap_targets_result(void) {return native.result;}
int af_ap_targets_refresh(void) {int result=(int)native.refresh;native.refresh=0;return result;}
