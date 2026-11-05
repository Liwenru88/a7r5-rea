"""已知context起始字节与媒体工作区必须隔离；不猜context大小，不执行设备接口。"""
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
sys.path.insert(0,str(ROOT/'a7r5-firmware-features/custom-filters/tests'))
from test_ap_media import HARNESS, NATIVE

EXTRA=r'''
static uint64_t provider_context=0x1234567812345678ULL;
static uint8_t importer_context[4096];
static int cancels;
static int pscan(void *ctx,uint64_t gen,AfMediaList *work,AfMediaList *out){
 (void)ctx;(void)gen;(void)work;(void)out;assert(0);return AF_IO;
}
static int pread_(void *ctx,const AfMediaList *list,uint32_t index,void *out,size_t cap,
 AfMediaSource *info,AfGridProgress p,void *opaque){
 (void)ctx;(void)list;(void)index;(void)out;(void)cap;(void)info;(void)p;(void)opaque;
 assert(0);return AF_IO;
}
static int fscan(int fd,uint64_t gen,AfMediaList *work,AfMediaList *out){
 (void)fd;(void)gen;(void)work;(void)out;assert(0);return AF_IO;
}
static int fread_(int fd,const AfMediaList *list,uint32_t index,void *out,size_t cap,
 AfMediaSource *info,AfGridProgress p,void *opaque){
 (void)fd;(void)list;(void)index;(void)out;(void)cap;(void)info;(void)p;(void)opaque;
 assert(0);return AF_IO;
}
static int pp(void *ctx,const AfMediaProvider *p,const AfMediaList *l,const AfApMediaInfo *i){
 (void)ctx;(void)p;(void)l;(void)i;return AF_OK;
}
static int fp(void *ctx,int fd,const AfMediaList *l,const AfApMediaInfo *i){
 (void)ctx;(void)fd;(void)l;(void)i;return AF_OK;
}
static int req(void *ctx,AfApManageRequest *r){(void)ctx;(void)r;return AF_MANAGE_NOT_READY;}
static int cancel(void *ctx){(void)ctx;++cancels;return AF_OK;}
int main(int argc,char **argv){
 assert(argc==3);(void)cube;
 int provider=argv[1][0]=='p',rebinding=argv[2][0]=='r';
 AfApMediaProviderBinding p={1,sizeof(p),{1,sizeof(AfMediaProvider),&provider_context,pscan,pread_},source,sizeof(source)};
 AfApMediaBinding f={1,sizeof(f),3,0,fscan,fread_,source,sizeof(source)};
 assert((provider?af_ap_media_provider_bind(&p):af_ap_media_bind(&f))==AF_OK);
 void *context=rebinding?(void *)importer_context:(void *)(source+32);
 AfApMediaProviderImporter pi={1,sizeof(pi),context,pp,req,cancel};
 AfApMediaImporter fi={1,sizeof(fi),context,fp,req,cancel};
 int status=provider?af_ap_media_provider_importer_bind(&pi):af_ap_media_importer_bind(&fi);
 if(rebinding){
  assert(status==AF_OK);p.source=f.source=importer_context;
  status=provider?af_ap_media_provider_rebind(&p):af_ap_media_rebind(&f);
 }
 printf("%s %s status=%d cancels=%d\n",argv[1],argv[2],status,cancels);fflush(stdout);
 assert(status==AF_INVALID);
 assert(cancels==0); /* 拒绝必须发生在取消旧选择/释放上下文之前。 */
 return 0;
}
'''

@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    folder=tmp_path_factory.mktemp('provider-known-alias');source=folder/'driver.c';binary=folder/'driver'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0]+EXTRA)
    command=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
             '-I'+str(NATIVE),str(source),*[str(NATIVE/n) for n in
             ('af_ap_media.c','af_media.c','af_sha256.c','af_slots.c')],'-o',str(binary)]
    result=subprocess.run(command,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return binary

@pytest.mark.parametrize('mode',['fd','provider'])
@pytest.mark.parametrize('operation',['bind','rebind'])
def test_importer_context_start_is_never_a_media_write_buffer(driver,mode,operation):
    result=subprocess.run([str(driver),mode,operation],text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
