"""核对第51批实际菜单、虚拟VFAT记录与独立启动恢复；不授予设备／成像资格。"""
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT/'.local/fixed-custom-filters'
sys.path[:0] = [str(ROOT/'a7r5-qemu/tools')]
from menu_live import clean_console, snapshot_png
from headless_osd_capture import HEADER, METADATA
from store_records import export, validate

WORK = BASE/'boot-menu51-workflow-v2/execution/runs/native-boot-menu406-kugv5ljt'
RECOVER = BASE/'boot-menu51-final-recovery/execution/runs/native-boot-menu406-zdhnoy02'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def records(run, index, out):
    raw = (run/f'store-export-{index:03d}.log').read_bytes()
    assert b'AF_STORE_RC=0' in raw
    checked = export(clean_console(raw).decode('utf-8'), out)
    saved = run/f'store-export-{index:03d}'
    assert checked == json.loads((saved/'records.json').read_text())
    for name, row in checked['files'].items():
        assert validate(name, (saved/name).read_bytes()) == row
        assert (saved/name).read_bytes() == (out/name).read_bytes()
    return checked


def run_check(run):
    receipt = json.loads((run/'verification.json').read_text())
    assert receipt['status'] == 'NATURAL_STARTUP_STATE_COLLECTED_NOT_MENU_ACCEPTANCE'
    assert receipt['exit'] == {'method': 'qmp-quit', 'exit_code': 0}
    for key in ('camera_io','CP_hardware_emulated','actual_CP_peer','forced_admission','forced_publish'):
        assert receipt[key] is False
    state = {name: int.from_bytes(bytes.fromhex(raw), 'little') for name, raw in
             re.findall(r'^AF_STATE (\w+) ([0-9a-f]+)\r?$', (run/'state.log').read_text(), re.M)}
    assert all(state[key] == 1 for key in ('prepared','registered','installed','admission_ready'))
    assert state['startup_phase'] == 3
    assert all(state[key] == 0 for key in ('startup_result','native_media_result','reference_import_result'))
    log = (run/'console.log').read_bytes()
    assert b'Entering exception monitor.' not in log and b'Exception>' not in log
    assert b'AF_QEMU_CHINESE_APPLIED model=25' in log
    assert b'AF_QEMU_PEER_HELLO' in log and b'AF_QEMU_PEER_DELIVER' in log
    actions = json.loads((run/'actions.json').read_text())
    assert actions == receipt['actions']
    for row in actions:
        png = Path(row['png']);raw = png.with_suffix('.bin').read_bytes()
        assert hashlib.sha256(raw[HEADER+METADATA:]).hexdigest() == row['frame']['pixel_sha256']
        assert snapshot_png(raw) == png.read_bytes()
    return dict(path=str(run.relative_to(ROOT)), actions=len(actions), exit=receipt['exit'],
                verification_sha256=sha(run/'verification.json'))


def main():
    out = BASE/'boot-menu51-final'
    assert not out.exists()
    out.mkdir()
    runs = [run_check(run) for run in (WORK, RECOVER)]
    baseline = records(WORK, 44, out/'records-imported')
    cancelled = records(WORK, 50, out/'records-cancelled')
    dirty = records(WORK, 81, out/'records-dirty')
    saved = records(WORK, 83, out/'records-saved')
    copied = records(WORK, 87, out/'records-copied')
    recovered = records(RECOVER, 1, out/'records-recovered')
    assert baseline == cancelled == dirty  # 取消和临时调参都没有隐式写盘。
    assert copied == recovered  # 全部原字节、缺失银行和两种载荷均独立恢复。
    old = baseline['files']['C20_A.rec']
    new = saved['files']['C20_B.rec']
    assert old['initial']['parameters'] == old['saved']['parameters'] == [1,2,0,0,0,4,3,1]
    assert new['initial'] == old['initial'] and new['generation'] == 2
    expected = [2,3,1,1,1,5,4,2]
    assert new['saved']['parameters'] == expected
    assert copied['files']['C08_A.rec']['saved']['parameters'] == expected
    assert copied['files']['C08_A.rec']['name'] == '自定义C08'
    cube = copied['files']['C07_A.rec']
    assert cube['name'] == '01_照片基准' and cube['converter'] == 2 and cube['image_bytes'] == 1943
    assert cube['saved']['kind'] == 1 and cube['generation'] == 1
    source = b'LUT_3D_SIZE 2\n'+''.join(f'{r} {g} {b}\n' for b in range(2) for g in range(2) for r in range(2)).encode()
    assert cube['saved']['lut_sha256'] == hashlib.sha256(source).hexdigest()
    mounts = (RECOVER/'state-000.log').read_text()
    assert re.search(r'^/dev/nflasha2 /setting vfat rw,', mounts, re.M)
    assert 'fmask=0177' in mounts and 'dmask=0077' in mounts
    manifests = []
    for name in ('boot-menu51-workflow-v2','boot-menu51-final-recovery'):
        directory = BASE/name
        manifest = json.loads((directory/'manifest.json').read_text())
        assert manifest['chinese'] and manifest['software_storage'] and manifest['software_protocol_peer']
        assert manifest['unrelated_original_entries_identical']
        assert not manifest['camera_io'] and not manifest['CP_hardware_emulated']
        assert manifest['loader_sha256'] == sha(directory/'libaf_bootstrap-qemu.so')
        assert manifest['product_loader_sha256'] == sha(BASE/'boot-menu50-loader/libaf_bootstrap406.so')
        assert manifest['loader_sha256'] != manifest['product_loader_sha256']
        for inc in ('software-peer.inc','qemu-storage.inc','chinese-ui.inc'):
            assert (directory/inc).read_bytes() == Path(__file__).with_name(inc).read_bytes()
        manifests.append(dict(path=str((directory/'manifest.json').relative_to(ROOT)), sha256=sha(directory/'manifest.json')))
    result = dict(status='PASS_QEMU_CHINESE_DUAL_IMPORT_SAVE_AND_INDEPENDENT_RECOVERY',
                  runs=runs, manifests=manifests, frame_count=sum(row['actions'] for row in runs),
                  camera_io=False, CP_hardware_emulated=False, actual_CP_peer=False,
                  actual_SD_Fsys_verified=False, device_durability_verified=False,
                  EVF_JPG_pixels_verified=False, full_feature_verified=False,
                  records=copied, temporary_edits_do_not_persist=True, cancel_does_not_persist=True,
                  explicit_save_preserves_initial=True, all_eight_parameters_restored=True,
                  software_adapters='实验SD目录端口／协议对端；真实Linux VFAT及生产保存代码',
                  source_sha256={str(p.relative_to(ROOT)):sha(p) for p in Path(__file__).parent.iterdir() if p.is_file() and p.suffix in ('.py','.c','.inc','.md')})
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(out/'verification.json')


if __name__ == '__main__':
    main()
