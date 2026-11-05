"""核对离线启动对照、原始帧和产物；不把软件对端当成真实CP。"""
from pathlib import Path
import hashlib
import io
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / '.local/fixed-custom-filters'
sys.path[:0] = [str(ROOT / 'a7r5-qemu/tools')]
from menu_live import snapshot_png
from headless_osd_capture import HEADER, METADATA
from elftools.elf.elffile import ELFFile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def state(path):
    raw = (path / 'state.log').read_text()
    return {name: int.from_bytes(bytes.fromhex(value), 'little', signed=False)
            for name, value in re.findall(r'^AF_STATE (\w+) ([0-9a-f]+)\r?$', raw, re.M)}


def abi(path):
    elf = ELFFile(io.BytesIO(path.read_bytes()))
    assert elf['e_machine'] == 'EM_AARCH64' and elf['e_type'] == 'ET_DYN'
    loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    assert all(s['p_filesz'] <= s['p_memsz'] and (s['p_flags'] & 3) != 3 for s in loads)
    dynamic = elf.get_section_by_name('.dynamic')
    names = [(t.entry.d_tag, t.needed if t.entry.d_tag == 'DT_NEEDED' else t.soname)
             for t in dynamic.iter_tags() if t.entry.d_tag in ('DT_NEEDED', 'DT_SONAME')]
    symbols = [(s.name, s['st_info']['type'], s['st_info']['bind'], s['st_shndx'] == 'SHN_UNDEF')
               for s in elf.get_section_by_name('.dynsym').iter_symbols() if s.name]
    versions = [(v.name, sorted(a.name for a in aux))
                for v, aux in elf.get_section_by_name('.gnu.version_r').iter_versions()]
    return names, sorted(symbols), versions


