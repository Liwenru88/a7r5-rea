"""受约束求解经真实仓库服务保存和恢复完整配方；仅使用宿主临时目录。"""
import subprocess

import pytest

from test_repository_import_service import EXTRA, HARNESS, NATIVE


CHECKED_MODEL = r'''
static int basis_checked_predict(void *context,const AfJointRecipe *recipe,
 const float *input,float *output){
 for(unsigned i=0;i<6;++i)for(unsigned e=1;e<3;++e)
  assert(recipe->matrix[i]-seed.matrix[i]==recipe->matrix[6*e+i]-seed.matrix[6*e+i]);
 for(unsigned i=0;i<8;++i)for(unsigned e=1;e<3;++e)
  assert(recipe->cc1[i]-seed.cc1[i]==recipe->cc1[8*e+i]-seed.cc1[8*e+i]);
 return af_joint_synthetic_predict(context,recipe,input,output);
}
'''


RECOVERED_EXPORT = r'''
 if(catalog.slots[6].present){
  /* 新服务没有转换模型或源CUBE，完整AJR1只可能来自持久化记录。 */
  assert(!service_model.predict&&!candidate.initial.kind&&af_dirty(&catalog,7)==0);
  assert(af_repository_service_capabilities(s)==0x3f);
  assert(mkdirat(fd,"recovered",0700)==0);
  int restored_library=openat(fd,"recovered",O_RDONLY|O_DIRECTORY);assert(restored_library>=0);
  assert(af_repository_service_bind_library(s,restored_library)==0);
  q=(AfApManageRequest){0};q.op=AF_MANAGE_EXPORT;q.source_slot=q.target_slot=7;
  assert(af_ap_manage_submit(&manager,&catalog,&q)==0&&af_repository_service_pump(s,&manager)==0);
  int restored_file=openat(restored_library,"C07_G0000000000000001.a7filter",O_RDONLY);assert(restored_file>=0);
  uint8_t restored_bytes[4096];ssize_t restored_count=read(restored_file,restored_bytes,sizeof(restored_bytes));
  assert(restored_count>AF_JOINT_ASSET_BYTES&&close(restored_file)==0&&close(restored_library)==0);
  AfDocument restored;AfJointAsset restored_asset;
  assert(af_document_decode(restored_bytes,(size_t)restored_count,AF_JOINT_ASSET_SCHEMA,&restored)==0);
  assert(restored.image_bytes==AF_JOINT_ASSET_BYTES&&!memcmp(restored.image,expected_image,sizeof(expected_image)));
  assert(restored.report.samples==4&&restored.initial.kind==1&&restored.saved.kind==1);
  assert(restored.name_bytes==strlen(filter_name)&&!memcmp(restored.name,filter_name,restored.name_bytes));
  assert(af_import_asset(&restored,&restored_asset)==0&&restored_asset.model_sha256[0]==0x20);
 }
'''


def replace_once(text, before, after):
    assert text.count(before) == 1, '既有服务测试入口变化，需要重新核对集成边界'
    return text.replace(before, after)


@pytest.fixture(scope='module')
def driver(tmp_path_factory):
    folder = tmp_path_factory.mktemp('repository-basis-integration')
    source, binary = folder / 'driver.c', folder / 'driver'
    extra = replace_once(EXTRA, 'static void configure(void){',
                         CHECKED_MODEL + '\nstatic void configure(void){')
    extra = replace_once(extra, 'service_model.predict=af_joint_synthetic_predict;',
                         'service_model.predict=basis_checked_predict;')
    extra = replace_once(extra, 'assert(argc==3);int fd=',
                         'uint8_t expected_image[AF_JOINT_ASSET_BYTES]={0};\n assert(argc==3);int fd=')
    extra = replace_once(extra,
        'assert(af_repository_service_close(s)==0);assert(unlinkat(fd,file_name,0)==0);',
        'if(argv[2][0]==\'s\')memcpy(expected_image,candidate.image,sizeof(expected_image));\n '
        'assert(af_repository_service_close(s)==0);assert(unlinkat(fd,file_name,0)==0);\n '
        'assert(faccessat(fd,file_name,F_OK,0)<0);\n '
        'memset(&service_model,0,sizeof(service_model));memset(&candidate,0,sizeof(candidate));\n '
        'memset(&import_work,0,sizeof(import_work));memset(&parameters,0,sizeof(parameters));\n '
        'memset(input_source,0,sizeof(input_source));af_labels_init(&labels);')
    extra = replace_once(extra, 'assert(af_repository_service_close(s)==0&&close(fd)==0);return 0;',
                         RECOVERED_EXPORT + '\n assert(af_repository_service_close(s)==0&&close(fd)==0);return 0;')
    source.write_text(HARNESS.split('int main(int argc,char **argv)')[0] + extra)
    names = ('af_repository.c', 'af_repository_service.c', 'af_repository_import.c',
             'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c',
             'af_ap_manage.c', 'af_persist.c', 'af_store.c', 'af_document.c',
             'af_record.c', 'af_sha256.c', 'af_slots.c', 'af_ui.c', 'af_import.c',
             'af_joint.c', 'af_joint_fit.c', 'af_joint_basis.c', 'af_joint_asset.c',
             'af_joint_report.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c')
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-function', '-DAF_JOINT_BASIS406', '-I' + str(NATIVE), str(source),
        *[str(NATIVE / name) for name in names],
        str(NATIVE.parent / 'tests/native_joint_target.c'), '-o', str(binary)],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return binary


@pytest.mark.parametrize('case', ['success', 'cancel', 'hash-changed'])
def test_chinese_cube_basis_import_is_durable_or_leaves_no_slot(driver, tmp_path, case):
    run = subprocess.run([str(driver), str(tmp_path), case], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert not (tmp_path / '暖光.cube').exists()
    if case == 'success':
        assert (tmp_path / 'recovered' / 'C07_G0000000000000001.a7filter').is_file()
    else:
        assert not list((tmp_path / 'A7LOOKS1').glob('C07_*.rec'))
        assert not (tmp_path / 'recovered').exists()
