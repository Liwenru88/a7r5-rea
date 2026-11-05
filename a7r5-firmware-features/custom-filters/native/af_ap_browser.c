/* 使用原注册器、原D4呈现与原高亮/确认分派；这里只返回同代文件索引。 */
#include "af_ap_browser.h"
#include "af_text.h"
static struct {
    uintptr_t base;
    uint32_t registered,enabled,active,serial,page,count,focus,selected,refresh,intent;
    int result;
    AfMediaList list;
    AfApBrowserSelection selection;
    uint8_t records[68][128],page_rows[20][128],descriptor[192];
} native;
static void copy(void *a,const void *b,size_t n) {uint8_t *x=a;const uint8_t *y=b;while(n--)*x++=*y++;}
static void put32(void *a,uint32_t v) {copy(a,&v,4);}
static void putptr(void *a,uintptr_t v) {copy(a,&v,sizeof(v));}
static uintptr_t va(uintptr_t off) {return native.base+off;}
static int separate(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=UINTPTR_MAX-n && y<=UINTPTR_MAX-m && (x+n<=y || y+m<=x);
}
static uint32_t epoch(uint32_t low) {return AF_BROWSER_TEXT_FIRST+(native.serial<<8)+low;}
static uint32_t code(uint32_t menu) {
    if(menu>=AF_BROWSER_MENU_FILE_FIRST && menu<AF_BROWSER_MENU_FILE_FIRST+AF_MEDIA_MAX)
        return menu-AF_BROWSER_MENU_FILE_FIRST+4;
    return menu==AF_BROWSER_MENU_PREVIOUS?1:menu==AF_BROWSER_MENU_NEXT?2:menu==AF_BROWSER_MENU_CANCEL?3:0;
}
static uint32_t admitted(void) {return 1;}
static int valid(const AfMediaList *list) {
    if(!list->generation || list->count>AF_MEDIA_MAX)return 0;
    for(unsigned j=0;j<list->count;++j) {
        const AfMediaEntry *e=&list->entries[j];size_t n=0;
        while(n<AF_MEDIA_NAME_BYTES && e->name[n])++n;
        if(n<6 || n>=AF_MEDIA_NAME_BYTES || !e->size || e->size>AF_MEDIA_SOURCE_MAX ||
           e->nanoseconds<0 || e->nanoseconds>=1000000000)return 0;
        if(!af_media_kind(e->name,n))return 0;
        for(size_t i=0;i<n;++i)if(e->name[i]=='/' || e->name[i]=='\\')return 0;
        for(size_t at=0;at<n;) {
            size_t end=at+63;if(end>n)end=n;
            while(end<n && ((uint8_t)e->name[end]&0xc0)==0x80)--end;
            if(end==at || !af_text_name_valid(e->name+at,end-at))return 0;at=end;
        }
        if(j) {
            unsigned i=0;const uint8_t *a=(const uint8_t *)list->entries[j-1].name,*b=(const uint8_t *)e->name;
            while(i<AF_MEDIA_NAME_BYTES && a[i] && a[i]==b[i])++i;
            if(i==AF_MEDIA_NAME_BYTES || a[i]>=b[i])return 0;
        }
    }
    return 1;
}
static void page_build(void) {
    uint32_t start=native.page*AF_BROWSER_PAGE_FILES,end=start+AF_BROWSER_PAGE_FILES;
    if(end>native.list.count)end=native.list.count;
    native.count=0;
    for(uint32_t i=start;i<end;++i)copy(native.page_rows[native.count++],native.records[1+i],128);
    if(native.page)copy(native.page_rows[native.count++],native.records[65],128);
    if(end<native.list.count)copy(native.page_rows[native.count++],native.records[66],128);
    copy(native.page_rows[native.count++],native.records[67],128);
    put32(native.descriptor+0x54,native.count);
    putptr(native.descriptor+0x58,(uintptr_t)native.page_rows);
    native.focus=0;native.refresh=1;
}
int af_ap_browser_is_id(uint32_t menu) {return menu>=AF_BROWSER_MENU_ROOT && menu<=AF_BROWSER_MENU_CANCEL;}
uint32_t af_ap_browser_parent(uint32_t menu) {
    return menu==AF_BROWSER_MENU_ROOT?0x15e7u:af_ap_browser_is_id(menu)?AF_BROWSER_MENU_ROOT:UINT32_MAX;
}
uint32_t af_ap_browser_name(uint32_t menu) {
    if(menu==AF_BROWSER_MENU_ROOT)return AF_BROWSER_TEXT_FIRST;
    uint32_t low=code(menu);return low && native.serial?epoch(low):UINT32_MAX;
}
int af_ap_browser_is_token(uint32_t token) {return (token&0xffff0000u)==AF_BROWSER_TEXT_FIRST;}
static int browser_chinese(void) {
    if(!native.base)return 0;
    const uint32_t *(*get)(void)=(void *)va(0x28b0464);
    const uint32_t *language=get();return language && *language==25u;
}
const char *af_ap_browser_text(uint32_t token) {
    if(!af_ap_browser_is_token(token))return 0;
    int chinese=browser_chinese();
    if(token==AF_BROWSER_TEXT_FIRST)return native.list.count?(chinese?"选择LUT或滤镜配方":"Choose LUT or preset"):
                                                                     (chinese?"没有LUT或滤镜配方":"No LUT or preset files");
    if(!native.enabled || !native.serial || (token&0xff00u)!=(native.serial<<8))return chinese?"列表已变化":"List changed";
    uint32_t low=token&255u;
    if(low==1)return chinese?"上一页":"Previous page";
    if(low==2)return chinese?"下一页":"Next page";
    if(low==3)return chinese?"取消":"Cancel";
    return low>=4 && low-4<native.list.count?native.list.entries[low-4].name:(chinese?"列表已变化":"List changed");
}
int af_ap_browser_bind(const AfApBrowserBinding *binding) {
    static const struct {uintptr_t off;uint32_t word;} checks[]={
        {0x1c91c40,0xa9bc7bfd},{0x1c91e94,0xa9bc7bfd},{0x1c935e0,0xa9bc7bfd},
        {0x1c938a8,0xa9bc7bfd},
        {0x1bd906c,0x91002002},{0x1bd924c,0xa9bc7bfd},{0x1bd9348,0xa9bc7bfd},
        {0x28a87e8,0xf002b2a0},{0x28a87fc,0xf002b2a0},
        {0x28a88ac,0xf002b2a0},{0x28a88c0,0xf002b2a0},
        {0x21edb44,0xa9be7bfd},{0x21edb68,0xa9be7bfd},
        {0x21f3ed8,0xa9bd7bfd},{0x21f4130,0xa9bd7bfd},
        {0x21f0864,0x39405001},{0x21f0830,0x39405001},
        {0x1bdb214,0xa9be7bfd},{0x1bd6384,0xa9be7bfd},{0x28b0464,0xf002b260}};
    if(native.base)return AF_BUSY;
    if(!binding || binding->version!=AF_AP_BROWSER_VERSION || binding->bytes!=sizeof(*binding) ||
       !binding->ap_base || (binding->ap_base&4095u) || binding->ap_base>UINTPTR_MAX-0x8e84000u)return AF_INVALID;
    uintptr_t base=binding->ap_base;
    for(unsigned i=0;i<sizeof(checks)/sizeof(checks[0]);++i)
        if(*(const uint32_t *)(base+checks[i].off)!=checks[i].word)return AF_STALE;
    if(*(const uint32_t *)(base+0x5845f28+0x20)!=0xd4 ||
       *(const uint32_t *)(base+0x5845f28+0x54)!=8 ||
       *(const uintptr_t *)(base+0x5845f28+0x58)!=base+0x3f52680)return AF_STALE;
    native.base=base;native.result=AF_EMPTY;return AF_OK;
}
int af_ap_browser_register(void) {
    uintptr_t rows,descriptors,parents,secondary,pairs[68][2],descriptor[2];
    uint32_t secondary_rows[68][2];
    uint32_t parent[2]={AF_BROWSER_MENU_ROOT,AF_BROWSER_MENU_DESCRIPTOR};
    if(!native.base)return AF_INVALID;if(native.registered)return AF_BUSY;
    rows=*(const uintptr_t *)va(0x5915b80);descriptors=*(const uintptr_t *)va(0x59611f8);parents=*(const uintptr_t *)va(0x593fbd8);
    secondary=*(const uintptr_t *)va(0x59430d0);
    if(!rows || !descriptors || !parents || !secondary)return AF_EMPTY;
    int (*contains)(void *,const uint32_t *)=(void *)va(0x1bd906c);
    for(uint32_t key=AF_BROWSER_MENU_ROOT;key<=AF_BROWSER_MENU_CANCEL;++key)
        if(contains((void *)rows,&key) || contains((void *)secondary,&key))return AF_EXISTS;
    if(contains((void *)descriptors,parent+1) || contains((void *)parents,parent))return AF_EXISTS;
    for(unsigned i=0;i<68;++i) {
        uint8_t *row=native.records[i];copy(row,(const void *)va(i?0x3f52680:0x3fe4a00),128);
        put32(row,AF_BROWSER_MENU_ROOT+i);put32(row+4,AF_BROWSER_MENU_ROOT+i);
        put32(row+8,AF_BROWSER_TEXT_FIRST);
        put32(row+0x10,UINT32_MAX);put32(row+0x34,0);
        put32(row+0x70,0x00550029);put32(row+0x74,0x00121086);put32(row+0x78,0x4f);put32(row+0x7c,0);
        pairs[i][0]=AF_BROWSER_MENU_ROOT+i;pairs[i][1]=(uintptr_t)row;
        secondary_rows[i][0]=secondary_rows[i][1]=AF_BROWSER_MENU_ROOT+i;
    }
    copy(native.descriptor,(const void *)va(0x5845f28),192);
    put32(native.descriptor,AF_BROWSER_TEXT_FIRST);put32(native.descriptor+0xc,UINT32_MAX);
    put32(native.descriptor+0x54,0);putptr(native.descriptor+0x58,(uintptr_t)native.page_rows);
    putptr(native.descriptor+0x70,(uintptr_t)admitted);
    putptr(native.descriptor+0x78,(uintptr_t)af_ap_browser_current);
    putptr(native.descriptor+0x80,(uintptr_t)af_ap_browser_focus);
    putptr(native.descriptor+0x88,(uintptr_t)af_ap_browser_action);
    putptr(native.descriptor+0x98,0);putptr(native.descriptor+0xa0,0);
    putptr(native.descriptor+0xa8,(uintptr_t)af_ap_browser_disabled);
    descriptor[0]=AF_BROWSER_MENU_DESCRIPTOR;descriptor[1]=(uintptr_t)native.descriptor;
    ((void (*)(void *,const void *,const void *))va(0x1c91e94))((void *)rows,pairs,pairs+68);
    ((void (*)(void *,const void *,const void *))va(0x1c91c40))((void *)descriptors,descriptor,descriptor+2);
    ((void (*)(void *,const void *,const void *))va(0x1c935e0))((void *)parents,parent,parent+2);
    /* 原全局菜单缓存先经二级别名解析；无同身份项会变成2b36而跳过新行。 */
    ((void (*)(void *,const void *,const void *))va(0x1c938a8))((void *)secondary,secondary_rows,secondary_rows+68);
    native.registered=1;return AF_OK;
}
int af_ap_browser_enable(uint32_t value) {
    if(!native.registered || value>1)return AF_INVALID;
    if(!value)(void)af_ap_browser_cancel();native.enabled=value;return AF_OK;
}
int af_ap_browser_publish(const AfMediaList *list) {
    if(!native.registered || !native.enabled || !list || !separate(list,sizeof(*list),&native,sizeof(native)) || !valid(list))return AF_INVALID;
    if(native.active || native.selected || native.intent)return AF_BUSY;
    if(list->generation<=native.list.generation)return AF_STALE;
    if(native.serial==255)return AF_EXHAUSTED;
    copy(&native.list,list,sizeof(*list));++native.serial;native.page=0;native.active=1;native.result=AF_EMPTY;
    for(unsigned i=1;i<68;++i) {
        uint32_t token=epoch(code(AF_BROWSER_MENU_ROOT+i));
        put32(native.records[i]+8,token);put32(native.records[i]+0x34,token);
    }
    page_build();return AF_OK;
}
static uint32_t model(uintptr_t getter) {
    const uint32_t *(*get)(void)=(void *)va(getter);return *get();
}
static uint32_t parent_of(uint32_t menu) {return ((uint32_t (*)(uint32_t))va(0x1bdb214))(menu);}
static uint32_t screen_of(uint32_t menu) {return ((uint32_t (*)(uint32_t))va(0x1bd6384))(menu);}
static uint32_t route(uint32_t menu) {
    static const uintptr_t values[2]={0x28a87e8,0x28a88ac},metadata[2]={0x28a87fc,0x28a88c0};
    static const uintptr_t setters[2]={0x21f3ed8,0x21f4130},notifiers[2]={0x21f0864,0x21f0830};
    /* 3bc来自原目标screen查询，不能写入逻辑父菜单ID。 */
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
int af_ap_browser_show(void) {
    if(!native.enabled || !native.active || !native.count)return AF_INVALID;
    uint32_t menu=model(0x28a87e8),parent=parent_of(menu),first;
    if(!((parent==0x15e7 && menu==0x15ea) ||
         (parent==AF_BROWSER_MENU_ROOT && af_ap_browser_is_id(menu))))return AF_STALE;
    copy(&first,native.page_rows[0],4);
    if(parent_of(first)!=AF_BROWSER_MENU_ROOT)return AF_STALE;
    uint32_t screen=route(first);
    if(model(0x28a87e8)!=first || model(0x28a88ac)!=screen)return AF_STALE;
    /* 新页首项已由原模型事务明确呈现，直接按确认也应有效，无需先转动转盘。 */
    copy(&native.focus,native.page_rows[0]+0x34,4);native.refresh=1;return AF_OK;
}
int af_ap_browser_back(void) {
    if(!native.enabled || native.active)return AF_INVALID;
    uint32_t menu=model(0x28a87e8);
    if(!af_ap_browser_is_id(menu) || parent_of(menu)!=AF_BROWSER_MENU_ROOT || parent_of(0x15ea)!=0x15e7)return AF_STALE;
    uint32_t screen=route(0x15ea);
    if(model(0x28a87e8)!=0x15ea || model(0x28a88ac)!=screen)return AF_STALE;
    native.refresh=1;return AF_OK;
}
uint32_t af_ap_browser_current(void) {
    if(!native.active || !native.count)return 0;
    if(native.focus)return native.focus;
    uint32_t value;copy(&value,native.page_rows[0]+0x34,4);return value;
}
void af_ap_browser_focus(uint32_t token) {
    if(!native.enabled || !native.active)return;
    /* 陈旧高亮清除已记录焦点；确认仍按当前原菜单及本代元数据校验。 */
    native.focus=0;
    if((token&0xffffff00u)!=(AF_BROWSER_TEXT_FIRST+(native.serial<<8)))return;
    for(unsigned i=0;i<native.count;++i) {
        uint32_t value;copy(&value,native.page_rows[i]+0x34,4);
        if(value==token){native.focus=token;return;}
    }
}
uint32_t af_ap_browser_disabled(void) {return !native.enabled || !native.active;}
int af_ap_browser_intent(uint32_t menu) {
    if(!menu){native.intent=0;return AF_OK;}
    if(native.intent)return AF_BUSY;
    if(!native.enabled || !native.active || menu==AF_BROWSER_MENU_ROOT || !af_ap_browser_is_id(menu))return AF_INVALID;
    if(model(0x28a87e8)!=menu)return AF_STALE;
    native.intent=menu;return AF_OK;
}
void af_ap_browser_action(uint32_t menu) {
    if(!menu || native.intent!=menu)return;
    native.intent=0;
    if(!native.enabled || !native.active)return;
    native.result=AF_STALE;
    const uint32_t *(*current)(void)=(void *)va(0x28a87e8);
    if(*current()!=menu || parent_of(menu)!=AF_BROWSER_MENU_ROOT)return;
    /* 获准ENTER已消费一次性许可；仍要求当前列表确含此行，不依赖+80。 */
    unsigned row=0;for(;row<native.count;++row) {
        uint32_t id;copy(&id,native.page_rows[row],4);if(id==menu)break;
    }
    if(row==native.count)return;
    if(menu==AF_BROWSER_MENU_CANCEL) {(void)af_ap_browser_cancel();return;}
    if(menu==AF_BROWSER_MENU_PREVIOUS && native.page) {--native.page;page_build();native.result=AF_EMPTY;return;}
    if(menu==AF_BROWSER_MENU_NEXT && (native.page+1)*AF_BROWSER_PAGE_FILES<native.list.count) {++native.page;page_build();native.result=AF_EMPTY;return;}
    if(menu<AF_BROWSER_MENU_FILE_FIRST || menu>=AF_BROWSER_MENU_FILE_FIRST+native.list.count)return;
    uint32_t index=menu-AF_BROWSER_MENU_FILE_FIRST;
    if(index/AF_BROWSER_PAGE_FILES!=native.page)return;
    native.selection.generation=native.list.generation;native.selection.index=index;native.selection.reserved=0;
    native.selected=1;native.active=0;native.result=AF_OK;native.refresh=1;
}
int af_ap_browser_cancel(void) {
    if(!native.registered)return AF_INVALID;
    native.intent=0;native.active=0;native.selected=0;native.focus=0;native.result=AF_BROWSER_CANCELLED;native.refresh=1;return AF_OK;
}
int af_ap_browser_take(uint64_t generation,AfApBrowserSelection *out) {
    if(!generation || !out || !separate(out,sizeof(*out),&native,sizeof(native)))return AF_INVALID;
    if(generation!=native.list.generation)return AF_STALE;
    if(!native.selected)return AF_EMPTY;
    *out=native.selection;native.selected=0;return AF_OK;
}
int af_ap_browser_result(void) {return native.result;}
uint32_t af_ap_browser_page(void) {return native.page;}
uint32_t af_ap_browser_rows(void) {return native.count;}
int af_ap_browser_refresh(void) {int value=(int)native.refresh;native.refresh=0;return value;}
