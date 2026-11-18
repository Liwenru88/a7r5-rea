"""不透明原生介质上下文贯穿浏览；64位token不能截断成POSIX fd。"""
import subprocess
import pytest
from test_ap_media import HARNESS, NATIVE

EXTRA = r'''
static uint64_t token=0x1234567812345678ULL;
static int cancelled,prepared;
static int scan_provider(void *ctx,uint64_t gen,AfMediaList *work,AfMediaList *out){
 assert(ctx==&token&&*(uint64_t *)ctx==0x1234567812345678ULL);
 memset(work,0,sizeof(*work));work->generation=gen;work->count=1;
 strcpy(work->entries[0].name,"暖光.cube");work->entries[0].size=sizeof(cube)-1;*out=*work;return 0;
}
static int read_provider(void *ctx,const AfMediaList *list,uint32_t index,void *out,size_t cap,
 AfMediaSource *info,AfGridProgress progress,void *opaque){
 assert(ctx==&token&&index==0&&list->device==0&&list->inode==0&&cap>=sizeof(cube));
 (void)progress;(void)opaque;++read_count;memcpy(out,cube,sizeof(cube)-1);
 info->bytes=sizeof(cube)-1;assert(af_sha256(out,info->bytes,info->sha256)==0);return 0;
}
static int prepare_provider(void *ctx,const AfMediaProvider *p,const AfMediaList *list,const AfApMediaInfo *info){
 assert(ctx==&prepared&&p->context==&token&&p->read==read_provider);
 assert(list->generation==info->generation&&info->source.bytes==sizeof(cube)-1);++prepared;return 0;
}
static int request_provider(void *ctx,AfApManageRequest *q){(void)ctx;(void)q;return AF_MANAGE_NOT_READY;}
static int cancel_provider(void *ctx){assert(ctx==&prepared);return cancelled?AF_BUSY:0;}
int main(int argc,char **argv){
 (void)argc;(void)argv;
 AfApMediaProviderBinding b={1,sizeof(b),{1,sizeof(AfMediaProvider),&token,scan_provider,read_provider},source,sizeof(source)};
 AfApMediaProviderImporter i={1,sizeof(i),&prepared,prepare_provider,request_provider,cancel_provider};
 assert(af_ap_media_provider_bind(&b)==0&&af_ap_media_provider_importer_bind(&i)==0);
 assert(af_ap_media_prepare()==0&&af_ap_media_provider_rebind(&b)==AF_BUSY);
 browser_status=AF_OK;assert(af_ap_media_finish()==0&&prepared==1&&read_count==1);
 AfApMediaInfo info;assert(af_ap_media_snapshot(&info)==0&&info.generation==1);
 cancelled=1;assert(af_ap_media_provider_rebind(&b)==AF_BUSY);
 assert(af_ap_media_snapshot(&info)==0);cancelled=0;
 assert(af_ap_media_provider_rebind(&b)==0&&af_ap_media_snapshot(&info)==AF_EMPTY);
 assert(af_ap_media_prepare()==0&&published.generation==2);
 assert(af_ap_media_cancel()==0&&read_count==1);return 0;
}
'''

def test_opaque_provider_selection_and_busy_lifetime(tmp_path):
    source=tmp_path/'driver.c'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA)
    binary=tmp_path/'driver'
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
        '-I'+str(NATIVE),str(source),*[str(NATIVE/n) for n in
        ('af_ap_media.c','af_media.c','af_sha256.c','af_slots.c')],'-o',str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
