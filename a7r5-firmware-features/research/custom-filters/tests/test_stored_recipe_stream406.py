"""真实默认转换/文件保存→UI回调→AP28帧→Rx校验；系统消息为宿主端口，非成像验收。"""
from pathlib import Path
import subprocess

import pytest

from test_ap_recipe_sender import HARNESS as AP_HARNESS
from test_edit_joint import SOURCES
from test_native_repository import HARNESS as REPOSITORY_HARNESS
from test_reference_default_import import EXTRA as DEFAULT_IMPORT

HOME = Path(__file__).resolve().parents[1]

STREAM = r'''
#include "af_imaging406.h"
int af_ap_factory406_snapshot(uintptr_t base,uint32_t selector,AfPreset *out){
 (void)base;*out=(AfPreset){.base=(uint8_t)selector,.params={0,0,0,0,0,0,3,0}};return AF_OK;
}
static void stream_saved(void *service){
 AfPreset expected=catalog.slots[6].working;
 AfRecipeTx captured,before;memset(&captured,0xa5,sizeof captured);before=captured;
 AfPreset stale=expected;stale.params[0]=stale.params[0]==9?8:9;
 assert(af_repository_service_recipe_capture(service,7,&stale,71,1,&captured)==AF_STALE);
 assert(!memcmp(&captured,&before,sizeof captured));
 assert(af_repository_service_recipe_capture(service,7,&expected,71,1,&captured)==AF_OK);
 assert(!memcmp(&captured.message.preset,&expected,sizeof expected)&&captured.message.image[3]=='2');
 assert(af_repository_service_recipe_capture(service,7,&captured.message.preset,71,1,&captured)==AF_INVALID);
 connect(AF_APPLY_PROTOCOL_REQUIRED);assert(!af_recipe_rx_init(&receiver,71,AF_RECIPE_CAP_FULL));
 AfApImagingBinding binding;assert(!af_imaging406_binding(0x7000000000u,&binding));
 assert(!(binding.capabilities(binding.context)&AF_APPLY_CAP_FULL_RECIPE));
 assert(binding.send(binding.context,7,&expected)==AF_INVALID&&!allocations);
 AfImaging406RecipeSource source={1,sizeof(source),service,af_repository_service_recipe_capture};
 assert(!af_imaging406_bind_recipe_source(&source)&&af_imaging406_bind_recipe_source(&source)==AF_BUSY);
 assert(binding.capabilities(binding.context)&AF_APPLY_CAP_FULL_RECIPE);
 assert(!binding.send(binding.context,7,&expected)&&frames==28&&seen==1);
 AfRecipeAck ack;assert(af_ap_runtime_recipe_result(&ack)==AF_BUSY);
 assert(af_ap_runtime_reply(acknowledgment,0x90030001u,128)==1&&!af_ap_runtime_recipe_result(&ack));
 assert(ack.status==AF_OK&&ack.version==1&&ack.slot==7);
 assert(receiver.buffers[receiver.active].asset.native_mode==1);
 assert(!memcmp(receiver.buffers[receiver.active].message.image,captured.message.image,AF_JOINT_ASSET_BYTES));
 /* 预览临时调参仍取保存的同一LUT，仅八项值变化，不隐式保存。 */
 int value=expected.params[0]==9?8:9;assert(!af_edit(&catalog,7,0,value));
 expected=catalog.slots[6].working;assert(af_dirty(&catalog,7)==1);
 assert(!binding.send(binding.context,7,&expected)&&frames==56&&seen==2);
 assert(af_ap_runtime_reply(acknowledgment,0x90030001u,128)==1&&!af_ap_runtime_recipe_result(&ack)&&ack.version==2);
 assert(receiver.buffers[receiver.active].message.preset.params[0]==value);
 assert(!memcmp(receiver.buffers[receiver.active].message.image,captured.message.image,AF_JOINT_ASSET_BYTES));
 assert(catalog.slots[6].saved_revision==1&&af_dirty(&catalog,7)==1);
}
'''


@pytest.mark.parametrize('slot', [1, 7], ids=['explicit-first-six-overlay', 'new-user-slot'])
def test_default_saved_lut_uses_real_sender_session_and_keeps_dirty_values(tmp_path, slot):
    prefix = REPOSITORY_HARNESS.split('int main(int argc,char **argv)')[0]
    sender = AP_HARNESS.split('int main(int argc,char **argv)')[0]
    point = ' assert(af_repository_service_close(service)==0);'
    assert DEFAULT_IMPORT.count(point) == 2
    main = DEFAULT_IMPORT.replace(point, ' stream_saved(service);\n' + point, 1)
    stream = STREAM
    if slot == 1:
        main = main.replace('q.target_slot=7;', 'q.target_slot=1;q.overwrite=1;')
        main = main.replace('catalog.slots[6]', 'catalog.slots[0]')
        stream = stream.replace('catalog.slots[6]', 'catalog.slots[0]')
        stream = stream.replace('service,7,', 'service,1,')
        stream = stream.replace('binding.context,7,', 'binding.context,1,')
        stream = stream.replace('af_edit(&catalog,7,', 'af_edit(&catalog,1,')
        stream = stream.replace('af_dirty(&catalog,7)', 'af_dirty(&catalog,1)')
        stream = stream.replace('ack.slot==7', 'ack.slot==1')
    source = tmp_path / 'stream.c'
    source.write_text(prefix + sender + stream + main)
    names = list(dict.fromkeys([*SOURCES,
        'af_repository.c', 'af_repository_service.c', 'af_repository_recipe.c', 'af_repository_import.c',
        'af_media.c', 'af_posix.c', 'af_labels.c', 'af_labels_store.c', 'af_ap_manage.c', 'af_persist.c',
        'af_store.c', 'af_document.c', 'af_record.c', 'af_slots.c', 'af_ui.c', 'af_import.c',
        'af_joint_fit.c', 'af_joint_basis.c', 'af_joint_asset.c', 'af_joint_report.c', 'af_grid.c',
        'af_grid_fit.c', 'af_cube.c', 'af_reference_joint.c', 'af_reference_domain.c',
        'af_reference_samples.c', 'af_reference_assets.c', 'af_reference_grid.c', 'af_reference_import.c',
        'af_reference_blob.S', 'af_runtime_ap406.c', 'af_runtime.c', 'af_handshake.c', 'af_apply_wire.c',
        'af_recipe_transport.c', 'af_imaging406.c']))
    binary = tmp_path / 'stream'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-function', '-DAF_JOINT_BASIS406', '-DAF_REFERENCE_IMPORT406',
        '-DAF_CP_PRESET406', '-DAF_FACTORY_RESTORE406', '-DAF_SNAPSHOT_OVERLAY406', '-DAF_RECIPE_BRIDGE406',
        '-ffp-contract=off', '-I' + str(HOME / 'native'), str(source),
        *[str(HOME / 'native' / name) for name in names], str(HOME / 'tests/native_joint_target.c'),
        '-o', str(binary)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    folder = tmp_path / 'body'
    folder.mkdir()
    run = subprocess.run([str(binary), str(folder)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert (folder / f'A7LOOKS1/C{slot:02d}_A.rec').is_file()