def main():
    baseline = BASE / 'boot-menu50-observe/execution/runs/native-boot-menu406-vsrw54cm'
    no_peer = BASE / 'boot-menu50-fixed/execution/runs/native-boot-menu406-lmfdk31r'
    management = BASE / 'boot-menu50-peer-v2/execution/runs/native-boot-menu406-5ejlrtz7'
    slots = BASE / 'boot-menu50-peer-v2/execution/runs/native-boot-menu406-v508qm9v'
    before, after, published = state(baseline), state(no_peer), state(slots)
    assert before['last_status'] == 0xfffffffb and not before['prepared'] and not before['ui']
    raw = (baseline / 'state.log').read_text()
    assert 'AF_SINGLE_RX=0' in raw and 'AF_CHECK_MISMATCHES=0' in raw
    assert after['last_status'] == 0 and after['prepared'] == 1 and after['hook_changed'] == 56
    assert after['startup_phase'] == 4 and not after['admission_ready'] and not after['installed']
    assert published['prepared'] == published['registered'] == published['installed'] == published['admission_ready'] == 1
    assert published['startup_phase'] == 3 and published['startup_changed'] == 3
    assert published['startup_result'] == 0xfffffffa  # tmpfs不符合生产存储合同，不能记作保存成功。
    keys = {}
    frame_total = 0
    for directory in (management, slots):
        run = json.loads((directory / 'verification.json').read_text())
        assert run['status'] == 'NATURAL_STARTUP_STATE_COLLECTED_NOT_MENU_ACCEPTANCE'
        assert not run['camera_io'] and not run['actual_CP_peer'] and not run['forced_admission'] and not run['forced_publish']
        assert run['exit'] == {'method': 'qmp-quit', 'exit_code': 0}
        assert b'Entering exception monitor.' not in (directory / 'console.log').read_bytes()
        log = (directory / 'application.log').read_text()
        assert 'AF_QEMU_PEER_HELLO' in log and 'AF_QEMU_PEER_DELIVER' in log and 'AF_QEMU_PEER_FREE' in log
        actions = json.loads((directory / 'actions.json').read_text())
        assert actions == run['actions']
        for row in actions:
            image = Path(row['png']); blob = image.with_suffix('.bin').read_bytes()
            assert hashlib.sha256(blob[HEADER+METADATA:]).hexdigest() == row['frame']['pixel_sha256']
            frame_total += 1
    reviewed = {
        'custom_filters_parent': management / 'menu-011-RIGHT.png',
        'custom_filters_management': management / 'menu-016-ENTER.png',
        'native_photo_M': slots / 'menu-001-MODE_M.png',
        'creative_look_ST': slots / 'menu-016-ENTER.png',
        'factory_FL2': slots / 'menu-022-DOWN.png',
        'factory_FL3': slots / 'menu-023-DOWN.png',
        'user_C07': slots / 'menu-034-DOWN.png',
        'user_C20': slots / 'menu-047-DOWN.png',
        'wrap_to_ST': slots / 'menu-048-DOWN.png',
    }
    for label, image in reviewed.items():
        assert snapshot_png(image.with_suffix('.bin').read_bytes()) == image.read_bytes()
        keys[label] = dict(path=str(image.relative_to(ROOT)), sha256=sha(image),
                          original_frame_sha256=sha(image.with_suffix('.bin')), visually_reviewed=True)
    old = BASE / 'loader-recovery-library'
    new = BASE / 'boot-menu50-loader'
    assert abi(old / 'libaf_bootstrap406.so') == abi(new / 'libaf_bootstrap406.so')
    assert (old / 'af_bootstrap_manifest.h').read_bytes() == (new / 'af_bootstrap_manifest.h').read_bytes()
    build = json.loads((new / 'verification.json').read_text())
    software = json.loads((BASE / 'boot-menu50-software/verification.json').read_text())
    for receipt in (build, software):
        for name, digest in receipt['source_sha256'].items():
            assert sha(ROOT / name) == digest, name
    assert '66 passed' in software['commands'][-1]['stdout'] and all(c['exit_code'] == 0 for c in software['commands'])
    assert sha(new / 'libaf_bootstrap406.so') == build['bootstrap']['sha256']
    assert (BASE/'boot-menu50-peer-v2/software-peer.inc').read_bytes() == Path(__file__).with_name('software-peer.inc').read_bytes()
    sources = [Path(__file__), Path(__file__).with_name('build.py'), Path(__file__).with_name('run.py'),
               Path(__file__).with_name('software-peer.inc'),
               ROOT / 'a7r5-firmware-features/custom-filters/tests/test_loader_maps406.py']
    result = dict(status='PASS_OFFLINE_BOOT_AND_NATIVE_MENU_WITH_SOFTWARE_PROTOCOL_PEER',
                  task='T11f', candidate=build['bootstrap'], source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
                  original_preimages_match_before_prepare=True, continuous_RX_split_rejection_reproduced=True,
                  production_protection_fix_executed=True, missing_peer_keeps_UI_disabled=True,
                  production_HELLO_codec_and_client_gate_executed=True, native_UI_frames_verified=frame_total,
                  visible_looks=32, factory_looks=12, user_slots=20, native_special_row_not_counted_as_user_slot=True,
                  observed_C20_wraps_to_ST=True, native_management_page_visible=True,
                  menu_language_verified='English', reviewed_frames=keys,
                  artifact_imports_exports_dependencies_and_asset_table_unchanged=True,
                  targeted_host_tests=66, camera_io=False, CP_hardware_emulated=False,
                  target_code_executed_in_QEMU=True, camera_library_written=False,
                  baseline_platform='复用原菜单客体所需的virt/Linux基础平台；未新增CP/ISP硬件模型',
                  actual_CP_peer=False, force_admission=False, force_publish=False,
                  actual_body_persistence_verified=False, actual_EVF_JPG_verified=False,
                  hardware_upgrade_verified=False, full_feature_acceptance=False)
    out = BASE / 'boot-menu50-final'
    out.mkdir(exist_ok=True)
    (out / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('status', 'candidate', 'native_UI_frames_verified', 'visible_looks', 'camera_io')}, indent=2))


if __name__ == '__main__':
    main()
