"""真实文件选择到显式转换服务；不提供默认模型或相机资格。"""
import subprocess

import pytest

from test_ap_media import HARNESS, NATIVE


EXTRA = r'''
static int prepared,requests,cancels,reject;
static AfApMediaInfo expected;
static int prepare_import(void *context,int fd,const AfMediaList *list,const AfApMediaInfo *info){
 assert(context==&prepared&&fd>=0&&list->generation==info->generation&&info->index==0);
 uint8_t digest[32];assert(af_sha256(source,info->source.bytes,digest)==0);
 assert(!memcmp(digest,info->source.sha256,32));expected=*info;++prepared;
 return reject?AF_MANAGE_NOT_READY:AF_OK;
}
static int import_template(void *context,AfApManageRequest *out){
 assert(context==&prepared);++requests;*out=(AfApManageRequest){0};
 out->op=AF_MANAGE_IMPORT;out->media_generation=expected.generation;
 out->media_index=expected.index;out->initial.params[6]=3;out->name_bytes=6;memcpy(out->name,"Import",6);
 if(reject==2)++out->media_generation;return AF_OK;
}
static int cancel_import(void *context){assert(context==&prepared);++cancels;return AF_OK;}
int main(int argc,char **argv){
 assert(argc==3);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);
 put(fd,cube,sizeof(cube)-1);
 AfApMediaBinding b={1,sizeof(b),fd,0,af_media_scan,actual_read,source,sizeof(source)};
 AfApMediaImporter importer={1,sizeof(importer),&prepared,prepare_import,import_template,cancel_import};
 assert(af_ap_media_importer_bind(&importer)==AF_MANAGE_NOT_READY);
 assert(af_ap_media_bind(&b)==0&&af_ap_media_importer_bind(&importer)==0);
 assert(af_ap_media_importer_bind(&importer)==AF_BUSY);
 AfApManageRequest q={0},before=q;
 assert(af_ap_media_import_request(&q)==AF_MANAGE_NOT_READY);
 assert(af_ap_media_prepare()==0&&cancels==1);
 if(argv[2][0]=='n')reject=1;
 browser_status=AF_OK;
 assert(af_ap_media_finish()==(reject?AF_MANAGE_NOT_READY:AF_OK)&&prepared==1&&read_count==1);
 if(reject){assert(af_ap_media_import_request(&q)==AF_MANAGE_NOT_READY&&!requests);}
 else{
  assert(af_ap_media_import_request(&q)==0&&requests==1&&q.op==3&&q.media_generation==1&&!q.target_slot&&!q.overwrite);
  before=q;reject=2;assert(af_ap_media_import_request(&q)==AF_STALE&&!memcmp(&before,&q,sizeof(q)));
 }
 assert(af_ap_media_cancel()==0&&cancels==2);
 assert(af_ap_media_import_request(&q)==AF_MANAGE_NOT_READY);
 assert(close(fd)==0);return 0;
}
'''


@pytest.mark.parametrize('case', ['ready', 'no-model'])
def test_selected_source_identity_and_deferred_request(tmp_path, case):
    source = tmp_path / 'driver.c'
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0] + EXTRA)
    binary = tmp_path / 'driver'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                          '-I' + str(NATIVE), str(source),
                          *[str(NATIVE / n) for n in ('af_ap_media.c', 'af_media.c', 'af_sha256.c', 'af_slots.c')],
                          '-o', str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    run = subprocess.run([str(binary), str(tmp_path), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
