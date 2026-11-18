"""原生卡槽切换在扫描前完成；不调用真实卡或文件接口。"""
import subprocess
from test_ap_media import HARNESS, NATIVE

EXTRA=r'''
static uint64_t token[2]={0x1234567812345678ULL,0x8765432187654321ULL};
static int scans,routes,fault,cancel_busy;
static AfApMediaProviderBinding binding;
static int scan_card(void *ctx,uint64_t gen,AfMediaList *work,AfMediaList *out){
 assert(ctx==&token[0]||ctx==&token[1]);++scans;memset(work,0,sizeof(*work));work->generation=gen;*out=*work;return 0;
}
static int read_card(void *ctx,const AfMediaList *l,uint32_t i,void *o,size_t n,AfMediaSource *s,AfGridProgress p,void *c){
 (void)ctx;(void)l;(void)i;(void)o;(void)n;(void)s;(void)p;(void)c;assert(0);return AF_IO;
}
static int select_card(void *ctx,uint32_t slot){
 assert(ctx==&routes&&slot<2);++routes;
 assert(af_ap_media_card_select(slot)==AF_BUSY);
 if(fault)return AF_IO;
 AfApMediaProviderBinding next=binding;next.provider.context=&token[slot];
 return af_ap_media_provider_rebind(&next);
}
static int prepare(void *ctx,const AfMediaProvider *p,const AfMediaList *l,const AfApMediaInfo *i){
 (void)ctx;(void)p;(void)l;(void)i;return AF_MANAGE_NOT_READY;
}
static int request(void *ctx,AfApManageRequest *q){(void)ctx;(void)q;return AF_MANAGE_NOT_READY;}
static int cancel(void *ctx){assert(ctx==&cancel_busy);return cancel_busy?AF_BUSY:0;}
int main(void){
 (void)cube;AfApMediaCardService service={1,sizeof(service),&routes,select_card};
 assert(!af_ap_media_card_available()&&af_ap_media_card_current()==UINT32_MAX);
 assert(af_ap_media_card_service_bind(&service)==AF_MANAGE_NOT_READY);
 binding=(AfApMediaProviderBinding){1,sizeof(binding),{1,sizeof(AfMediaProvider),&token[0],scan_card,read_card},source,sizeof(source)};
 assert(!af_ap_media_provider_bind(&binding));
 AfApMediaProviderImporter importer={1,sizeof(importer),&cancel_busy,prepare,request,cancel};
 assert(!af_ap_media_provider_importer_bind(&importer));
 AfApMediaCardService bad=service;bad.context=source+8;
 assert(af_ap_media_card_service_bind(&bad)==AF_INVALID);
 assert(!af_ap_media_card_service_bind(&service)&&af_ap_media_card_available());
 assert(af_ap_media_card_service_bind(&service)==AF_BUSY);
 AfApMediaProviderBinding overlap=binding;overlap.source=&routes;overlap.capacity=sizeof(routes);
 assert(af_ap_media_provider_rebind(&overlap)==AF_INVALID);
 assert(af_ap_media_card_select(2)==AF_INVALID&&!routes&&!scans);
 assert(!af_ap_media_prepare()&&scans==1);
 assert(af_ap_media_card_select(1)==AF_BUSY&&!routes&&af_ap_media_card_current()==UINT32_MAX);
 assert(!af_ap_media_cancel());cancel_busy=1;
 assert(af_ap_media_card_select(1)==AF_BUSY&&routes==1&&af_ap_media_phase()==AF_AP_MEDIA_CANCELLED);
 cancel_busy=0;assert(!af_ap_media_card_select(1)&&routes==2&&scans==1);
 assert(af_ap_media_card_current()==1&&af_ap_media_phase()==AF_AP_MEDIA_IDLE&&scans==1);
 fault=1;assert(af_ap_media_card_select(0)==AF_IO&&af_ap_media_card_current()==1);
 assert(!af_ap_media_prepare()&&scans==2);return 0;
}
'''

def test_native_card_switch_rebinds_before_scanning_and_preserves_busy_input(tmp_path):
    source=tmp_path/'driver.c';binary=tmp_path/'driver'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA)
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
        '-I'+str(NATIVE),str(source),*[str(NATIVE/n) for n in ('af_ap_media.c','af_media.c','af_sha256.c','af_slots.c')],
        '-o',str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    run=subprocess.run([str(binary)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
