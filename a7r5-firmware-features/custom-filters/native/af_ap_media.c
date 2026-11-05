#include "af_ap_media.h"
static struct {
    AfApMediaBinding binding;
    AfApMediaImporter importer;
    AfMediaProvider provider;
    AfApMediaCardService cards;
    uint32_t card_busy,card_selected;
    int (*prepare_provider)(void *,const AfMediaProvider *,const AfMediaList *,const AfApMediaInfo *);
    AfMediaList work,list;
    AfApMediaInfo info;
    uint64_t generation,device,inode;
    uint32_t bound,identity,phase,page,refresh;
    int result;
} media;
static int separate(const void *a,size_t n,const void *b,size_t m) {
    uintptr_t x=(uintptr_t)a,y=(uintptr_t)b;
    return a&&b&&x<=UINTPTR_MAX-n&&y<=UINTPTR_MAX-m&&(x+n<=y||y+m<=x);
}
static int fail(int result) {
    media.phase=AF_AP_MEDIA_FAILED;media.result=result;media.refresh=1;return result;
}
static int binding_valid(const AfApMediaBinding *b) {
    if(!b||b->version!=AF_AP_MEDIA_VERSION||b->bytes!=sizeof(*b)||b->directory<0||
       b->reserved||!b->scan||!b->read||!b->capacity||b->capacity>AF_MEDIA_SOURCE_MAX||
       !separate(b,sizeof(*b),&media,sizeof(media))||
       !separate(b->source,b->capacity,&media,sizeof(media))||
       !separate(b->source,b->capacity,b,sizeof(*b)))return 0;
    return 1;
}
int af_ap_media_bind(const AfApMediaBinding *b) {
    if(media.bound)return AF_BUSY;
    if(!binding_valid(b))return AF_INVALID;
    media.binding=*b;media.bound=1;media.result=AF_EMPTY;return AF_OK;
}
int af_ap_media_rebind(const AfApMediaBinding *b) {
    if(!media.bound)return AF_MANAGE_NOT_READY;
    if(media.provider.context)return AF_INVALID;
    if(media.phase==AF_AP_MEDIA_BROWSING)return AF_BUSY;
    if(!binding_valid(b))return AF_INVALID;
    if(media.importer.context&&!separate(media.importer.context,1,b->source,b->capacity))return AF_INVALID;
    if(media.importer.cancel){int result=media.importer.cancel(media.importer.context);if(result)return result;}
    media.binding=*b;media.identity=0;media.phase=AF_AP_MEDIA_IDLE;
    media.result=AF_EMPTY;media.refresh=1;return AF_OK;
}
int af_ap_media_importer_bind(const AfApMediaImporter *b) {
    if(!media.bound)return AF_MANAGE_NOT_READY;
    if(media.provider.context)return AF_INVALID;
    if(media.importer.prepare || media.prepare_provider || media.phase==AF_AP_MEDIA_BROWSING)return AF_BUSY;
    if(!b || b->version!=AF_AP_MEDIA_VERSION || b->bytes!=sizeof(*b) ||
       !b->context || !b->prepare || !b->request || !b->cancel ||
       !separate(b,sizeof(*b),&media,sizeof(media)) ||
       !separate(b->context,1,&media,sizeof(media))||
       !separate(b->context,1,media.binding.source,media.binding.capacity))return AF_INVALID;
    media.importer=*b;return AF_OK;
}
static int provider_valid(const AfApMediaProviderBinding *b){
    return b&&b->version==AF_AP_MEDIA_VERSION&&b->bytes==sizeof(*b)&&
        af_media_provider_valid(&b->provider)&&b->capacity&&b->capacity<=AF_MEDIA_SOURCE_MAX&&
        separate(b,sizeof(*b),&media,sizeof(media))&&
        separate(b->source,b->capacity,&media,sizeof(media))&&
        separate(b->source,b->capacity,b,sizeof(*b))&&
        separate(b->provider.context,1,&media,sizeof(media))&&
        separate(b->provider.context,1,b->source,b->capacity);
}
int af_ap_media_provider_bind(const AfApMediaProviderBinding *b){
    if(media.bound)return AF_BUSY;
    if(!provider_valid(b))return AF_INVALID;
    media.provider=b->provider;media.binding.source=b->source;media.binding.capacity=b->capacity;
    media.binding.directory=-1;media.bound=1;media.result=AF_EMPTY;return AF_OK;
}
int af_ap_media_provider_rebind(const AfApMediaProviderBinding *b){
    if(!media.bound)return AF_MANAGE_NOT_READY;
    if(!media.provider.context)return AF_INVALID;
    if(media.phase==AF_AP_MEDIA_BROWSING)return AF_BUSY;
    if(!provider_valid(b))return AF_INVALID;
    if(media.importer.context&&!separate(media.importer.context,1,b->source,b->capacity))return AF_INVALID;
    if(media.cards.context&&!separate(media.cards.context,1,b->source,b->capacity))return AF_INVALID;
    if(media.importer.cancel){int r=media.importer.cancel(media.importer.context);if(r)return r;}
    media.provider=b->provider;media.binding.source=b->source;media.binding.capacity=b->capacity;
    media.identity=0;media.phase=AF_AP_MEDIA_IDLE;media.result=AF_EMPTY;media.refresh=1;return AF_OK;
}
int af_ap_media_provider_importer_bind(const AfApMediaProviderImporter *b){
    if(!media.bound)return AF_MANAGE_NOT_READY;
    if(!media.provider.context)return AF_INVALID;
    if(media.importer.prepare||media.prepare_provider||media.phase==AF_AP_MEDIA_BROWSING)return AF_BUSY;
    if(!b||b->version!=AF_AP_MEDIA_VERSION||b->bytes!=sizeof(*b)||!b->context||
       !b->prepare||!b->request||!b->cancel||!separate(b,sizeof(*b),&media,sizeof(media))||
       !separate(b->context,1,&media,sizeof(media))||
       !separate(b->context,1,media.binding.source,media.binding.capacity))return AF_INVALID;
    media.prepare_provider=b->prepare;media.importer.context=b->context;
    media.importer.request=b->request;media.importer.cancel=b->cancel;return AF_OK;
}
int af_ap_media_card_service_bind(const AfApMediaCardService *service){
    if(!media.bound)return AF_MANAGE_NOT_READY;
    if(media.cards.select||media.card_busy||media.phase==AF_AP_MEDIA_BROWSING)return AF_BUSY;
    if(!media.provider.context||!service||service->version!=AF_AP_MEDIA_VERSION||
       service->bytes!=sizeof(*service)||!service->context||!service->select||
       !separate(service,sizeof(*service),&media,sizeof(media))||
       !separate(service->context,1,&media,sizeof(media))||
       !separate(service->context,1,media.binding.source,media.binding.capacity))return AF_INVALID;
    media.cards=*service;return AF_OK;
}
int af_ap_media_card_available(void){return media.bound&&media.cards.select!=0;}
uint32_t af_ap_media_card_current(void){return media.card_selected?media.card_selected-1u:UINT32_MAX;}
int af_ap_media_card_select(uint32_t slot){
    if(!af_ap_media_card_available())return AF_MANAGE_NOT_READY;
    if(slot>1)return AF_INVALID;
    if(media.card_busy||media.phase==AF_AP_MEDIA_BROWSING)return AF_BUSY;
    media.card_busy=1;
    int result=media.cards.select(media.cards.context,slot);
    media.card_busy=0;
    if(!result){media.card_selected=slot+1u;media.refresh=1;}
    return result;
}
int af_ap_media_import_request(AfApManageRequest *request) {
    if(!request || !separate(request,sizeof(*request),&media,sizeof(media)) ||
       (media.bound&&!separate(request,sizeof(*request),media.binding.source,media.binding.capacity)))return AF_INVALID;
    if(media.phase!=AF_AP_MEDIA_READ_READY || media.result!=AF_OK || !media.importer.request)return AF_MANAGE_NOT_READY;
    AfApManageRequest next={0};
    int result=media.importer.request(media.importer.context,&next);
    if(result!=AF_OK)return result;
    if(next.op!=AF_MANAGE_IMPORT || next.source_slot || next.target_slot || next.overwrite ||
       next.media_generation!=media.info.generation || next.media_index!=media.info.index ||
       !next.name_bytes || next.name_bytes>63 || af_validate(&next.initial)!=AF_OK || next.initial.kind)return AF_STALE;
    *request=next;return AF_OK;
}
int af_ap_media_prepare(void) {
    if(!media.bound)return AF_MANAGE_NOT_READY;
    if(media.card_busy)return AF_BUSY;
    if(media.phase==AF_AP_MEDIA_BROWSING)return AF_BUSY;
    if(media.generation==UINT64_MAX)return AF_EXHAUSTED;
    if(media.importer.cancel){int result=media.importer.cancel(media.importer.context);if(result)return result;}
    uint64_t generation=++media.generation;
    int result=media.provider.context?media.provider.scan(media.provider.context,generation,&media.work,&media.list):
        media.binding.scan(media.binding.directory,generation,&media.work,&media.list);
    if(result)return fail(result);
    if(media.list.generation!=generation)return fail(AF_STALE);
    if(media.identity&&(media.device!=media.list.device||media.inode!=media.list.inode))return fail(AF_STALE);
    if(!media.identity){media.device=media.list.device;media.inode=media.list.inode;media.identity=1;}
    result=af_ap_browser_publish(&media.list);if(result)return fail(result);
    media.phase=AF_AP_MEDIA_BROWSING;media.page=af_ap_browser_page();
    media.result=AF_OK;media.refresh=1;return AF_OK;
}
int af_ap_media_open(void) {
    int result=af_ap_media_prepare();if(result)return result;
    result=af_ap_browser_show();
    if(result){(void)af_ap_browser_cancel();return fail(result);}
    return AF_OK;
}
static int consume(int navigation) {
    if(!media.bound||media.phase!=AF_AP_MEDIA_BROWSING)return AF_EMPTY;
    int result=af_ap_browser_result();
    if(result==AF_BROWSER_CANCELLED) {
        if(navigation){result=af_ap_browser_back();if(result)return fail(result);}
        media.phase=AF_AP_MEDIA_CANCELLED;media.result=AF_MANAGE_CANCEL;media.refresh=1;
        return AF_MANAGE_CANCEL;
    }
    if(result!=AF_OK) {
        if(media.page!=af_ap_browser_page()) {
            if(navigation){result=af_ap_browser_show();if(result)return fail(result);}
            media.page=af_ap_browser_page();media.refresh=1;return AF_OK;
        }
        return AF_EMPTY;
    }
    AfApBrowserSelection selection;AfApMediaInfo info={0};
    result=af_ap_browser_take(media.generation,&selection);if(result)return fail(result);
    if(selection.generation!=media.generation||selection.index>=media.list.count||selection.reserved)return fail(AF_STALE);
    if(navigation){result=af_ap_browser_back();if(result)return fail(result);}
    result=media.provider.context?media.provider.read(media.provider.context,&media.list,selection.index,
        media.binding.source,media.binding.capacity,&info.source,0,0):
        media.binding.read(media.binding.directory,&media.list,selection.index,
        media.binding.source,media.binding.capacity,&info.source,0,0);
    if(result)return fail(result);
    if(!info.source.bytes||info.source.bytes>media.binding.capacity||
       info.source.bytes!=media.list.entries[selection.index].size)return fail(AF_STALE);
    info.generation=selection.generation;info.index=selection.index;media.info=info;
    media.phase=AF_AP_MEDIA_READ_READY;
    media.result=media.prepare_provider?media.prepare_provider(media.importer.context,&media.provider,&media.list,&media.info):
        media.importer.prepare?media.importer.prepare(media.importer.context,media.binding.directory,&media.list,&media.info):AF_MANAGE_NOT_READY;
    media.refresh=1;return media.result;
}
int af_ap_media_poll(void){return consume(1);}
int af_ap_media_finish(void){return consume(0);}
int af_ap_media_cancel(void) {
    if(!media.bound)return AF_INVALID;
    if(media.card_busy)return AF_BUSY;
    if(media.importer.cancel){int result=media.importer.cancel(media.importer.context);if(result)return result;}
    if(media.phase==AF_AP_MEDIA_BROWSING)(void)af_ap_browser_cancel();
    media.phase=AF_AP_MEDIA_CANCELLED;media.result=AF_MANAGE_CANCEL;media.refresh=1;return AF_OK;
}
uint32_t af_ap_media_phase(void){return media.phase;}
int af_ap_media_result(void){return media.result;}
int af_ap_media_snapshot(AfApMediaInfo *out) {
    if(!out||!separate(out,sizeof(*out),&media,sizeof(media))||
       (media.bound&&!separate(out,sizeof(*out),media.binding.source,media.binding.capacity)))return AF_INVALID;
    if(media.phase!=AF_AP_MEDIA_READ_READY)return AF_EMPTY;
    *out=media.info;return AF_OK;
}
const char *af_ap_media_name(void) {
    return media.phase==AF_AP_MEDIA_READ_READY?media.list.entries[media.info.index].name:0;
}
int af_ap_media_refresh(void){int value=(int)media.refresh;media.refresh=0;return value;}
