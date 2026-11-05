/* 原厂管理动作只进入一个有界请求；真实文件、转换和持久化由唯一拥有者执行。 */
#include "af_ap_manage.h"
#include "af_text.h"

static void copy_bytes(void *,const void *,size_t);
static void clear(void *p,size_t n) { uint8_t *b=p;while(n--)*b++=0; }
static int separate(const void *a,size_t an,const void *b,size_t bn) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return x<=UINTPTR_MAX-an && y<=UINTPTR_MAX-bn && (x+an<=y || y+bn<=x);
}
static int slot_valid(uint32_t slot) { return slot>0 && slot<=AF_USERS; }
static int preset_same(const AfPreset *a,const AfPreset *b) {
    if(a->base!=b->base || a->kind!=b->kind)return 0;
    for(unsigned i=0;i<AF_PARAMETERS;++i)if(a->params[i]!=b->params[i])return 0;
    for(unsigned i=0;i<32;++i)
        if(a->payload_sha256[i]!=b->payload_sha256[i] || a->lut_sha256[i]!=b->lut_sha256[i])return 0;
    return 1;
}
static int complete_slot(const AfSlot *s){
    const AfPreset *a=&s->initial,*b=&s->saved,*c=&s->working;
    if(af_validate(a)!=AF_OK||af_validate(b)!=AF_OK||af_validate(c)!=AF_OK||
       a->kind!=b->kind||a->kind!=c->kind)return 0;
    if(!a->kind)return 1;
    if(a->base!=b->base||a->base!=c->base)return 0;
    for(unsigned i=0;i<32;++i)if(a->payload_sha256[i]!=b->payload_sha256[i]||
       a->payload_sha256[i]!=c->payload_sha256[i]||a->lut_sha256[i]!=b->lut_sha256[i]||
       a->lut_sha256[i]!=c->lut_sha256[i])return 0;
    return 1;
}
static int active(const AfApManage *m) {
    return m->phase==AF_MANAGE_QUEUED || m->phase==AF_MANAGE_RUNNING ||
           m->phase==AF_MANAGE_COMMITTING || m->phase==AF_MANAGE_UNCERTAIN;
}
static void capture(AfApManageSlot *to,const AfSlot *from) {
    clear(to,sizeof(*to));to->revision=from->saved_revision;to->present=from->present;
    if(from->present) {to->initial=from->initial;to->saved=from->saved;to->working=from->working;}
}
static int unchanged(const AfApManageSlot *before,const AfSlot *now) {
    if(now->pending.request || before->present!=now->present || before->revision!=now->saved_revision)return 0;
    return !now->present || (preset_same(&before->initial,&now->initial) &&
           preset_same(&before->saved,&now->saved) && preset_same(&before->working,&now->working));
}
void af_ap_manage_init(AfApManage *m) {
    if(m) {clear(m,sizeof(*m));m->next_ticket=1;}
}
int af_ap_manage_submit(AfApManage *m,const AfCatalog *catalog,const AfApManageRequest *request) {
    AfApManageJob next;const AfSlot *source=0,*target;
    if(!m || !catalog || !request || !m->next_ticket ||
       !separate(m,sizeof(*m),catalog,sizeof(*catalog)) ||
       !separate(m,sizeof(*m),request,sizeof(*request)) ||
       !separate(catalog,sizeof(*catalog),request,sizeof(*request)))return AF_INVALID;
    if(active(m))return AF_BUSY;
    if(m->next_ticket==UINT64_MAX)return AF_EXHAUSTED;
    if(request->overwrite>1 || !slot_valid(request->target_slot) ||
       request->op<AF_MANAGE_SAVE || request->op>AF_MANAGE_EXPORT)return AF_INVALID;
    /* 旧六原生数据不迁移；即使尚无overlay，创建/复制/导入也必须显式确认替换。 */
    if(request->target_slot<=6 && !request->overwrite &&
       (request->op==AF_MANAGE_COPY || request->op==AF_MANAGE_CREATE || request->op==AF_MANAGE_IMPORT))return AF_INVALID;
    if(request->op==AF_MANAGE_CLEAR) {
        if(request->source_slot || request->overwrite!=1 ||
           request->name_bytes || request->media_generation || request->media_index)return AF_INVALID;
        target=&catalog->slots[request->target_slot-1];
        if(!target->present)return AF_EMPTY;
        if(!complete_slot(target))return AF_INVALID;
    } else if(request->op==AF_MANAGE_IMPORT || request->op==AF_MANAGE_CREATE) {
        if(request->source_slot || request->initial.kind || af_validate(&request->initial)!=AF_OK)return AF_INVALID;
        if(request->op==AF_MANAGE_IMPORT ? (!request->media_generation || request->media_index>=AF_AP_MANAGE_MEDIA_MAX):
                                          (request->media_generation || request->media_index))return AF_INVALID;
    } else {
        if(!slot_valid(request->source_slot) || request->media_generation || request->media_index ||
           ((request->op==AF_MANAGE_SAVE || request->op==AF_MANAGE_RENAME || request->op==AF_MANAGE_EXPORT) ?
                                          request->source_slot!=request->target_slot :
                                          request->source_slot==request->target_slot))return AF_INVALID;
        if((request->op==AF_MANAGE_RENAME || request->op==AF_MANAGE_EXPORT) && request->overwrite)return AF_INVALID;
        if(request->op==AF_MANAGE_EXPORT) {AfPreset empty={0};if(!preset_same(&request->initial,&empty))return AF_INVALID;}
        source=&catalog->slots[request->source_slot-1];
        if(!source->present)return AF_EMPTY;
        if(source->pending.request)return AF_BUSY;
        if(!complete_slot(source))return AF_INVALID;
    }
    if(request->op==AF_MANAGE_SAVE || request->op==AF_MANAGE_CLEAR || request->op==AF_MANAGE_EXPORT) {if(request->name_bytes)return AF_INVALID;}
    else if(!af_text_name_valid(request->name,request->name_bytes))return AF_INVALID;
    target=&catalog->slots[request->target_slot-1];
    if(target->pending.request)return AF_BUSY;
    if(request->op!=AF_MANAGE_SAVE && request->op!=AF_MANAGE_RENAME && request->op!=AF_MANAGE_EXPORT && target->present && !request->overwrite)return AF_EXISTS;
    if(request->op!=AF_MANAGE_EXPORT && target->saved_revision==UINT64_MAX)return AF_EXHAUSTED;
    clear(&next,sizeof(next));next.ticket=m->next_ticket;
    next.request.op=request->op;next.request.source_slot=request->source_slot;
    next.request.target_slot=request->target_slot;next.request.overwrite=request->overwrite;
    if(request->op!=AF_MANAGE_SAVE) {
        next.request.name_bytes=request->name_bytes;
        for(unsigned i=0;i<request->name_bytes;++i)next.request.name[i]=request->name[i];
    }
    if(request->op==AF_MANAGE_IMPORT || request->op==AF_MANAGE_CREATE) {
        next.request.media_generation=request->media_generation;next.request.media_index=request->media_index;
        next.request.initial=request->initial;
    }
    if(source)capture(&next.source,source);
    capture(&next.target,target);
    copy_bytes(&m->job,&next,sizeof(next));++m->next_ticket;clear(&m->receipt,sizeof(m->receipt));
    m->cancel_requested=0;m->progress_done=0;m->progress_total=0;m->phase=AF_MANAGE_QUEUED;
    return AF_OK;
}
int af_ap_manage_take(AfApManage *m,AfApManageJob *job) {
    if(!m || !job || !separate(m,sizeof(*m),job,sizeof(*job)))return AF_INVALID;
    if(m->phase!=AF_MANAGE_QUEUED)return AF_EMPTY;
    copy_bytes(job,&m->job,sizeof(*job));m->phase=AF_MANAGE_RUNNING;return AF_OK;
}
int af_ap_manage_cancel(AfApManage *m,uint64_t ticket) {
    if(!m || !ticket)return AF_INVALID;
    if(ticket!=m->job.ticket)return AF_STALE;
    if(m->phase==AF_MANAGE_CANCELLED || m->cancel_requested)return AF_OK;
    if(m->phase==AF_MANAGE_COMMITTING)return AF_BUSY;
    if(m->phase!=AF_MANAGE_QUEUED && m->phase!=AF_MANAGE_RUNNING)return AF_STALE;
    m->cancel_requested=1;
    if(m->phase==AF_MANAGE_QUEUED) {
        clear(&m->receipt,sizeof(m->receipt));m->receipt.ticket=ticket;
        m->receipt.result=AF_MANAGE_CANCEL;m->phase=AF_MANAGE_CANCELLED;
    }
    return AF_OK;
}
int af_ap_manage_cancelled(const AfApManage *m,uint64_t ticket) {
    return m && ticket && ticket==m->job.ticket && m->cancel_requested ? 1:0;
}
int af_ap_manage_progress(AfApManage *m,uint64_t ticket,uint32_t done,uint32_t total) {
    if(!m || !ticket || !total || done>total)return AF_INVALID;
    if(ticket!=m->job.ticket || m->phase!=AF_MANAGE_RUNNING)return AF_STALE;
    if(m->cancel_requested)return AF_MANAGE_CANCEL;
    if(done<m->progress_done || (m->progress_total && total!=m->progress_total))return AF_INVALID;
    m->progress_done=done;m->progress_total=total;return AF_OK;
}
int af_ap_manage_commit_begin(AfApManage *m,const AfCatalog *catalog,uint64_t ticket) {
    if(!m || !catalog || !ticket || !separate(m,sizeof(*m),catalog,sizeof(*catalog)))return AF_INVALID;
    if(ticket!=m->job.ticket || m->phase!=AF_MANAGE_RUNNING)return AF_STALE;
    if(m->cancel_requested)return AF_MANAGE_CANCEL;
    if(!unchanged(&m->job.target,&catalog->slots[m->job.request.target_slot-1]) ||
       (m->job.request.source_slot &&
        !unchanged(&m->job.source,&catalog->slots[m->job.request.source_slot-1])))return AF_STALE;
    m->phase=AF_MANAGE_COMMITTING;return AF_OK;
}
int af_ap_manage_finish(AfApManage *m,const AfCatalog *catalog,const AfApManageReceipt *receipt) {
    const AfSlot *target;
    if(!m || !catalog || !receipt || !separate(m,sizeof(*m),catalog,sizeof(*catalog)) ||
       !separate(m,sizeof(*m),receipt,sizeof(*receipt)) ||
       !separate(catalog,sizeof(*catalog),receipt,sizeof(*receipt)) ||
       !receipt->ticket || receipt->durable>1 || receipt->uncertain>1)return AF_INVALID;
    if(receipt->ticket!=m->job.ticket ||
       (m->phase!=AF_MANAGE_RUNNING && m->phase!=AF_MANAGE_COMMITTING))return AF_STALE;
    if(receipt->result==AF_OK) {
        if(m->phase!=AF_MANAGE_COMMITTING || !receipt->durable || receipt->uncertain ||
           (m->job.request.op==AF_MANAGE_EXPORT ? receipt->generation!=m->job.target.revision :
                                                receipt->generation<=m->job.target.revision))return AF_INVALID;
        target=&catalog->slots[m->job.request.target_slot-1];
        if(target->pending.request || target->saved_revision!=receipt->generation)return AF_STALE;
        if(m->job.request.op==AF_MANAGE_EXPORT) {
            if(!unchanged(&m->job.target,target))return AF_STALE;
        } else if(m->job.request.op==AF_MANAGE_CLEAR) {
            AfPreset empty={0};
            if(target->present || !preset_same(&target->initial,&empty) ||
               !preset_same(&target->saved,&empty) || !preset_same(&target->working,&empty))return AF_STALE;
        } else {
        if(!target->present || af_validate(&target->saved)!=AF_OK)return AF_STALE;
        if(m->job.request.op==AF_MANAGE_RENAME) {
            /* 改名不能把dirty工作值存入saved，也不能改变任何成像参数。 */
            if(!preset_same(&target->initial,&m->job.target.initial) ||
               !preset_same(&target->saved,&m->job.target.saved) ||
               !preset_same(&target->working,&m->job.target.working))return AF_STALE;
        } else if(m->job.request.op==AF_MANAGE_IMPORT) {
            /* 双入口允许已完整验证的纯参数回导或联合配方；输入文件由后端核验。 */
            if(target->saved.kind>1)return AF_STALE;
        } else if(m->job.request.op==AF_MANAGE_CREATE) {
            if(!preset_same(&target->saved,&m->job.request.initial) ||
               !preset_same(&target->initial,&m->job.request.initial))return AF_STALE;
        } else if(!preset_same(&target->saved,&m->job.source.working))return AF_STALE;
        }
        m->phase=AF_MANAGE_DONE;
    } else {
        if(receipt->durable || receipt->generation ||
           (receipt->uncertain && m->phase!=AF_MANAGE_COMMITTING))return AF_INVALID;
        if(receipt->result==AF_MANAGE_CANCEL &&
           (m->phase!=AF_MANAGE_RUNNING || !m->cancel_requested || receipt->uncertain))return AF_INVALID;
        m->phase=receipt->uncertain?AF_MANAGE_UNCERTAIN:
                 receipt->result==AF_MANAGE_CANCEL?AF_MANAGE_CANCELLED:AF_MANAGE_FAILED;
    }
    m->receipt=*receipt;return AF_OK;
}
int af_ap_manage_recovered(AfApManage *m) {
    if(!m || m->phase!=AF_MANAGE_UNCERTAIN)return AF_INVALID;
    /* 调用方已完成真实存储恢复；不抹掉失败回执及ticket，保留供原界面显示。 */
    m->phase=AF_MANAGE_FAILED;return AF_OK;
}

