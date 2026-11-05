/* 真实目标指令中的导入/管理事务；颜色合成后端与内存存储均为显式夹具。 */
#include "../native/af_import.h"
#include "../native/af_persist.h"
#include "../native/af_ui.h"
extern void *memset(void *,int,size_t);
extern void *memcpy(void *,const void *,size_t);
extern int af_joint_synthetic_predict(void *,const AfJointRecipe *,const float *,float *);
static AfImportWork work;
static AfImportCandidate candidate,cancelled_candidate;
static AfJointRecipe seed;
static AfJointAsset asset;
static AfCatalog catalog,reboot;
static AfStore source,target;
static AfGridSample training[8],validation[4];
static float cube_storage[24];
static uint8_t a[4096],b[4096],next[4096],exported[4096];
typedef struct {
    uint8_t records[2][4096],pending[4096];size_t sizes[2],pending_bytes;
    uint32_t pending_bank,owned,fail_directory;
} Memory;
static Memory memory;
uint32_t af_import_target_report[8];
float af_import_target_metrics[7];
static int read_record(void *ctx,uint32_t slot,uint32_t bank,void *out,size_t cap,size_t *bytes) {
    Memory *m=ctx;(void)slot;
    if (bank>1) return -1;
    if (!m->sizes[bank]) return 1;
    if (m->sizes[bank]>cap) return 2;
    memcpy(out,m->records[bank],m->sizes[bank]);*bytes=m->sizes[bank];return 0;
}
static int stage(void *ctx,uint32_t slot,uint32_t bank,const void *raw,size_t bytes) {
    Memory *m=ctx;(void)slot;
    if (bank>1 || m->owned || bytes>4096) return -1;
    memcpy(m->pending,raw,bytes);m->pending_bank=bank;m->pending_bytes=bytes;m->owned=1;return 0;
}
static int sync_data(void *ctx,uint32_t slot,uint32_t bank) {
    Memory *m=ctx;(void)slot;return (!m->owned || m->pending_bank!=bank)?-1:0;
}
static int publish(void *ctx,uint32_t slot,uint32_t bank) {
    Memory *m=ctx;(void)slot;
    if (sync_data(ctx,slot,bank)) return -1;
    memcpy(m->records[bank],m->pending,m->pending_bytes);m->sizes[bank]=m->pending_bytes;m->owned=0;return 0;
}
static int sync_directory(void *ctx,uint32_t slot,uint32_t bank) {
    Memory *m=ctx;(void)slot;(void)bank;return m->fail_directory?-1:0;
}
static int discard(void *ctx,uint32_t slot,uint32_t bank) {
    Memory *m=ctx;(void)slot;(void)bank;m->owned=0;return 0;
}
static int cancel_last(void *ctx,uint32_t done,uint32_t total) {(void)ctx;return done==total;}
#define CHECK(v) do {++af_import_target_report[1];if (!(v)) return __LINE__;} while (0)
uint32_t af_import_target_check(void) {
    static const char text[]="LUT_3D_SIZE 2\n0 0 0\n1 0 0\n.015625 1 0\n1.015625 1 0\n0 .015625 1.015625\n1 .015625 1.03125\n.015625 1.015625 1.015625\n1.015625 1.015625 1.03125\n";
    AfJointModel model={0};AfImportRequest request={0};AfDocument document={0},decoded={0};
    AfStoreIo io={&memory,read_record,stage,sync_data,publish,sync_directory,discard};
    AfStoreBuffers buffers={a,b,next,sizeof(a)};
    AfPreset current={0};size_t bytes=0;unsigned n=0;int value=77;
    memset(af_import_target_report,0,sizeof(af_import_target_report));memset(&memory,0,sizeof(memory));
    memset(&seed,0,sizeof(seed));memset(&catalog,0,sizeof(catalog));memset(&reboot,0,sizeof(reboot));
    af_import_target_report[0]=0x49323231u;
    for (unsigned i=0;i<129;++i) seed.gamma[i]=i*1024;
    model.schema=model.base_mask=model.domain=1;model.components=15;model.model_sha256[0]=0x20;
    for (unsigned i=0;i<32;++i) model.cp_sha256[i]=af_joint_cp_sha256[i];
    model.predict=af_joint_synthetic_predict;
    for (unsigned bb=0;bb<2;++bb) for (unsigned gg=0;gg<2;++gg) for (unsigned rr=0;rr<2;++rr)
        training[n++]=(AfGridSample){{.1f+.6f*rr,.15f+.55f*gg,.12f+.5f*bb},1,0};
    validation[0]=(AfGridSample){{.22f,.22f,.22f},1,1};validation[1]=(AfGridSample){{.41f,.41f,.41f},1,1};
    validation[2]=(AfGridSample){{.61f,.39f,.28f},1,2};validation[3]=(AfGridSample){{.8f,.2f,.55f},1,0};
    request.source=text;request.source_bytes=sizeof(text)-1;request.name="target import";request.name_bytes=13;
    request.model=&model;request.initial.params[6]=3;request.seed=&seed;
    request.training=training;request.training_count=8;request.validation=validation;request.validation_count=4;
    request.options=(AfJointOptions){65,256,16,16,16,4};
    CHECK(af_import_cube(&request,cube_storage,24,&work,&candidate,0,0)==AF_OK);
    CHECK(candidate.fit.attempted_components==15 && candidate.report.samples==4 && candidate.report.scope==1);
    for (unsigned i=0;i<4;++i) CHECK(candidate.fit.accepted[i]>0);
    CHECK(candidate.validation.gray_samples==2 && candidate.validation.skin_samples==1);
    CHECK(af_joint_asset_decode(candidate.image,sizeof(candidate.image),&asset)==AF_OK);
    CHECK(asset.recipe.gamma[128]==133120 && asset.recipe.matrix[0]==16 && asset.recipe.cc1[0]==16 && asset.recipe.grid[0]==4);
    CHECK(af_import_document(&candidate,&document)==AF_OK && document.schema==AF_JOINT_ASSET_SCHEMA);
    af_import_target_metrics[0]=candidate.fit.initial_mse;af_import_target_metrics[1]=candidate.fit.final_mse;
    for (unsigned i=0;i<5;++i) af_import_target_metrics[2+i]=candidate.validation.delta_e76[i];
    memset(&cancelled_candidate,0xa5,sizeof(cancelled_candidate));
    CHECK(af_import_cube(&request,cube_storage,24,&work,&cancelled_candidate,cancel_last,0)==AF_GRID_CANCELLED);
    for (unsigned i=0;i<sizeof(cancelled_candidate);++i) CHECK(((uint8_t *)&cancelled_candidate)[i]==0xa5);
    CHECK(af_store_init(&source,20,AF_JOINT_ASSET_SCHEMA,3072)==AF_STORE_OK);
    CHECK(af_persist_load(&catalog,&source,&io,&buffers,1)==AF_STORE_MISSING);
    CHECK(af_persist_replace(&catalog,&source,&io,&buffers,&document,0)==AF_STORE_OK);
    CHECK(af_persist_replace(&catalog,&source,&io,&buffers,&document,0)==AF_PERSIST_EXISTS);
    CHECK(af_ui_assign(&catalog,0x15e6,0,-9,&value)==AF_OK && value==-9);
    CHECK(af_persist_rename(&catalog,&source,&io,&buffers,"renamed",7)==AF_STORE_OK);
    CHECK(af_dirty(&catalog,20)==1 && catalog.slots[19].working.params[0]==-9 && catalog.slots[19].saved.params[0]==0);
    CHECK(catalog.slots[19].saved_revision==source.generation && source.generation==2);
    CHECK(af_persist_export(&catalog,&source,&io,&buffers,0,exported,sizeof(exported),&bytes)==AF_STORE_OK);
    CHECK(af_document_decode(exported,bytes,AF_JOINT_ASSET_SCHEMA,&decoded)==AF_DOCUMENT_OK);
    CHECK(decoded.saved.params[0]==0 && af_document_report_applies(&decoded,&decoded.saved)==1);
    CHECK(af_import_asset(&decoded,&asset)==AF_OK && asset.recipe.gamma[128]==133120);
    CHECK(af_persist_export(&catalog,&source,&io,&buffers,1,exported,sizeof(exported),&bytes)==AF_STORE_OK);
    CHECK(af_document_decode(exported,bytes,AF_JOINT_ASSET_SCHEMA,&decoded)==AF_DOCUMENT_OK);
    CHECK(decoded.saved.params[0]==-9 && af_document_report_applies(&decoded,&decoded.saved)==0);
    CHECK(af_persist_save(&catalog,&source,&io,&buffers)==AF_STORE_OK && af_dirty(&catalog,20)==0);
    CHECK(af_store_init(&target,20,AF_JOINT_ASSET_SCHEMA,3072)==AF_STORE_OK);
    CHECK(af_persist_load(&reboot,&target,&io,&buffers,0)==AF_STORE_OK);
    CHECK(af_read(&reboot,20,0,&current)==AF_OK && current.params[0]==-9);
    CHECK(af_restore(&reboot,20,1)==AF_OK && af_read(&reboot,20,0,&current)==AF_OK && current.params[0]==0);
    memory.fail_directory=1;
    CHECK(af_persist_rename(&catalog,&source,&io,&buffers,"uncertain",9)==AF_STORE_UNCERTAIN);
    CHECK(af_persist_save(&catalog,&source,&io,&buffers)==AF_STORE_UNCERTAIN);
    memory.fail_directory=0;
    CHECK(af_persist_load(&catalog,&source,&io,&buffers,0)==AF_STORE_OK);
    CHECK(af_persist_clear(&catalog,&source,&io,&buffers)==AF_STORE_OK);
    CHECK(af_persist_load(&reboot,&target,&io,&buffers,0)==AF_STORE_OK && af_read(&reboot,20,0,&current)==AF_EMPTY);
    CHECK(af_ui_read(&catalog,0x84c,0,&value)==AF_UI_NATIVE && value==-9);
    af_import_target_report[2]=(uint32_t)sizeof(work);af_import_target_report[3]=(uint32_t)sizeof(candidate);
    af_import_target_report[4]=AF_JOINT_ASSET_BYTES;af_import_target_report[5]=(uint32_t)source.generation;
    af_import_target_report[6]=71;af_import_target_report[7]=1;
    return 0;
}
