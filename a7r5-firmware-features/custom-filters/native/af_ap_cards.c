/* 复用原D4注册/呈现，仅真实ENTER许可可产生同代卡槽选择。 */
#include "af_ap_cards.h"

static struct {
    uintptr_t base;
    uint64_t generation;
    uint32_t registered,enabled,active,serial,focus,selected,refresh,intent;
    int result;
    AfApCardSelection selection;
    uint8_t records[4][128],rows[3][128],descriptor[192];
} native;

static void copy(void *a,const void *b,size_t n) {uint8_t *x=a;const uint8_t *y=b;while(n--)*x++=*y++;}
static void put32(void *a,uint32_t v) {copy(a,&v,4);}
static void putptr(void *a,uintptr_t v) {copy(a,&v,sizeof(v));}
static uintptr_t va(uintptr_t off) {return native.base+off;}
static int separate(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static uint32_t epoch(uint32_t low) {return AF_CARDS_TEXT_FIRST+(native.serial<<8)+low;}
static uint32_t code(uint32_t menu) {
    return menu==AF_CARDS_MENU_SLOT0?1u:menu==AF_CARDS_MENU_SLOT1?2u:menu==AF_CARDS_MENU_CANCEL?3u:0u;
}
static uint32_t admitted(void) {return 1;}
static uint32_t model(void) {
    const uint32_t *(*get)(void)=(void *)va(0x28a87e8);
    const uint32_t *value=get();return value?*value:UINT32_MAX;
}
static uint32_t parent_of(uint32_t menu) {return ((uint32_t (*)(uint32_t))va(0x1bdb214))(menu);}
static int chinese(void) {
    if(!native.base)return 0;
    const uint32_t *(*get)(void)=(void *)va(0x28b0464);
    const uint32_t *language=get();return language && *language==25u;
}
int af_ap_cards_is_id(uint32_t menu) {return menu>=AF_CARDS_MENU_ROOT && menu<=AF_CARDS_MENU_CANCEL;}
uint32_t af_ap_cards_parent(uint32_t menu) {
    return menu==AF_CARDS_MENU_ROOT?0x15e7u:af_ap_cards_is_id(menu)?AF_CARDS_MENU_ROOT:UINT32_MAX;
}
uint32_t af_ap_cards_name(uint32_t menu) {
    if(menu==AF_CARDS_MENU_ROOT)return AF_CARDS_TEXT_FIRST;
    uint32_t low=code(menu);return low && native.serial?epoch(low):UINT32_MAX;
}
uint32_t af_ap_cards_compact(uint32_t menu) {
    if(menu==AF_CARDS_MENU_ROOT)return AF_CARDS_TEXT_FIRST;
    uint32_t low=code(menu);return low && native.serial?epoch(low+4):UINT32_MAX;
}
int af_ap_cards_is_token(uint32_t token) {return (token&0xffff0000u)==AF_CARDS_TEXT_FIRST;}
const char *af_ap_cards_text(uint32_t token) {
    if(!af_ap_cards_is_token(token))return 0;
    int zh=chinese();
    if(token==AF_CARDS_TEXT_FIRST)return zh?"选择SD卡":"Choose SD card";
    if(!native.enabled || !native.serial || (token&0xff00u)!=(native.serial<<8))return zh?"列表已变化":"List changed";
    switch(token&255u) {
    case 1:return zh?"卡槽1":"Card slot 1";
    case 2:return zh?"卡槽2":"Card slot 2";
    case 3:case 7:return zh?"取消":"Cancel";
    case 5:return zh?"卡1":"SD1";
    case 6:return zh?"卡2":"SD2";
    default:return zh?"列表已变化":"List changed";
    }
}
int af_ap_cards_bind(const AfApCardsBinding *binding) {
    static const struct {uintptr_t off;uint32_t word;} checks[]={
        {0x1c91c40,0xa9bc7bfd},{0x1c91e94,0xa9bc7bfd},{0x1c935e0,0xa9bc7bfd},
        {0x1c938a8,0xa9bc7bfd},{0x1bd906c,0x91002002},
        {0x28a87e8,0xf002b2a0},{0x1bdb214,0xa9be7bfd},{0x28b0464,0xf002b260}};
    if(native.base)return AF_BUSY;
    if(!binding || binding->version!=AF_AP_CARDS_VERSION || binding->bytes!=sizeof(*binding) ||
       !binding->ap_base || (binding->ap_base&4095u) || binding->ap_base>UINTPTR_MAX-0x8e84000u)return AF_INVALID;
    uintptr_t base=binding->ap_base;
    for(unsigned i=0;i<sizeof(checks)/sizeof(checks[0]);++i)
        if(*(const uint32_t *)(base+checks[i].off)!=checks[i].word)return AF_STALE;
    if(*(const uint32_t *)(base+0x5845f28+0x20)!=0xd4 ||
       *(const uint32_t *)(base+0x5845f28+0x54)!=8 ||
       *(const uintptr_t *)(base+0x5845f28+0x58)!=base+0x3f52680)return AF_STALE;
    native.base=base;native.result=AF_EMPTY;return AF_OK;
}
int af_ap_cards_register(void) {
    if(!native.base)return AF_INVALID;
    if(native.registered)return AF_BUSY;
    uintptr_t rows=*(const uintptr_t *)va(0x5915b80),descriptors=*(const uintptr_t *)va(0x59611f8);
    uintptr_t parents=*(const uintptr_t *)va(0x593fbd8),secondary=*(const uintptr_t *)va(0x59430d0);
    if(!rows || !descriptors || !parents || !secondary)return AF_EMPTY;
    int (*contains)(void *,const uint32_t *)=(void *)va(0x1bd906c);
    uint32_t parent[2]={AF_CARDS_MENU_ROOT,AF_CARDS_MENU_DESCRIPTOR};
    for(uint32_t key=AF_CARDS_MENU_ROOT;key<=AF_CARDS_MENU_CANCEL;++key)
        if(contains((void *)rows,&key) || contains((void *)secondary,&key))return AF_EXISTS;
    if(contains((void *)descriptors,parent+1) || contains((void *)parents,parent))return AF_EXISTS;
    uintptr_t pairs[4][2],descriptor[2];uint32_t self[4][2];
    for(unsigned i=0;i<4;++i) {
        uint8_t *row=native.records[i];copy(row,(const void *)va(i?0x3f52680:0x3fe4a00),128);
        put32(row,AF_CARDS_MENU_ROOT+i);put32(row+4,AF_CARDS_MENU_ROOT+i);
        put32(row+8,AF_CARDS_TEXT_FIRST);put32(row+0x10,UINT32_MAX);put32(row+0x34,0);
        put32(row+0x70,0x00550029);put32(row+0x74,0x00121086);put32(row+0x78,0x4f);put32(row+0x7c,0);
        pairs[i][0]=AF_CARDS_MENU_ROOT+i;pairs[i][1]=(uintptr_t)row;
        self[i][0]=self[i][1]=AF_CARDS_MENU_ROOT+i;
    }
    copy(native.descriptor,(const void *)va(0x5845f28),192);
    put32(native.descriptor,AF_CARDS_TEXT_FIRST);put32(native.descriptor+0xc,UINT32_MAX);
    put32(native.descriptor+0x54,3);putptr(native.descriptor+0x58,(uintptr_t)native.rows);
    putptr(native.descriptor+0x70,(uintptr_t)admitted);
    putptr(native.descriptor+0x78,(uintptr_t)af_ap_cards_current);
    putptr(native.descriptor+0x80,(uintptr_t)af_ap_cards_focus);
    putptr(native.descriptor+0x88,(uintptr_t)af_ap_cards_action);
    put32(native.descriptor+0x90,0);putptr(native.descriptor+0x98,0);putptr(native.descriptor+0xa0,0);
    putptr(native.descriptor+0xa8,(uintptr_t)af_ap_cards_disabled);
    descriptor[0]=AF_CARDS_MENU_DESCRIPTOR;descriptor[1]=(uintptr_t)native.descriptor;
    ((void (*)(void *,const void *,const void *))va(0x1c91e94))((void *)rows,pairs,pairs+4);
    ((void (*)(void *,const void *,const void *))va(0x1c91c40))((void *)descriptors,descriptor,descriptor+2);
    ((void (*)(void *,const void *,const void *))va(0x1c935e0))((void *)parents,parent,parent+2);
    ((void (*)(void *,const void *,const void *))va(0x1c938a8))((void *)secondary,self,self+4);
    native.registered=1;return AF_OK;
}
int af_ap_cards_enable(uint32_t value) {
    if(!native.registered || value>1)return AF_INVALID;
    if(!value)(void)af_ap_cards_cancel();native.enabled=value;return AF_OK;
}
int af_ap_cards_begin(uint64_t generation) {
    if(!native.registered || !native.enabled || !generation)return AF_INVALID;
    if(native.active || native.selected || native.intent)return AF_BUSY;
    if(generation<=native.generation)return AF_STALE;
    if(native.serial==255)return AF_EXHAUSTED;
    native.generation=generation;++native.serial;native.active=1;native.result=AF_EMPTY;native.focus=0;
    for(unsigned i=1;i<4;++i) {
        uint32_t token=epoch(code(AF_CARDS_MENU_ROOT+i));
        put32(native.records[i]+8,token);put32(native.records[i]+0x34,token);
    }
    /* 默认取消，不因初选/方向回调而切换真实卡。 */
    copy(native.rows[0],native.records[3],128);
    copy(native.rows[1],native.records[1],128);
    copy(native.rows[2],native.records[2],128);
    native.refresh=1;return AF_OK;
}
uint32_t af_ap_cards_current(void) {
    if(!native.enabled || !native.active)return 0;
    return native.focus?native.focus:epoch(3);
}
void af_ap_cards_focus(uint32_t token) {
    if(!native.enabled || !native.active)return;
    native.focus=0;
    if((token&0xffffff00u)!=(AF_CARDS_TEXT_FIRST+(native.serial<<8)))return;
    uint32_t low=token&255u;if(low>=1 && low<=3)native.focus=token;
}
uint32_t af_ap_cards_disabled(void) {return !native.enabled || !native.active;}
int af_ap_cards_intent(uint32_t menu) {
    if(!menu){native.intent=0;return AF_OK;}
    if(native.intent)return AF_BUSY;
    if(!native.enabled || !native.active || !code(menu))return AF_INVALID;
    if(model()!=menu || parent_of(menu)!=AF_CARDS_MENU_ROOT)return AF_STALE;
    native.intent=menu;return AF_OK;
}
void af_ap_cards_action(uint32_t menu) {
    if(!menu || native.intent!=menu)return;
    native.intent=0;
    if(!native.enabled || !native.active)return;
    if(model()!=menu || parent_of(menu)!=AF_CARDS_MENU_ROOT) {
        native.active=0;native.result=AF_STALE;native.refresh=1;return;
    }
    if(menu==AF_CARDS_MENU_CANCEL){(void)af_ap_cards_cancel();return;}
    if(menu!=AF_CARDS_MENU_SLOT0 && menu!=AF_CARDS_MENU_SLOT1)return;
    native.selection.generation=native.generation;
    native.selection.slot=menu==AF_CARDS_MENU_SLOT0?0u:1u;native.selection.reserved=0;
    native.selected=1;native.active=0;native.result=AF_OK;native.refresh=1;
}
int af_ap_cards_cancel(void) {
    if(!native.registered)return AF_INVALID;
    native.intent=0;native.active=0;native.selected=0;native.focus=0;
    native.result=AF_CARDS_CANCELLED;native.refresh=1;return AF_OK;
}
int af_ap_cards_take(uint64_t generation,AfApCardSelection *out) {
    if(!generation || !out || !separate(out,sizeof(*out),&native,sizeof(native)))return AF_INVALID;
    if(generation!=native.generation)return AF_STALE;
    if(!native.selected)return AF_EMPTY;
    *out=native.selection;native.selected=0;return AF_OK;
}
int af_ap_cards_result(void) {return native.result;}
int af_ap_cards_refresh(void) {int value=(int)native.refresh;native.refresh=0;return value;}
