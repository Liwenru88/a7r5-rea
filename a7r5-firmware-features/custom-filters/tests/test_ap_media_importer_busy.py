"""活动导入持有旧媒体输入时，不允许成功换绑或取消并提前释放输入。"""
from pathlib import Path
import subprocess
from test_ap_media import HARNESS

NATIVE = Path(__file__).resolve().parents[1] / 'native'
EXTRA = r'''
static int held,cancels,prepared;
static uint8_t replacement[sizeof(source)];
static int prepare_import(void *context,int directory,const AfMediaList *list,const AfApMediaInfo *info){
 assert(context==&held&&directory>=0&&list->generation==info->generation);++prepared;return AF_OK;
}
static int request_import(void *context,AfApManageRequest *request){(void)context;(void)request;return AF_MANAGE_NOT_READY;}
static int release_input(void *context){assert(context==&held);if(held)return AF_BUSY;++cancels;return AF_OK;}
#ifdef AF_TEST_OLD_CANCEL_VOID
static void cancel_import(void *context){(void)release_input(context);}
#else
static int cancel_import(void *context){return release_input(context);}
#endif
int main(int argc,char **argv){
 assert(argc==2);int fd=open(argv[1],O_RDONLY|O_DIRECTORY);assert(fd>=0);put(fd,cube,sizeof(cube)-1);
 AfApMediaBinding original={1,sizeof(original),fd,0,af_media_scan,actual_read,source,sizeof(source)};
 AfApMediaImporter importer={1,sizeof(importer),&held,prepare_import,request_import,cancel_import};
 assert(af_ap_media_bind(&original)==0&&af_ap_media_importer_bind(&importer)==0);
 assert(af_ap_media_prepare()==0&&cancels==1);browser_status=AF_OK;
 assert(af_ap_media_finish()==0&&prepared==1&&read_count==1&&af_ap_media_phase()==AF_AP_MEDIA_READ_READY);
 AfApMediaInfo before,now;assert(af_ap_media_snapshot(&before)==0);
 AfApMediaBinding next=original;next.source=replacement;memset(replacement,0x5a,sizeof(replacement));held=1;
 assert(af_ap_media_rebind(&next)==AF_BUSY);
 assert(af_ap_media_cancel()==AF_BUSY);
 assert(af_ap_media_prepare()==AF_BUSY);
 assert(cancels==1&&af_ap_media_phase()==AF_AP_MEDIA_READ_READY&&af_ap_media_result()==AF_OK);
 assert(af_ap_media_snapshot(&now)==0&&!memcmp(&before,&now,sizeof(now))&&read_count==1);
 assert(!memcmp(source,cube,sizeof(cube)-1)&&replacement[0]==0x5a);
 /* 实际拥有者已结束后才可取消；先前BUSY换绑不得偷偷替换原source。 */
 held=0;assert(af_ap_media_cancel()==0&&cancels==2&&af_ap_media_snapshot(&now)==AF_EMPTY);
 assert(af_ap_media_prepare()==0&&cancels==3);browser_status=AF_OK;
 assert(af_ap_media_finish()==0&&read_count==2&&af_ap_media_snapshot(&now)==0&&now.generation==2);
 assert(!memcmp(source,cube,sizeof(cube)-1)&&replacement[0]==0x5a);
 assert(af_ap_media_cancel()==0&&close(fd)==0);return 0;
}
'''


def source_text():
    return HARNESS.split('int main(int argc,char **argv)')[0] + EXTRA


def test_active_import_keeps_media_binding_and_snapshot_until_release(tmp_path):
    source, binary = tmp_path / 'driver.c', tmp_path / 'driver'
    source.write_text(source_text())
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-I' + str(NATIVE), str(source), *[str(NATIVE / n) for n in
        ('af_ap_media.c','af_media.c','af_sha256.c','af_slots.c')], '-o', str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([str(binary), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