/* 原菜单模块：只追加原注册树中的独立记录，绘制与输入仍由原DS控件负责。 */
static struct {
    uintptr_t base;
    AfApManage *manager;
    AfCatalog *catalog;
    uint32_t registered,enabled,context,focus;
    uint32_t refresh,result_op,intent;
    int result;
    AfApManageService service;
    AfApManagePicker picker;
    uint32_t configured[7];
    AfApManageRequest request[7];
    uint8_t main_catalog[0x17088],rows[8][128],descriptor[192];
} native;
static uintptr_t va(uintptr_t offset) { return native.base+offset; }
static void copy_bytes(void *to,const void *from,size_t n) {
    uint8_t *a=to;const uint8_t *b=from;while(n--)*a++=*b++;
}
static void put32(void *where,uint32_t value) { copy_bytes(where,&value,4); }
static void putptr(void *where,uintptr_t value) { copy_bytes(where,&value,sizeof(value)); }
static uint32_t always_enabled(void) { return 1; }

uint32_t af_ap_manage_menu_for_op(uint32_t op) {
    if(op>=AF_MANAGE_SAVE && op<=AF_MANAGE_CREATE)return AF_MANAGE_MENU_ROOT+op;
    return op==AF_MANAGE_CLEAR?AF_MANAGE_MENU_CLEAR:op==AF_MANAGE_RENAME?AF_MANAGE_MENU_RENAME:op==AF_MANAGE_EXPORT?AF_MANAGE_MENU_EXPORT:UINT32_MAX;
}
static uint32_t menu_op(uint32_t menu) {
    if(menu>=AF_MANAGE_MENU_SAVE && menu<=AF_MANAGE_MENU_CREATE)return menu-AF_MANAGE_MENU_ROOT;
    return menu==AF_MANAGE_MENU_CLEAR?AF_MANAGE_CLEAR:menu==AF_MANAGE_MENU_RENAME?AF_MANAGE_RENAME:menu==AF_MANAGE_MENU_EXPORT?AF_MANAGE_EXPORT:0;
}
int af_ap_manage_menu_is_id(uint32_t menu) {
    return menu==AF_MANAGE_MENU_ROOT || menu_op(menu)!=0;
}
uint32_t af_ap_manage_menu_parent(uint32_t menu) {
    return menu==AF_MANAGE_MENU_ROOT?0x7f:
           menu_op(menu)?AF_MANAGE_MENU_ROOT:UINT32_MAX;
}
uint32_t af_ap_manage_menu_name(uint32_t menu) {
    return menu==AF_MANAGE_MENU_ROOT?AF_MANAGE_TEXT_FIRST:menu_op(menu)?AF_MANAGE_TEXT_FIRST+menu_op(menu):UINT32_MAX;
}
static int chinese(void) {
    if(!native.base)return 0;
    const uint32_t *(*get)(void)=(void *)va(0x28b0464);
    return *get()==25;
}
const char *af_ap_manage_menu_text(uint32_t token) {
    static const char *const names[2][8]={{"Custom Filters","Save","Save As","Import Filter","Create Filter","Clear Slot","Rename Filter","Export Saved Filter"},
        {"自定义滤镜","保存","另存为","从SD卡导入滤镜","新建参数滤镜","清空槽位","重命名滤镜","导出已保存滤镜"}};
    static const char *const unavailable[2][7]={{"Save (Unavailable)","Save As (Unavailable)","Import Filter (Unavailable)","Create Filter (Unavailable)","Clear (Unavailable)","Rename (Unavailable)","Export (Unavailable)"},
        {"保存（不可用）","另存为（不可用）","导入滤镜（不可用）","新建滤镜（不可用）","清空（不可用）","重命名（不可用）","导出（不可用）"}};
    static const char *const done[2][7]={{"Saved","Saved As","Imported","Created","Cleared","Renamed","Exported"},
        {"已保存","已另存为","已导入","已创建","已清空","已重命名","已导出"}};
    static const char *const failed[2][7]={{"Save failed","Save As failed","Import failed","Create failed","Clear failed","Rename failed","Export failed"},
        {"保存失败","另存为失败","导入失败","创建失败","清空失败","重命名失败","导出失败"}};
    static char title[64],progress_text[64];
    if(token<AF_MANAGE_TEXT_FIRST || token>=AF_MANAGE_TEXT_FIRST+8)return 0;
    uint32_t item=token-AF_MANAGE_TEXT_FIRST,lang=(uint32_t)chinese();
    if(item==AF_MANAGE_IMPORT && native.manager && native.manager->job.request.op==AF_MANAGE_IMPORT &&
       (native.manager->phase==AF_MANAGE_QUEUED || native.manager->phase==AF_MANAGE_RUNNING)){
        if(native.manager->cancel_requested)return lang?"正在取消导入…":"Cancelling import...";
        uint32_t percent=native.manager->progress_total?
            (uint32_t)((uint64_t)native.manager->progress_done*100/native.manager->progress_total):0;
        if(percent>100)percent=100;
        const char *prefix=lang?"导入 ":"Import ",*suffix=lang?"%（确定可取消）":"% (Enter to cancel)";
        size_t n=0;while(*prefix)progress_text[n++]=*prefix++;
        if(percent>=100)progress_text[n++]='1';
        if(percent>=10)progress_text[n++]=(char)('0'+percent/10%10);
        progress_text[n++]=(char)('0'+percent%10);
        while(*suffix)progress_text[n++]=*suffix++;progress_text[n]=0;return progress_text;
    }
    if(!item) {
        size_t n=0;const char *prefix=names[lang][0];
        while(prefix[n]){title[n]=prefix[n];++n;}
        if(native.context) {
            title[n++]=' ';title[n++]='C';title[n++]=(char)('0'+native.context/10);title[n++]=(char)('0'+native.context%10);
            if(af_dirty(native.catalog,native.context)==1){title[n++]=' ';title[n++]='*';}
        }
        title[n]=0;return title;
    }
    int source=native.context && native.catalog->slots[native.context-1].present;
    if((item<=2 && !source) ||
       (!(native.service.capabilities&AF_MANAGE_CAP(item)) &&
        !(item==AF_MANAGE_IMPORT && (native.picker.capabilities&AF_MANAGE_CAP(item)))))return unavailable[lang][item-1];
    if(item==AF_MANAGE_IMPORT && native.result_op==item && native.result!=AF_OK) {
        if(native.result==AF_MANAGE_NOT_READY)return lang?"LUT转换尚未就绪":"LUT conversion unavailable";
        if(native.result==AF_MANAGE_CANCEL)return lang?"已取消":"Cancelled";
        return lang?"滤镜文件读取失败":"Filter file read failed";
    }
    if(native.result_op==item && native.result<0 && item!=AF_MANAGE_IMPORT)
        return native.result==AF_MANAGE_CANCEL?(lang?"已取消":"Cancelled"):failed[lang][item-1];
    if(item==AF_MANAGE_SAVE && af_dirty(native.catalog,native.context)==1)return lang?"保存更改":"Save changes";
    if(native.manager && native.manager->job.request.op==item && native.manager->job.ticket) {
        switch(native.manager->phase) {
        case AF_MANAGE_QUEUED:case AF_MANAGE_RUNNING:case AF_MANAGE_COMMITTING:return lang?"处理中…":"Working...";
        case AF_MANAGE_DONE:return done[lang][item-1];
        case AF_MANAGE_FAILED:return failed[lang][item-1];
        case AF_MANAGE_CANCELLED:return lang?"已取消":"Cancelled";
        case AF_MANAGE_UNCERTAIN:return item==AF_MANAGE_EXPORT?(lang?"导出状态不确定":"Export status unknown"):(lang?"保存状态不确定":"Save status unknown");
        default:break;
        }
    }
    return names[lang][item];
}
int af_ap_manage_picker_bind(const AfApManagePicker *picker) {
    if(!native.base || !picker || picker->version!=AF_AP_MANAGE_VERSION || picker->bytes!=sizeof(*picker) ||
       !picker->context || !picker->open || picker->reserved || !picker->capabilities ||
       (picker->capabilities&~126u) || !separate(picker,sizeof(*picker),&native,sizeof(native)))return AF_INVALID;
    if(native.picker.open || active(native.manager))return AF_BUSY;
    native.picker=*picker;native.refresh=1;return AF_OK;
}
int af_ap_manage_menu_notice(uint32_t op,int result) {
    if(!native.base || op<AF_MANAGE_SAVE || op>AF_MANAGE_EXPORT || result==AF_OK)return AF_INVALID;
    native.result_op=op;native.result=result;native.refresh=1;return AF_OK;
}

