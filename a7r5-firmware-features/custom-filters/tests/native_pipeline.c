/* 目标指令集的无设备闭环。内存后端和应用回执仅是显式测试边界。 */
#include "../native/af_persist.h"
#include "../native/af_ui.h"
#include "../native/af_versions.h"
#include "../native/af_sha256.h"
#include "../native/af_cp406.h"
#include "../native/af_labels_store.h"

#define CAP 544u
#define CHECK(condition) do { ++af_pipeline_report[1];if (!(condition)) return __LINE__; } while (0)
uint32_t af_pipeline_report[8];
uint8_t af_pipeline_digest[32];
uint8_t af_pipeline_cp_digest[32];
static uint8_t cp_source[AF_CP406_PREFIX_BYTES],cp_snapshot[AF_CP406_PREFIX_BYTES];
static uint8_t files[20][2][CAP],staged[CAP],buffers[3][CAP],version_bytes[3][512];
static size_t lengths[20][2],staged_bytes;
static uint32_t staged_slot,staged_bank;
static int sync_fails,publish_fails;
static AfCatalog catalog;
static AfStore stores[20];
static AfVersions versions;
static AfLabels labels;

/* 为独立ELF提供内存ABI；没有替代业务行为或原厂成像函数。 */
#ifdef AF_PIPELINE_TARGET
void *memcpy(void *to,const void *from,size_t bytes) {
    for (size_t i=0;i<bytes;++i) ((uint8_t *)to)[i]=((const uint8_t *)from)[i];
    return to;
}
void *memset(void *to,int value,size_t bytes) {
    for (size_t i=0;i<bytes;++i) ((uint8_t *)to)[i]=(uint8_t)value;
    return to;
}
void __aeabi_memcpy(void *to,const void *from,size_t n) { (void)memcpy(to,from,n); }
void __aeabi_memcpy4(void *to,const void *from,size_t n) { (void)memcpy(to,from,n); }
void __aeabi_memcpy8(void *to,const void *from,size_t n) { (void)memcpy(to,from,n); }
void __aeabi_memmove(void *to,const void *from,size_t n) {
    if ((uintptr_t)to>(uintptr_t)from && (uintptr_t)to-(uintptr_t)from<n) {
        while (n) { --n;((uint8_t *)to)[n]=((const uint8_t *)from)[n]; }
    } else (void)memcpy(to,from,n);
}
void __aeabi_memclr(void *to,size_t n) { (void)memset(to,0,n); }
void __aeabi_memclr4(void *to,size_t n) { (void)memset(to,0,n); }
void __aeabi_memclr8(void *to,size_t n) { (void)memset(to,0,n); }
#else
#include <string.h>
#endif

static int read_record(void *c,uint32_t slot,uint32_t bank,void *p,size_t cap,size_t *n) {
    size_t size=lengths[slot-1][bank];
    (void)c;
    if (!size) return 1;
    if (size>cap) return 2;
    memcpy(p,files[slot-1][bank],size);*n=size;
    return 0;
}
static int stage(void *c,uint32_t slot,uint32_t bank,const void *p,size_t n) {
    (void)c;
    if (n>CAP || staged_bytes) return -1;
    memcpy(staged,p,n);staged_bytes=n;staged_slot=slot;staged_bank=bank;
    return 0;
}
static int sync_data(void *c,uint32_t slot,uint32_t bank) {
    (void)c;(void)slot;(void)bank;
    return sync_fails?-1:0;
}
static int publish(void *c,uint32_t slot,uint32_t bank) {
    (void)c;
    if (!staged_bytes || slot!=staged_slot || bank!=staged_bank) return -1;
    memcpy(files[slot-1][bank],staged,staged_bytes);lengths[slot-1][bank]=staged_bytes;
    staged_bytes=0;
    return publish_fails?-1:0;
}
static int sync_directory(void *c,uint32_t slot,uint32_t bank) {
    (void)c;(void)slot;(void)bank;return 0;
}
static int discard(void *c,uint32_t slot,uint32_t bank) {
    (void)c;(void)slot;(void)bank;staged_bytes=0;return 0;
}

