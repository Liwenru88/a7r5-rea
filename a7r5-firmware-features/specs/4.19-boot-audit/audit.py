"""只读检查既有包的启动相关资源；不打包、不访问设备、不修改候选。"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
import zlib

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[3]
FEATURES = ROOT / 'a7r5-firmware-features'
sys.path.insert(0, str(FEATURES))
from core.plan import make_plan


def sha(data):
    return hashlib.sha256(data).hexdigest()


def facts(path):
    h, crc, size = hashlib.sha256(), 0, 0
    with path.open('rb') as stream:
        while block := stream.read(4 << 20):
            h.update(block)
            crc = zlib.crc32(block, crc)
            size += len(block)
    return dict(bytes=size, sha256=h.hexdigest(), crc32=f'{crc:08x}')


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def elf_loads(raw):
    elf = ELFFile(io.BytesIO(raw))
    loads = [dict(offset=s['p_offset'], va=s['p_vaddr'], filesz=s['p_filesz'],
                  memsz=s['p_memsz'], flags=s['p_flags'], align=s['p_align'])
             for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    for seg in loads:
        assert seg['filesz'] <= seg['memsz']
        assert seg['offset'] + seg['filesz'] <= len(raw)
        if seg['align'] > 1:
            assert (seg['va'] - seg['offset']) % seg['align'] == 0
    for left, right in zip(sorted(loads, key=lambda s: s['va']),
                           sorted(loads, key=lambda s: s['va'])[1:]):
        assert left['va'] + left['memsz'] <= right['va']
    return loads


def main():
    output = Path(sys.argv[1]).resolve()
    assert output.is_relative_to(ROOT / '.local') and not output.exists()
    output.mkdir()
    bundle = FEATURES / 'releases/4.19-full'
    readback = ROOT / '.local/full419-readback-v2'
    stock = ROOT / 'a7r5-fastboot/private/cases/4.18-incident/stock'
    lock = json.loads((bundle / 'lock.json').read_text())
    manifest = json.loads((readback / 'manifest.json').read_text())
    original = json.loads((stock / 'manifest.json').read_text())
    dat = facts(bundle / 'BODYDATA.DAT')
    assert dat == lock['dat'] == manifest['source']
    assert original['source'] == lock['plan']['base']['dat']
    report = dict(schema='r5-offline-boot-audit/1', dat=dat, camera_io=False,
                  production_files_modified=False, device_boot_verified=False)

    changed, order = [], {}
    for index, (before, after) in enumerate(zip(original['entries'], manifest['entries'], strict=True), 1):
        assert before['name'] == after['name']
        order[after['name']] = index
        assert {k: v for k, v in before.items() if k not in ('sha256', 'crc32')} == {
            k: v for k, v in after.items() if k not in ('sha256', 'crc32')}
        if 'sha256' in after:
            actual = facts(readback / 'archive' / after['name'])
            assert actual == dict(bytes=after['size'], sha256=after['sha256'], crc32=after['crc32'])
            if before['sha256'] != after['sha256']:
                changed.append(after['name'])
    assert set(changed) == set(lock['expected']['archive'])
    report['archive'] = dict(entries=len(order), changed=changed,
                            all_payload_hashes_checked=True, original_order_and_metadata_preserved=True)
    partitions, pending = {}, None
    table = (readback / 'archive/0300_partconf/partinf.conf').read_bytes().decode('latin1')
    for line in table.splitlines():
        match = re.match(r'# /dev/(nflasha\d+)\s', line)
        if match:
            pending = match[1]
        elif pending and line.startswith('0x'):
            start, size, *_ = (int(item, 16) for item in line.split(','))
            partitions[pending] = dict(start=start * 512, capacity=size * 512)
            pending = None
    report['partition_bounds'] = {}
    for name, pin in partitions.items():
        image = readback / 'archive/0700_part_image/dev' / name
        if image.is_file():
            size = image.stat().st_size
            assert size <= pin['capacity']
            report['partition_bounds'][name] = dict(**pin, payload_bytes=size)

    name = '0700_part_image/dev/nflasha5'
    target, source = readback / 'archive' / name, stock / 'archive' / name
    with target.open('rb') as new, source.open('rb') as old:
        old_header, new_header = old.read(512), new.read(512)
        assert old_header.startswith(b'WBI2') and new_header == bytes(512)
        while block := old.read(4 << 20):
            assert new.read(len(block)) == block
        assert not new.read(1)
    wbi_facts = facts(target)
    crc_line = next(line for line in (readback / 'archive/0701_part_image_sum/part_image.sum').read_text().splitlines()
                    if ',dev/nflasha5,' in line)
    fields = crc_line.split(',')
    assert fields[1] == wbi_facts['crc32'] and int(fields[2], 16) == wbi_facts['bytes']
    report['wbi'] = dict(**wbi_facts, first_512_zero=True, tail_exact_to_stock=True,
                         stock_magic=old_header[:4].decode(), partition_bytes=partitions['nflasha5']['capacity'],
                         crc_record=crc_line, order={key: order[key] for key in (
                             '0301_partconf_sum/partconf.sum', name,
                             '0701_part_image_sum/part_image.sum', '0751_nor_loader_sum/nor_loader.sum')})
    assert report['wbi']['bytes'] < report['wbi']['partition_bytes']
    fs = load(ROOT / 'a7r5-updater-trust/src/filesystems.py')
    updater = (readback / 'format/updater.bin').read_bytes()
    assert sha(updater) == manifest['updater_sha256'] == original['updater_sha256']
    squash = fs.SquashImage(updater)
    extracted = {}
    for path in ('/bin/nor_loader_writer.sh', '/bin/us_mkfs.sh', '/bin/endupdate.sh',
                 '/bin/us_crc32sum.sh', '/bin/ud_wbi_drop.elf', '/bin/uc_crc32sum.elf',
                 '/bodylib/libupdaterbody.so', '/config/config.xml'):
        raw = squash.read(path)
        dst = output / 'updater' / path.lstrip('/')
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(raw)
        extracted[path] = sha(raw)
        previous = ROOT / 'a7r5-fastboot/private/cases/4.18-incident/wbi-order/updater' / path.lstrip('/')
        assert previous.read_bytes() == raw
    conf = ET.fromstring(squash.read('/config/config.xml'))
    for key in ('partconf_sum/partconf.sum', 'part_image_sum/part_image.sum', 'nor_loader_sum/nor_loader.sum'):
        for shell in conf.findall(f'.//proc[@key="{key}"]/shell'):
            assert shell.get('thread') is None
    report['updater'] = dict(sha256=sha(updater), unchanged_from_stock=True,
                             relevant_members=extracted, relevant_steps_synchronous=True)

    # 只执行抽出的两个函数；写入命令由本进程内的无设备替身提供。
    nor = squash.read('/bin/nor_loader_writer.sh').decode()
    functions = nor[nor.index('write_flash()'):nor.index('load_cp_updater()')]
    assert '/dev/' not in functions
    failures = []
    for erase, write in ((7, 0), (0, 7), (7, 7)):
        script = f'''CPFIRMUP_COMMAND=cp_stub
OSPI_ERASE_SECTOR=2
cp_stub() {{
  printf 'stub %s\\n' "$*"
  if [ "$1" = "-e" ]; then return {erase}; fi
  return {write}
}}
{functions}
erase_write_flash test-fixture.bin 2097152 17617008 -f 3
printf 'erase_write_status=%s\\n' "$?"
write_flash test-fixture.bin 2097152 -f
printf 'write_status=%s\\n' "$?"
'''
        result = subprocess.run(['/bin/sh'], input=script, text=True, capture_output=True, check=True)
        assert 'erase_write_status=0' in result.stdout and 'write_status=0' in result.stdout
        failures.append(dict(erase_exit=erase, write_exit=write, outer_exit=result.returncode, stdout=result.stdout))
    report['nor_failure_injection'] = failures
    report['nor_failure_masking_reproduced'] = True

    replay = load(ROOT / 'a7r5-fastboot/private/cases/4.18-incident/wbi-order/replay.py')
    cleared, ok = replay.wbi_drop(old_header, 512)
    assert ok and cleared == bytes(512)
    final = replay.extract_image(cleared, new_header)
    assert final == bytes(512)
    short, short_ok = replay.wbi_drop(old_header, 0)
    assert short_ok and short == old_header
    overwritten = replay.extract_image(short, new_header)
    assert overwritten == bytes(512)
    assert replay.crc_reader(new_header) == zlib.crc32(new_header)
    assert replay.crc_reader(old_header) != replay.crc_reader(new_header)
    assert replay.crc_reader(new_header, short_read=True) is None
    report['wbi_native_instruction_replay'] = dict(final_header_zero=True,
        initial_drop_short_write_reports_success=True, later_write_replaces_stale_header=True,
        stale_header_crc_differs=True, crc_short_read_rejected=True, full_update_executed=False)

    cp = (readback / 'components/cpapp-b.bin').read_bytes()
    assert sha(cp) == lock['expected']['components']['cpapp-b.bin']['sha256']
    bss = struct.unpack_from('<3I', cp, 0x20148)
    # 描述符顺序为装载地址、长度、运行地址；页表跟随运行区末尾。
    root = (bss[2] + bss[1] + 0x4fff) & ~0x3fff
    assert root == 0x1a3c000
    report['cp'] = dict(bytes=len(cp), sha256=sha(cp), bss=bss,
                      page_table_root_derived_from_boot_descriptor=hex(root),
                      pointer_in_file_before_boot=hex(struct.unpack_from('<I', cp, 0x108f1c - 0x108000)[0]))
    report['ELF'] = {}
    for label, raw in (
        ('packaged_AP', (readback / 'components/usr/lib/appFw.so').read_bytes()),
        ('latest_repaired_AP', (ROOT / '.local/operation-fixes-20261111-01/combined-components/appFw.so').read_bytes()),
        ('MPR', (ROOT / '.local/full419-candidate-v2/build-evidence/capture/libmpr.so').read_bytes())):
        report['ELF'][label] = dict(sha256=sha(raw), loads=elf_loads(raw))
    fat = fs.FatImage((readback / 'archive/0700_part_image/dev/nflasha3').read_bytes())
    entry = fat.entries['/av-cam.bin']
    capacity = sum(size for _, size in entry['extents'])
    report['avcam'] = dict(bytes=entry['size'], allocated_bytes=capacity,
                           spare_bytes=capacity-entry['size'], sha256=sha(fat.read('/AV-CAM.BIN')))
    assert report['avcam']['spare_bytes'] >= 0
    plans = {}
    for name in ('look24', 'look-fl2-fl3', 'look-factory-six', 'photo-electronic-shutter-sound',
                 'video-ntsc-prompt', 'photo-framing-markers', 'photo-aspect-ratios', 'lens-af-compat'):
        plan = make_plan(dict(base='ilce-7rm5-4.00', modules=[name]))
        plans[name] = dict(archive_targets=plan['archive_targets'],
                          wbi_invalidated='0700_part_image/dev/nflasha5' in plan['archive_targets'])
    report['single_module_wbi_policy'] = plans
    report['status'] = 'AUDITED_WITH_CONFIRMED_NOR_ERROR_MASKING_AND_SINGLE_MODULE_WBI_GAP'
    (output / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ('status', 'dat', 'wbi', 'cp', 'avcam')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