int af_ap_manage_service_bind(const AfApManageService *service) {
    if(!native.base || !service || service->version!=AF_AP_MANAGE_VERSION ||
       service->bytes!=sizeof(*service) || !service->context || !service->pump ||
       service->reserved || !service->capabilities || (service->capabilities&~127u) ||
       !separate(service,sizeof(*service),&native,sizeof(native)))return AF_INVALID;
    if(native.service.pump || active(native.manager))return AF_BUSY;
    native.service=*service;native.refresh=1;return AF_OK;
}
int af_ap_manage_service_poll(void) {
    if(!native.service.pump || !native.enabled ||
       (native.manager->phase!=AF_MANAGE_QUEUED &&
        !(native.manager->phase==AF_MANAGE_RUNNING && native.manager->job.request.op==AF_MANAGE_IMPORT)))return AF_EMPTY;
    int result=native.service.pump(native.service.context,native.manager);
    native.refresh=1;return result;
}
int af_ap_manage_menu_bind(const AfApManageMenuBinding *binding) {
    static const struct {uintptr_t offset;uint32_t word;} checks[]={
        {0x1c91c40,0xa9bc7bfd},{0x1c91e94,0xa9bc7bfd},{0x1c935e0,0xa9bc7bfd},
        {0x1c938a8,0xa9bc7bfd},{0x1c933ec,0xa9bc7bfd},
        {0x1bd906c,0x91002002},{0x1bd924c,0xa9bc7bfd},{0x1bd9348,0xa9bc7bfd},
        {0x28a87e8,0xf002b2a0},{0x28b0464,0xf002b260}
    };
    uintptr_t base;
    if(native.base)return AF_BUSY;
    if(!binding || binding->version!=AF_AP_MANAGE_VERSION || binding->bytes!=sizeof(*binding) ||
       !binding->manager || !binding->catalog || !binding->manager->next_ticket ||
       !separate(binding->manager,sizeof(*binding->manager),binding->catalog,sizeof(*binding->catalog)))return AF_INVALID;
    base=binding->ap_base;
    if(!base || (base&4095u) || base>UINTPTR_MAX-0x8e84000u)return AF_INVALID;
    /* 调用者先核验完整AP摘要、映射与页权限。全部原像匹配之前不发布绑定。 */
    for(unsigned i=0;i<sizeof(checks)/sizeof(checks[0]);++i)
        if(*(const uint32_t *)(base+checks[i].offset)!=checks[i].word)return AF_STALE;
    if(*(const uintptr_t *)(base+0x594a7b0)!=base+0x5049d80 ||
       *(const uint32_t *)(base+0x5049d80)!=8 ||
       *(const uint32_t *)(base+0x5053628)!=0x15 ||
       *(const uint32_t *)(base+0x5053628+8)!=7 ||
       *(const uint32_t *)(base+0x5053628+0x28)!=0x1f2 ||
       *(const uintptr_t *)(base+0x5053628+0x30)!=base+0x5858b08 ||
       *(const uint32_t *)(base+0x5845f28+0x20)!=0xd4 ||
       *(const uint32_t *)(base+0x5845f28+0x54)!=8 ||
       *(const uintptr_t *)(base+0x5845f28+0x58)!=base+0x3f52680)return AF_STALE;
    native.base=base;native.manager=binding->manager;native.catalog=binding->catalog;
    native.result=AF_MANAGE_NOT_READY;return AF_OK;
}
int af_ap_manage_menu_register(void) {
    uintptr_t rows,descriptors,parents,secondary,reverse,registration[8][2],descriptor[2];
    uint32_t secondary_rows[8][2];
    uint32_t parent[2]={AF_MANAGE_MENU_ROOT,AF_MANAGE_MENU_DESCRIPTOR};
    uint32_t inverse[2]={AF_MANAGE_MENU_DESCRIPTOR,AF_MANAGE_MENU_ROOT};
    int (*contains)(void *,const uint32_t *);
    void (*add_rows)(void *,const void *,const void *);
    void (*add_descriptors)(void *,const void *,const void *);
    void (*add_parents)(void *,const void *,const void *);
    void (*add_secondary)(void *,const void *,const void *);
    void (*add_reverse)(void *,const void *,const void *);
    if(!native.base)return AF_MANAGE_NOT_READY;
    if(native.registered)return AF_BUSY;
    rows=*(const uintptr_t *)va(0x5915b80);
    descriptors=*(const uintptr_t *)va(0x59611f8);
    parents=*(const uintptr_t *)va(0x593fbd8);
    secondary=*(const uintptr_t *)va(0x59430d0);
    reverse=*(const uintptr_t *)va(0x5959e80);
    if(!rows || !descriptors || !parents || !secondary || !reverse)return AF_MANAGE_NOT_READY;
    contains=(int (*)(void *,const uint32_t *))va(0x1bd906c);
    for(unsigned index=0;index<8;++index) {
        uint32_t menu=index?af_ap_manage_menu_for_op(index):AF_MANAGE_MENU_ROOT;
        if(contains((void *)rows,&menu) || contains((void *)secondary,&menu))return AF_EXISTS;
    }
    if(contains((void *)descriptors,&parent[1]) || contains((void *)parents,&parent[0]) ||
       contains((void *)reverse,&inverse[0]))return AF_EXISTS;
    if(*(const uintptr_t *)va(0x594a7b0)!=va(0x5049d80) ||
       *(const uint32_t *)va(0x5053628+8)!=7)return AF_STALE;
    copy_bytes(native.main_catalog,(const void *)va(0x5049d80),sizeof(native.main_catalog));
    copy_bytes(native.rows[0],(const void *)va(0x3fe4a00),128);
    for(unsigned i=0;i<8;++i) {
        uint8_t *row=native.rows[i];
        if(i)copy_bytes(row,(const void *)va(0x3f52680),128);
        uint32_t menu=i?af_ap_manage_menu_for_op(i):AF_MANAGE_MENU_ROOT;
        put32(row,menu);put32(row+4,menu);
        put32(row+8,AF_MANAGE_TEXT_FIRST+i);put32(row+0x10,UINT32_MAX);
        put32(row+0x34,i?i-1:7);
        /* 与已验证新增创意外观相同的五类空哨兵；不复用原动作或Backup项。 */
        put32(row+0x70,0x00550029);put32(row+0x74,0x00121086);
        put32(row+0x78,0x4f);put32(row+0x7c,0);
        registration[i][0]=menu;registration[i][1]=(uintptr_t)row;
        secondary_rows[i][0]=secondary_rows[i][1]=menu;
    }
    /* 原主菜单另有分类目录，不能把同名逻辑页的128字节选项表当主菜单。
     * 仅追加 Exposure/Color 的 Color/Tone 分类（原15组）的第八个描述符。
     * 其余8分类、原7项和备用描述符全部逐字节保留。 */
    put32(native.rows[0]+0x30,0);
    for(unsigned i=0;i<20;++i) {
        uint16_t value=i==16?1:0;copy_bytes(native.rows[0]+0x44+2*i,&value,2);
    }
    uint8_t *group=native.main_catalog+(0x5053628-0x5049d80);
    put32(group+8,8);put32(group+0x10+7*24,AF_MANAGE_MENU_DESCRIPTOR);
    putptr(group+0x18+7*24,(uintptr_t)native.descriptor);putptr(group+0x20+7*24,0);
    copy_bytes(native.descriptor,(const void *)va(0x5845f28),192);
    put32(native.descriptor,AF_MANAGE_TEXT_FIRST);put32(native.descriptor+0xc,UINT32_MAX);
    put32(native.descriptor+0x54,7);putptr(native.descriptor+0x58,(uintptr_t)native.rows[1]);
    /* 原AP在后续初始化中补全各描述符的产品资格；提前复制的私有对象不会被该表更新。
     * 此候选只开放同源实测A7R5产品列16，其余型号维持关闭，不改原模板。 */
    for(unsigned i=0;i<20;++i) {
        uint16_t value=i==16?1:0;copy_bytes(native.descriptor+0x2c+2*i,&value,2);
    }
    /* 原0x691仅作为原控件的只读刷新订阅；所有能写属性的回调均替换。
     * +80仅记录高亮；+88也会自动应用，必须由真实ENTER关闭点的一次性intent授权。 */
    putptr(native.descriptor+0x70,(uintptr_t)always_enabled);
    putptr(native.descriptor+0x78,(uintptr_t)af_ap_manage_menu_current);
    putptr(native.descriptor+0x80,(uintptr_t)af_ap_manage_menu_focus);
    putptr(native.descriptor+0x88,(uintptr_t)af_ap_manage_menu_action);
    putptr(native.descriptor+0x98,0);putptr(native.descriptor+0xa0,0);
    putptr(native.descriptor+0xa8,(uintptr_t)af_ap_manage_menu_disabled);
    descriptor[0]=AF_MANAGE_MENU_DESCRIPTOR;descriptor[1]=(uintptr_t)native.descriptor;
    add_rows=(void (*)(void *,const void *,const void *))va(0x1c91e94);
    add_descriptors=(void (*)(void *,const void *,const void *))va(0x1c91c40);
    add_parents=(void (*)(void *,const void *,const void *))va(0x1c935e0);
    add_secondary=(void (*)(void *,const void *,const void *))va(0x1c938a8);
    add_reverse=(void (*)(void *,const void *,const void *))va(0x1c933ec);
    add_rows((void *)rows,registration,registration+8);
    add_descriptors((void *)descriptors,descriptor,descriptor+2);
    add_parents((void *)parents,parent,parent+2);
    add_reverse((void *)reverse,inverse,inverse+2);
    /* 原主菜单的全局可见缓存按二级身份索引；未知身份会变成2b36并跳过。
     * 仅追加已核验小于缓存上界2b34的8个自映射，原5591和C07..C20不变。
     * 后续原全局初始化自然建缓存，不直接写缓存位或重放清空构造。 */
    add_secondary((void *)secondary,secondary_rows,secondary_rows+8);
    native.registered=1;return AF_OK;
}
int af_ap_manage_menu_enable(uint32_t value) {
    uintptr_t expected;
    if(value>1 || !native.registered)return AF_INVALID;
    if(active(native.manager))return AF_BUSY;
    expected=native.enabled?(uintptr_t)native.main_catalog:va(0x5049d80);
    if(*(const uintptr_t *)va(0x594a7b0)!=expected)return AF_STALE;
    *(uintptr_t *)va(0x594a7b0)=value?(uintptr_t)native.main_catalog:va(0x5049d80);
    native.intent=0;native.enabled=value;return AF_OK;
}
int af_ap_manage_menu_context(uint32_t slot) {
    if(!native.base || !slot_valid(slot))return AF_INVALID;
    if(active(native.manager))return AF_BUSY;
    if(native.context!=slot) {
        native.intent=0;native.context=slot;native.focus=0;native.refresh=1;
        clear(native.configured,sizeof(native.configured));clear(native.request,sizeof(native.request));
    }
    return AF_OK;
}
int af_ap_manage_menu_configure(const AfApManageRequest *request) {
    AfApManage probe;int result;
    if(!native.base || !request || !native.context || request->op==AF_MANAGE_SAVE ||
       request->op<AF_MANAGE_COPY || request->op>AF_MANAGE_CREATE ||
       (request->op==AF_MANAGE_COPY?request->source_slot!=native.context:
                                   request->target_slot!=native.context))return AF_INVALID;
    if(active(native.manager))return AF_BUSY;
    af_ap_manage_init(&probe);result=af_ap_manage_submit(&probe,native.catalog,request);
    if(result!=AF_OK)return result;
    native.request[request->op-1]=probe.job.request;native.configured[request->op-1]=1;return AF_OK;
}
void af_ap_manage_menu_focus(uint32_t index) { if(native.enabled && index<7)native.focus=index; }
uint32_t af_ap_manage_menu_current(void) { return native.focus; }
uint32_t af_ap_manage_menu_disabled(void) {
    if(!native.enabled)return 1;
    if(!active(native.manager))return 0;
    return !(native.focus==AF_MANAGE_IMPORT-1 && native.manager->job.request.op==AF_MANAGE_IMPORT &&
        (native.manager->phase==AF_MANAGE_QUEUED || native.manager->phase==AF_MANAGE_RUNNING) &&
        !native.manager->cancel_requested);
}
int af_ap_manage_menu_intent(uint32_t menu) {
    if(!menu){native.intent=0;return AF_OK;}
    if(native.intent)return AF_BUSY;
    if(!native.enabled || !menu_op(menu))return AF_INVALID;
    const uint32_t *(*current)(void)=(void *)va(0x28a87e8);
    if(*current()!=menu)return AF_STALE;
    native.intent=menu;return AF_OK;
}
void af_ap_manage_menu_action(uint32_t menu) {
    AfApManageRequest request;const uint32_t *(*current)(void);uint32_t op,shown;
    /* 方向键也会走+88。未授权时连结果／焦点都不改变，不能自动提交。 */
    if(!menu || native.intent!=menu)return;
    native.intent=0;
    native.result=AF_MANAGE_NOT_READY;
    if(!native.enabled || !menu_op(menu))return;
    op=menu_op(menu);
    current=(const uint32_t *(*)(void))va(0x28a87e8);shown=*current();
    if(shown!=menu) {native.result=AF_STALE;return;}
    /* 输入意图由真实ENTER关闭点另行授权；当前身份仍须匹配这次许可。 */
    native.focus=op-1;
    native.result_op=op;
    if(active(native.manager)){
        if(op==AF_MANAGE_IMPORT && native.manager->job.request.op==AF_MANAGE_IMPORT &&
           (native.manager->phase==AF_MANAGE_QUEUED || native.manager->phase==AF_MANAGE_RUNNING))
            native.result=af_ap_manage_cancel(native.manager,native.manager->job.ticket);
        else native.result=AF_BUSY;
        native.refresh=1;return;
    }
    if(op<=AF_MANAGE_COPY && (!native.context || !native.catalog->slots[native.context-1].present)) {
        native.result=AF_EMPTY;native.refresh=1;return;
    }
    if(op!=AF_MANAGE_IMPORT && !(native.service.capabilities&AF_MANAGE_CAP(op)))return;
    if(native.picker.open && (native.picker.capabilities&AF_MANAGE_CAP(op))) {
        native.result=native.picker.open(native.picker.context,op,op==AF_MANAGE_COPY?native.context:0);
        native.refresh=1;return;
    }
    /* 清空必须经目标选择器的二次确认，不能使用configure或当前context直提。 */
    if(op==AF_MANAGE_CLEAR || op==AF_MANAGE_RENAME || op==AF_MANAGE_EXPORT || !native.context || !(native.service.capabilities&AF_MANAGE_CAP(op)))return;

    clear(&request,sizeof(request));request.op=op;
    if(op==AF_MANAGE_SAVE)request.source_slot=request.target_slot=native.context;
    else {
        if(!native.configured[op-1]) {
            if(op!=AF_MANAGE_CREATE)return;
            /* 明确的ST新建默认，仅由用户确认Create Filter触发；不自动填槽。 */
            request.target_slot=native.context;request.initial.params[6]=3;request.name_bytes=3;
            request.name[0]='C';request.name[1]=(char)('0'+native.context/10);
            request.name[2]=(char)('0'+native.context%10);
        } else request=native.request[op-1];
    }
    native.result=af_ap_manage_submit(native.manager,native.catalog,&request);
    native.refresh=1;
    /* 文件和目标选择属于这次确认；任务失败后必须重新明确选择，不能复用陈旧浏览。 */
    if(native.result==AF_OK && op!=AF_MANAGE_SAVE)native.configured[op-1]=0;
}
int af_ap_manage_menu_result(void) { return native.result; }
int af_ap_manage_menu_refresh(void) {
    if(!native.base || !native.enabled || !native.refresh)return 0;
    const uint32_t *(*current)(void)=(const uint32_t *(*)(void))va(0x28a87e8);
    if(!af_ap_manage_menu_is_id(*current()))return 0;
    native.refresh=0;return 1;
}