uint32_t af_pipeline_check(void) {
    AfStoreIo io={0,read_record,stage,sync_data,publish,sync_directory,discard};
    AfStoreBuffers b={buffers[0],buffers[1],buffers[2],CAP};
    AfDocument d={0};
    AfPreset current;
    AfVersionToken tokens[4];
    AfVersionLease refs[3];
    const void *pinned;
    size_t pinned_bytes,encoded_bytes;
    int value;
    static const int adjusted[8]={-9,9,-8,7,6,5,4,3};
    static const unsigned cp_bases[12]={0,3,2,1,16,15,19,20,17,18,5,13};
    memset(af_pipeline_report,0,sizeof(af_pipeline_report));
    memset(lengths,0,sizeof(lengths));sync_fails=0;publish_fails=0;staged_bytes=0;
    af_pipeline_report[0]=0x41375031u;
    af_catalog_init(&catalog);
    for (size_t i=0;i<sizeof(cp_source);++i) cp_source[i]=(uint8_t)(17*i+3);
    d.present=1;d.name="C20";d.name_bytes=3;d.initial.params[6]=3;d.saved=d.initial;
    for (uint32_t slot=1;slot<=20;++slot) {
        AfUiRoute route;
        CHECK(af_store_init(&stores[slot-1],slot,0,512)==0);
        CHECK(af_persist_load(&catalog,&stores[slot-1],&io,&b,1)==AF_STORE_MISSING);
        d.initial.base=(uint8_t)af_builtin_selector((slot-1)%12);d.saved=d.initial;
        CHECK(af_persist_replace(&catalog,&stores[slot-1],&io,&b,&d,0)==0);
        CHECK(af_ui_item(11+slot,&route)==0 && route.slot==slot);
        for (unsigned j=0;j<8;++j) CHECK(af_ui_assign(&catalog,route.menu,j,adjusted[j],&value)==0 && value==adjusted[j]);
        CHECK(af_read(&catalog,slot,0,&current)==0);
        CHECK(af_cp406_overlay(&current,cp_source,cp_snapshot,sizeof(cp_source))==0);
        CHECK(af_cp406_matches(&current,cp_snapshot,sizeof(cp_snapshot))==0);
        CHECK(cp_snapshot[0xa40]==cp_bases[(slot-1)%12]);
        CHECK(af_persist_save(&catalog,&stores[slot-1],&io,&b)==0);
        CHECK(af_dirty(&catalog,slot)==0);
        ++af_pipeline_report[2];
    }
    af_catalog_init(&catalog);
    for (uint32_t slot=1;slot<=20;++slot) {
        CHECK(af_store_init(&stores[slot-1],slot,0,512)==0);
        CHECK(af_persist_load(&catalog,&stores[slot-1],&io,&b,0)==0);
        CHECK(af_read(&catalog,slot,0,&current)==0);
        for (unsigned j=0;j<8;++j) CHECK(current.params[j]==adjusted[j]);
        CHECK(current.base==af_builtin_selector((slot-1)%12));
        CHECK(af_cp406_overlay(&current,cp_source,cp_snapshot,sizeof(cp_source))==0);
        CHECK(af_cp406_matches(&current,cp_snapshot,sizeof(cp_snapshot))==0);
        ++af_pipeline_report[3];
    }
    CHECK(af_sha256(cp_snapshot,sizeof(cp_snapshot),af_pipeline_cp_digest)==0);
    for (size_t i=0;i<sizeof(cp_source);++i) CHECK(cp_source[i]==(uint8_t)(17*i+3));
    CHECK(af_edit(&catalog,20,0,5)==0);sync_fails=1;
    CHECK(af_persist_save(&catalog,&stores[19],&io,&b)==AF_STORE_IO);
    CHECK(af_read(&catalog,20,1,&current)==0 && current.params[0]==-9);
    CHECK(af_dirty(&catalog,20)==1);sync_fails=0;publish_fails=1;
    CHECK(af_persist_save(&catalog,&stores[19],&io,&b)==AF_STORE_UNCERTAIN);
    CHECK(af_persist_save(&catalog,&stores[19],&io,&b)==AF_STORE_UNCERTAIN);
    publish_fails=0;
    CHECK(af_persist_load(&catalog,&stores[19],&io,&b,0)==0);
    CHECK(af_read(&catalog,20,0,&current)==0 && current.params[0]==5);
    af_pipeline_report[4]=2;
    CHECK(af_persist_copy(&catalog,&stores[19],&stores[6],&io,&io,&b,"copy",4,1)==0);
    CHECK(af_read(&catalog,7,0,&current)==0 && current.params[0]==5);
    CHECK(af_persist_clear(&catalog,&stores[19],&io,&b)==0);
    CHECK(af_persist_load(&catalog,&stores[19],&io,&b,0)==0);
    CHECK(af_read(&catalog,20,0,&current)==AF_EMPTY);
    af_pipeline_report[5]=2;
    CHECK(af_store_recover(&stores[6],&io,&b,0,&d)==0);
    CHECK(af_document_encode(&d,0,staged,512,&encoded_bytes)==0);
    CHECK(af_sha256(staged,encoded_bytes,af_pipeline_digest)==0);
    CHECK(af_versions_init(&versions,version_bytes[0],version_bytes[1],version_bytes[2],512,0)==0);
    for (unsigned i=0;i<3;++i) {
        CHECK(af_versions_stage(&versions,staged,encoded_bytes,&tokens[i])==0);
        CHECK(af_versions_finish(&versions,&tokens[i],1)==0);
        CHECK(af_versions_acquire(&versions,&refs[i])==0);
    }
    CHECK(af_versions_stage(&versions,staged,encoded_bytes,&tokens[3])==AF_BUSY);
    CHECK(af_versions_view(&versions,&refs[0],&pinned,&pinned_bytes)==0 && pinned_bytes==encoded_bytes);
    for (size_t i=0;i<encoded_bytes;++i) CHECK(((const uint8_t *)pinned)[i]==staged[i]);
    CHECK(af_versions_release(&versions,&refs[0])==0);
    CHECK(af_versions_release(&versions,&refs[0])==AF_STALE);
    CHECK(af_versions_stage(&versions,staged,encoded_bytes,&tokens[3])==0);
    CHECK(af_versions_finish(&versions,&tokens[0],1)==AF_STALE);
    CHECK(af_versions_finish(&versions,&tokens[3],0)==AF_IO);
    CHECK(af_versions_release(&versions,&refs[1])==0);
    CHECK(af_versions_release(&versions,&refs[2])==0);
    /* 真实目标ABI联验保存后的基底及名称；内存后端不是机身文件服务。 */
    {
        const char name[]="\xe6\x9a\x96\xe5\x85\x89 C07";
        const char *shown=0;size_t shown_bytes=0;
        af_labels_init(&labels);
        CHECK(af_edit_base(&catalog,7,17)==AF_OK);
        CHECK(af_persist_save(&catalog,&stores[6],&io,&b)==AF_STORE_OK);
        CHECK(af_persist_rename(&catalog,&stores[6],&io,&b,name,sizeof(name)-1)==AF_STORE_OK);
        CHECK(af_labels_from_store(&labels,&catalog,&stores[6],&b,0)==AF_STORE_OK);
        CHECK(af_labels_read(&labels,7,&shown,&shown_bytes)==AF_OK && shown_bytes==sizeof(name)-1);
        for (size_t i=0;i<sizeof(name);++i) CHECK(shown[i]==name[i]);
        CHECK(af_edit_base(&catalog,7,18)==AF_OK && af_dirty(&catalog,7)==1);
        CHECK(af_persist_load(&catalog,&stores[6],&io,&b,0)==AF_STORE_OK);
        CHECK(af_read(&catalog,7,0,&current)==AF_OK && current.base==17 && current.params[0]==5);
        CHECK(af_labels_from_store(&labels,&catalog,&stores[6],&b,1)==AF_STORE_OK);
        CHECK(af_persist_clear(&catalog,&stores[6],&io,&b)==AF_STORE_OK);
        CHECK(af_labels_from_store(&labels,&catalog,&stores[6],&b,0)==AF_STORE_OK);
        CHECK(af_labels_read(&labels,7,&shown,&shown_bytes)==AF_EMPTY);
    }
    af_pipeline_report[6]=3;af_pipeline_report[7]=1;
    return 0;
}
