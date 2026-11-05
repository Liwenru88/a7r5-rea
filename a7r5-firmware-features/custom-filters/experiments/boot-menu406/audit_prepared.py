"""补充验证完整AFD1/AJR2文件经原菜单导入；与先前140帧回执分开冻结。"""
import json
from pathlib import Path

from audit_storage import BASE, ROOT, WORK, records, run_check, sha


def main():
    out = BASE/'boot-menu51-final/full-prepared'
    assert not out.exists()
    out.mkdir()
    prior = json.loads((BASE/'boot-menu51-final/verification.json').read_text())
    assert prior['status'] == 'PASS_QEMU_CHINESE_DUAL_IMPORT_SAVE_AND_INDEPENDENT_RECOVERY'
    run = BASE/'boot-menu51-full-prepared/execution/runs/native-boot-menu406-wpfxevkr'
    receipt = run_check(run)
    imported = records(run, 26, out/'records')
    before = prior['records']
    assert set(imported['files']) == set(before['files']) | {'C09_A.rec'}
    assert imported['absent'] == [name for name in before['absent'] if name != 'C09_A.rec']
    for name, value in before['files'].items():
        assert imported['files'][name] == value
    value = imported['files']['C09_A.rec']
    assert value['generation'] == 1 and value['converter'] == 2 and value['image_bytes'] == 1943
    assert value['initial']['kind'] == value['saved']['kind'] == 1
    source = WORK/'store-export-025/C07_A.rec'
    assert (out/'records/C09_A.rec').read_bytes()[32:] == source.read_bytes()[32:]
    manifest_path = BASE/'boot-menu51-full-prepared/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['prepared_record_sha256'] == sha(source)
    assert manifest['restore_records'] and manifest['software_storage'] and manifest['chinese']
    result = dict(status='PASS_FULL_AFD1_AJR2_NATIVE_MENU_IMPORT_SOFTWARE_ONLY', run=receipt,
                  prior_verification_sha256=sha(BASE/'boot-menu51-final/verification.json'),
                  manifest_sha256=sha(manifest_path), source_record_sha256=sha(source),
                  imported_record=value, AFD1_document_bytes_identical=True,
                  camera_io=False, actual_SD_Fsys_verified=False, actual_CP_peer=False,
                  CP_hardware_emulated=False, EVF_JPG_pixels_verified=False,
                  desktop_optimizer_accuracy_verified=False,
                  source_sha256={str(Path(__file__).relative_to(ROOT)):sha(Path(__file__)),
                                 str(Path(__file__).with_name('build.py').relative_to(ROOT)):sha(Path(__file__).with_name('build.py'))})
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(out/'verification.json')


if __name__ == '__main__':
    main()
