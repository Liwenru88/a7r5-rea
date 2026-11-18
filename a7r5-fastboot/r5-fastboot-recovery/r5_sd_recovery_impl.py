#!/usr/bin/env python3
"""R5 adaptation of the supplied A7M4 MODE5 SD recovery trigger.

Offline preparation is the default. --execute uses the unchanged RAM entry,
reads the current body/settings/updater, writes only a checked nflasha2 sparse
overlay, verifies full logical and raw readback, then sends one normal reboot.
The camera's original updater, not this host tool, installs slot-1 BODYDATA.DAT.
"""
import argparse
from contextlib import contextmanager
import fcntl
import glob
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import zipfile

from build_r5_partition1 import FatImage, SquashImage, require
from modify_r5_slot_settings import raw_verify, save, utc
from patch_r5_slot_settings import SIZE, apply_sparse, changed_sectors, make_sparse
from sign_r5_firmware import digest_file
from fwtool.archive import fat as independent_fat

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor/fwtool.py-a7iv'))
BASE = ROOT / 'analysis/r5_sd_recovery_trigger_20261020'
HOST = ROOT / 'analysis/r5_live_system_20261014/host_tools'
BACKUP = ROOT / 'backups/R5_4.00_20261014_full'
PACKAGE = ROOT / 'build_r5_m4strict_4.06_20261020/BODYDATA.DAT'
PACKAGE_SHA = 'ced647c067bef985c5a8b23a0aaf96fa212c5007e6436e9032ca7deb944cf14e'
UPDATER_PART_SHA = '0ec7813c78f121f5abced7fc24350e34ac4cffa4ec8be4d1ecccee22f3d4922d'
INITRD_SHA = '07adc1a7d05984bc437dc9c5ef02fc0c86a31bfe5460e9300c3496b8232ddacf'
RAW_SETTINGS = 'oem partition dump nflasha 0xc000 0xa000'
PINS = {
    'tools/r5_settings_ram_boot.py': '80b79977a51bdfdfb5d8947ff92192ec04d803df3dbc2d0f79d2a634500329d8',
    'tools/modify_r5_slot_settings.py': '4670d7f15c4a85a7149f8a7edb26db7d9fd734a4c7f85b4324d8dea67252a6d8',
    'tools/patch_r5_slot_settings.py': '05b412c3b31c0bcbbda0fbf597dee31214d4d8c7ef676c3e33517883b6095790',
    'analysis/r5_verifykey_skip_flash_20261014/partition1_usb.c': 'bbf3faa3e45d04ec7f1231587721c70cbcea31f42846656d5bf21cc0fbb3b0c3',
    'analysis/r5_live_system_20261014/host_tools/configure_fastboot_usb': '6bd57af09f600593ef1e4014a6a9e19fe21a583a12c265e8b74a8ffa87008c0a',
    'analysis/r5_live_system_20261014/host_tools/read_fastboot_usb_all': '4f4156e1b02bc794791fa8c1e991ef65b38d8e6b045b1d4b74d55183558dfe7f',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode_version(raw):
    require(len(raw) == 2 and all((n >> 4) <= 9 and (n & 15) <= 9 for n in raw),
            'DAT4 is not a two-byte BCD version')
    minor, major = [(n >> 4) * 10 + (n & 15) for n in raw]
    return major * 100 + minor


def files(data):
    fs = FatImage(data)
    return {name: fs.read(name) for name, row in fs.entries.items() if not row['is_directory']}


def make_trigger(original):
    """Only DAT4's two bytes and unused directory rows for MODE/MODE5 may change."""
    require(len(original) == SIZE, 'Need a complete current 20 MiB R5 settings image')
    fs = FatImage(original)
    version = decode_version(fs.read('/updater/dat4'))
    require(version == 0 or version // 100 == 4, 'Only this R5 4.x settings profile is supported')
    directory = fs.entries['/updater']
    require(directory['is_directory'], 'UPDATER is not a directory')
    conflicts = {'/updater/' + n for n in ('mode1', 'mode2', 'mode3', 'mode4',
                                         'mode6', 'mode7', 'uincomp')}
    require(not conflicts.intersection(fs.entries), 'Conflicting updater flags: ' +
            ','.join(sorted(conflicts.intersection(fs.entries))))
    missing = []
    for name in ('mode', 'mode5'):
        path = '/updater/' + name
        if path not in fs.entries:
            missing.append(name)
        else:
            row = fs.entries[path]
            require(not row['is_directory'] and row['size'] == 0 and not row['extents'],
                    'Existing ' + name + ' is not an empty no-cluster flag')
    candidate = bytearray(original)
    allowed = fs.patch(candidate, '/updater/dat4', b'\0\0')
    created = []
    if missing:
        rows = [off for start, size in directory['extents']
                for off in range(start, start + size, 32)]
        end = next((i for i, off in enumerate(rows) if original[off] == 0), None)
        require(end is not None and end + len(missing) < len(rows),
                'No existing free UPDATER directory slots; no filesystem expansion permitted')
        slots = rows[end:end + len(missing) + 1]
        require(all(original[o:o + 32] == bytes(32) for o in slots),
                'Directory tail is not completely empty')
        dat4_row = fs.entries['/updater/dat4']['directory_entry_offset']
        for name, offset in zip(missing, slots):
            row = bytearray(32)
            row[:11] = name.upper().encode().ljust(8, b' ') + b'   '
            row[11], row[12] = 0x20, 8
            row[14:26] = original[dat4_row + 14:dat4_row + 26]
            require(row[20:22] == b'\0\0', 'FAT12 high-cluster field is not zero')
            candidate[offset:offset + 32] = row
            allowed.append((offset, 32))
            created.append('/updater/' + name)
    candidate = bytes(candidate)
    after = FatImage(candidate)
    require(after.read('/updater/mode') == after.read('/updater/mode5') == b'',
            'Trigger flags failed to parse')
    require(after.read('/updater/dat4') == b'\0\0', 'Temporary version gate differs')
    expected = files(original)
    expected['/updater/dat4'] = b'\0\0'
    expected.update({name: b'' for name in created})
    require(files(candidate) == expected, 'An unrelated file changed')
    independent = {row.path.casefold(): row.contents.read()
                   for row in independent_fat.readFat(io.BytesIO(candidate)) if stat.S_ISREG(row.mode)}
    require(independent == expected, 'Independent FAT parser disagrees with candidate files')
    require(candidate[fs.fat_start:fs.data_start] == original[fs.fat_start:fs.data_start],
            'FAT allocation or root directory changed')
    for name, entry in fs.entries.items():
        require(after.entries[name] == entry, 'Existing file metadata changed: ' + name)
    changes = [i for i in range(len(original)) if original[i] != candidate[i]]
    require(all(any(lo <= i < lo + count for lo, count in allowed) for i in changes),
            'Unexpected byte change outside trigger scope')
    require(len(changes) <= 66, 'Unexpectedly large trigger')
    sectors = changed_sectors(original, candidate)
    require(len(sectors) <= 3, 'Unexpectedly broad trigger sectors')
    return candidate, dict(current_version=f'{version // 100}.{version % 100:02d}',
                          temporary_gate='0.00', created_flags=created,
                          changed_bytes=len(changes), changed_offsets=changes,
                          changed_sectors=sectors, allowed_ranges=allowed,
                          all_existing_files_except_DAT4_preserved=True,
                          all_existing_directory_metadata_and_FAT_preserved=True,
                          independent_FAT_parser_agrees=True,
                          backup_bin_sha256=sha(fs.read('/backup.bin')),
                          backup_bak_sha256=sha(fs.read('/backup.bak')),
                          target='slot1:/BODYDATA.DAT', host_SD_content_verified=False)


def check_dependencies():
    for name, digest in PINS.items():
        require(digest_file(ROOT / name) == digest, 'Pinned dependency changed: ' + name)
    with zipfile.ZipFile(os.environ.get('A7R5_BOOTLOADER_ZIP', str(Path.home() / 'Downloads/bootloader脚本.zip'))) as z:
        for name, digest in {
            'a7m4fb.py': 'f944d89d012f356afd5fbf47b54739dc811f06b4acf6f11872a1ad7f20cc77c3',
            'bin/fastboot.bin': '330ac322bd0e40a7bb4974f69a2667e7d59a25e59c1322339690f30a3ceadbdc',
            'lib/pyserial.zip': 'd2262ca69ecfb0cb14b1c310998999692ed7ceb5cb106d2fb65fa421223264e5',
        }.items():
            require(sha(z.read('bootloader脚本/' + name)) == digest, 'RAM dependency changed: ' + name)
    return {name: digest_file(ROOT / name) for name in PINS}


def writer_source(digest):
    require(re.fullmatch('[0-9a-f]{64}', digest), 'Invalid sparse hash')
    source = (ROOT / 'analysis/r5_verifykey_skip_flash_20261014/partition1_usb.c').read_text()
    start = source.index('static int allowed(')
    end = source.index('static unsigned char staged', start)
    source = source[:start] + '''static int allowed(const char *s) {
    return !strcmp(s,"download:/PLACEHOLDER") || !strncmp(s,"download:/",10) ||
           !strcmp(s,"flash:nflasha2");
}
static int download_approved=0, write_sent=0;
''' + source[end:]
    source = source.replace('ce51008ae51696004488b02ae291b23390edcea70870d0c60280ebeccd1a53ee', digest)
    marker = 'static int command(const char *arg) {\n'
    require(source.count(marker) == 1, 'Unexpected host command structure')
    source = source.replace(marker, marker + '''    int is_flash=!strcmp(arg,"flash:nflasha2");
    if(is_flash && (!download_approved || write_sent)){fprintf(stderr,"Unarmed/repeated flash\\n");return -1;}
    download_approved=0;
    if(is_flash)write_sent=1;
''')
    marker = 'if(!memcmp(b,"OKAY",4)){if(saved_path)'
    require(source.count(marker) == 1, 'Unexpected host OKAY structure')
    source = source.replace(marker, 'if(!memcmp(b,"OKAY",4)){if(!strncmp(arg,"download:/",10)){if(downloading)return -1;download_approved=1;}if(saved_path)')
    marker = '    setbuf(stdout,NULL);\n'
    source = source.replace(marker, marker + '''    if(argc==3 && !strcmp(argv[1],"--check-download"))return load_download(argv[2])?2:0;
    if(argc!=3 || strncmp(argv[1],"download:/",10) || strcmp(argv[2],"flash:nflasha2")){
        fprintf(stderr,"Only one download plus flash:nflasha2 is permitted\\n");return 2;}
''')
    require('flash:nflasha1' not in source and 'reboot' not in source and 'erase' not in source,
            'Unexpected writer capability')
    return source


def compile_writer(folder, digest):
    source = folder / 'trigger_usb.c'
    source.write_text(writer_source(digest))
    binary = folder / 'trigger_usb'
    p = subprocess.run(['/usr/bin/clang', '-O2', '-Wno-deprecated-declarations', str(source),
                        '-o', str(binary), '-framework', 'IOKit', '-framework', 'CoreFoundation'],
                       capture_output=True, text=True, timeout=30)
    (folder / 'compile.log').write_text(p.stdout + p.stderr)
    require(p.returncode == 0, 'Writer compilation failed')
    return binary


def inspect_environment(data):
    require(sha(data) == UPDATER_PART_SHA, 'Current nflasha1 differs from this body\'s approved signature environment')
    fs = FatImage(data)
    initrd = fs.read('/boot/initrd.img')
    require(sha(initrd) == INITRD_SHA, 'Unexpected current updater initrd')
    sums = (hashlib.md5(fs.read('/boot/vmlinux.bin')).hexdigest() + '  ./boot/vmlinux.bin\n' +
            hashlib.md5(initrd).hexdigest() + '  ./boot/initrd.img\n').encode()
    require(fs.read('/p1chksum') == sums, 'Updater kernel/initrd checksums differ')
    sq = SquashImage(initrd)
    identities = {}
    for name in ('UdtrMain.sh', 'execute_ufp.sh', 'common.src'):
        path = '/usr/bin/' + name
        original = ROOT / 'analysis/r5_live_system_20261014/boot_probe_B/update_initrd' / path.lstrip('/')
        content = sq.read(path)
        require(content == original.read_bytes(), 'Updater mode script differs: ' + name)
        identities[path] = sha(content)
    require(b'test -f /setting/updater/mode5' in sq.read('/usr/bin/UdtrMain.sh') and
            b'sdfileinput.elf' in sq.read('/usr/bin/execute_ufp.sh'), 'Missing original R5 MODE5 dispatch')
    return dict(partition_sha256=sha(data), initrd_sha256=INITRD_SHA, scripts=identities,
                signature_environment_matches_previously_deployed_R5=True)


@contextmanager
def hardware_lock():
    path = BASE / '.hardware.lock'
    with path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def prepare():
    dependencies = check_dependencies()
    require(digest_file(PACKAGE) == PACKAGE_SHA, '4.06 DAT identity differs')
    folder = BASE / 'prepared'
    folder.mkdir(mode=0o700, exist_ok=False)
    source = ROOT / 'analysis/r5_405_failure_readback_20261020_F/nflasha2.logical.img'
    before = source.read_bytes()
    after, plan = make_trigger(before)
    sparse = make_sparse(before, after)
    require(apply_sparse(before, sparse)[0] == after, 'Sparse overlay differs')
    (folder / 'OFFLINE_TEST_ONLY.sparse.img').write_bytes(sparse)
    writer = compile_writer(folder, sha(sparse))
    checks = []
    for label, args, success in [
        ('valid_download', ['--check-download', str(folder / 'OFFLINE_TEST_ONLY.sparse.img')], True),
        ('unarmed_flash', ['flash:nflasha2'], False),
        ('other_partition', ['download:/unused', 'flash:nflasha15'], False),
        ('erase_blocked', ['erase:nflasha2'], False),
        ('reboot_blocked', ['reboot'], False),
    ]:
        p = subprocess.run([str(writer), *args], capture_output=True, text=True)
        require((p.returncode == 0) == success, 'Host offline check failed: ' + label)
        checks.append(dict(name=label, returncode=p.returncode, passed=True))
    bad = folder / 'tampered.sparse'
    bad.write_bytes(sparse[:-1] + bytes([sparse[-1] ^ 1]))
    p = subprocess.run([str(writer), '--check-download', str(bad)], capture_output=True, text=True)
    require(p.returncode != 0, 'Writer accepted tampered sparse data')
    checks.append(dict(name='tampered_download_rejected', returncode=p.returncode, passed=True))
    bad.unlink()
    require(make_trigger(after)[0] == after, 'Trigger is not idempotent')
    inspect_environment((ROOT / 'build_r5_partition1_verifykey_skip_20261014/nflasha1.R5_4.00.custom-key.verifykey-skip.logical.img').read_bytes())
    shutil.copyfile(Path(__file__), folder / 'executor.source.py')
    report = dict(created_utc=utc(), offline_only=True, camera_io=False, passed=True,
                  executor_sha256=digest_file(Path(__file__)), dependencies=dependencies,
                  source_settings=str(source), source_settings_sha256=sha(before), plan=plan,
                  host_checks=checks, idempotence_passed=True,
                  package=str(PACKAGE), package_sha256=PACKAGE_SHA,
                  artifacts={p.name: digest_file(p) for p in folder.iterdir() if p.is_file()},
                  limitation='Offline candidate must never be flashed; live candidate is rebuilt from a new read.')
    save(folder / 'manifest.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


def execute(port=None, already_fastboot=False):
    check_dependencies()
    manifest = json.loads((BASE / 'prepared/manifest.json').read_text())
    require(manifest['executor_sha256'] == digest_file(Path(__file__)), 'Executor changed after preparation')
    require(digest_file(PACKAGE) == PACKAGE_SHA, '4.06 package changed')
    for name, digest in manifest['artifacts'].items():
        require(digest_file(BASE / 'prepared' / name) == digest, 'Prepared artifact changed: ' + name)
    require(shutil.disk_usage(BASE).free > 300 << 20, 'Insufficient free disk space')
    from datetime import datetime, timezone
    folder = BASE / ('live_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ'))
    folder.mkdir(mode=0o700, exist_ok=False)
    shutil.copyfile(Path(__file__), folder / 'executor.source.py')
    state = dict(started_utc=utc(), stage='R5_MODE5_SD_trigger',
                 flash_attempted=False, readback_verified=False, reboot_attempted=False,
                 camera_SD_installation_completed=False,
                 user_confirmed_slot1_406_DAT_and_idle_camera=True,
                 host_can_read_camera_SD_card=False, target_package_sha256=PACKAGE_SHA)
    write_state = lambda: save(folder / 'report.json', state)
    write_state()
    index = 0

    def run(argv, label, timeout=60):
        nonlocal index
        index += 1
        path = folder / f'{index:03d}_{label}.log'
        print(label, flush=True)
        with path.open('x') as output:
            p = subprocess.run(list(map(str, argv)), stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        output = path.read_text()
        print(output[-2400:], flush=True)
        require(p.returncode == 0 and 'REPLY FAIL' not in output, label + ' failed: ' + str(p.returncode))
        return output

    def reads(args, label):
        output = run([HOST / 'read_fastboot_usb_all', *args], label)
        require(output.count('REPLY OKAY') == len(args), 'Missing acknowledgment: ' + label)
        return output

    with hardware_lock():
        try:
            if not already_fastboot:
                ports = glob.glob('/dev/cu.usbmodem*')
                if port is None:
                    require(len(ports) == 1, 'Need exactly one RP2040 serial port')
                    port = ports[0]
                run([ROOT / '.venv/bin/python', '-B', ROOT / 'tools/r5_settings_ram_boot.py',
                     '--port', port, '--output', folder / 'ram_boot'], 'original_RAM_entry', 65)
                entry = json.loads((folder / 'ram_boot/report.json').read_text())
                require(entry.get('usb_transport_verified'), 'RAM fastboot entry not verified')
                query = (folder / 'ram_boot/usb_queries.txt').read_text()
            else:
                query = reads(['oem partition'], 'existing_fastboot_geometry')
            require(re.search(r'INFOnflasha2\s+0000c000 0000a000 fat', query), 'R5 settings geometry differs')
            reads(['oem partition dump nflasha 0 0x80', 'upload:' + str(folder / 'sdm2.before.bin'),
                   'oem dumpbrom', 'upload:' + str(folder / 'ap_brom.bin'),
                   'oem partition dump nflasha1', 'upload:' + str(folder / 'nflasha1.before.img'),
                   'oem partition dump nflasha2', 'upload:' + str(folder / 'settings.before.logical.img'),
                   RAW_SETTINGS, 'upload:' + str(folder / 'settings.before.raw.img')], 'fresh_current_environment')
            require((folder / 'sdm2.before.bin').read_bytes() == (BACKUP / 'sdm2_partition_table.raw.bin').read_bytes(),
                    'Partition table differs from this R5')
            require((folder / 'ap_brom.bin').read_bytes() == (BACKUP / 'ap_bootrom.raw.A.bin').read_bytes(),
                    'Boot ROM differs from this R5')
            state['updater_environment'] = inspect_environment((folder / 'nflasha1.before.img').read_bytes())
            before = (folder / 'settings.before.logical.img').read_bytes()
            raw_before = (folder / 'settings.before.raw.img').read_bytes()
            raw_verify(raw_before, before)
            after, plan = make_trigger(before)
            sparse = make_sparse(before, after)
            require(apply_sparse(before, sparse) == (after, plan['changed_sectors']), 'Live sparse overlay differs')
            candidate = folder / 'settings.MODE5.logical.img'
            candidate.write_bytes(after)
            patch = folder / 'trigger.sparse.img'
            patch.write_bytes(sparse)
            state.update(plan=plan, full_current_settings_XTS_verified=True,
                         before_sha256=sha(before), after_sha256=sha(after), sparse_sha256=sha(sparse))
            write_state()
            writer = compile_writer(folder, sha(sparse))
            reads(['oem partition dump nflasha2', 'upload:' + str(folder / 'settings.prewrite.logical.img'),
                   'oem partition dump nflasha 0 0x80', 'upload:' + str(folder / 'sdm2.prewrite.bin')],
                  'immediate_prewrite_check')
            require((folder / 'settings.prewrite.logical.img').read_bytes() == before and
                    (folder / 'sdm2.prewrite.bin').read_bytes() == (folder / 'sdm2.before.bin').read_bytes(),
                    'Current settings/device state changed; stop before writing')
            require(candidate.read_bytes() == after and patch.read_bytes() == sparse,
                    'Candidate changed before write')
            if before != after:
                state['flash_attempted'] = True
                write_state()
                output = run([writer, 'download:' + str(patch), 'flash:nflasha2'], 'write_MODE5_trigger')
                require(f'wrote {len(plan["changed_sectors"])} sectors to nflasha2' in output,
                        'Unexpected write acknowledgment')
                state['flash_acknowledged'] = True
            reads(['oem partition dump nflasha2', 'upload:' + str(folder / 'settings.after.logical.img'),
                   RAW_SETTINGS, 'upload:' + str(folder / 'settings.after.raw.img'),
                   'oem partition dump nflasha 0 0x80', 'upload:' + str(folder / 'sdm2.after.bin')],
                  'full_trigger_readback')
            post = (folder / 'settings.after.logical.img').read_bytes()
            raw_post = (folder / 'settings.after.raw.img').read_bytes()
            require(post == after, 'Complete logical readback differs; do not reboot')
            require(changed_sectors(raw_before, raw_post) == plan['changed_sectors'],
                    'Raw write extent differs; do not reboot')
            require((folder / 'sdm2.after.bin').read_bytes() == (folder / 'sdm2.before.bin').read_bytes(),
                    'Partition table changed')
            raw_verify(raw_post, post)
            require(make_trigger(post)[0] == post, 'Readback trigger does not reparse')
            state.update(readback_verified=True, complete_raw_XTS_40960_sectors_verified=True,
                         all_unrelated_settings_and_calibration_preserved=True)
            write_state()
            state['reboot_attempted'] = True
            write_state()
            reads(['reboot'], 'normal_reboot_to_SD_update')
            state.update(status='TRIGGER_WRITTEN_VERIFIED_REBOOT_ACKNOWLEDGED',
                         normal_reboot_acknowledged=True,
                         installation_result='PENDING_CAMERA_OBSERVATION')
        except BaseException as error:
            state.update(status='REBOOT_OUTCOME_UNCERTAIN' if state['reboot_attempted'] else 'STOPPED',
                         error=repr(error), automatic_retry_or_rollback=False)
            print('STOP:', repr(error), flush=True)
        finally:
            state['finished_utc'] = utc()
            write_state()
            print(json.dumps(dict(output=str(folder), **state), ensure_ascii=False, indent=2), flush=True)
    return 0 if state.get('normal_reboot_acknowledged') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--already-fastboot', action='store_true')
    parser.add_argument('--port')
    args = parser.parse_args()
    require(not (args.prepare and args.execute), 'Choose prepare or execute')
    BASE.mkdir(exist_ok=True)
    if args.execute:
        sys.exit(execute(args.port, args.already_fastboot))
    elif args.prepare:
        prepare()
    else:
        print('Offline: use --prepare. Device operation: --execute; logs under ' + str(BASE))
