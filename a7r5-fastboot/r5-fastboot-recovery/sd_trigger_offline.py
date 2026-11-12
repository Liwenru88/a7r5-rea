#!/usr/bin/env python3
"""Offline MODE5 candidate generation only: no camera access or flash capability."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import stat
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'vendor/fwtool.py-a7iv'))
from build_r5_partition1 import FatImage, require
from patch_r5_slot_settings import SIZE, apply_sparse, changed_sectors, make_sparse
from fwtool.archive import fat as independent_fat

# Pure trigger algorithm retained from r5_sd_recovery_impl.py; covered by roundtrip tests.
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


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def generate(settings, package, output):
    settings, package, output = map(lambda p: Path(p).resolve(), (settings, package, output))
    if output.exists():
        raise FileExistsError('Output must be a new directory: ' + str(output))
    require(settings.is_file() and settings.stat().st_size == SIZE,
            'Need a complete 20 MiB logical settings image, not raw/encrypted data')
    require(package.is_file() and package.stat().st_size > 0, 'Package must be a nonempty file')
    before = settings.read_bytes()
    after, plan = make_trigger(before)
    sparse = make_sparse(before, after)
    require(apply_sparse(before, sparse) == (after, plan['changed_sectors']),
            'Sparse reconstruction failed')
    require(make_trigger(after)[0] == after, 'Trigger is not idempotent')
    report = dict(schema='r5-mode5-offline/1', camera_io=False, flash_authorized=False,
                  input_freshness_verified=False, same_physical_body_verified=False,
                  package_compatibility_verified=False, package_signature_verified=False,
                  settings_path=str(settings), settings_sha256=sha(before),
                  package_path=str(package), package_size=package.stat().st_size,
                  package_sha256=digest_file(package), plan=plan,
                  artifacts={'OFFLINE_ONLY.settings.logical.img': sha(after),
                             'OFFLINE_ONLY.trigger.sparse.img': sha(sparse)},
                  warning='OFFLINE ONLY. Do not flash without a fresh live read, updater compatibility verification and separate authorization.')
    report = json.loads(json.dumps(report))  # Keep returned and persisted JSON contracts identical.
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name, data in [('OFFLINE_ONLY.settings.logical.img', after),
                       ('OFFLINE_ONLY.trigger.sparse.img', sparse),
                       ('report.json', (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())]:
        with (output / name).open('xb') as stream:
            (output / name).chmod(0o600)
            stream.write(data)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', required=True, type=Path, help='Fresh current 20 MiB logical nflasha2 readback')
    parser.add_argument('--package', required=True, type=Path, help='Target DAT identity only; compatibility is NOT verified')
    parser.add_argument('--output', required=True, type=Path, help='New output directory')
    args = parser.parse_args()
    try:
        report = generate(args.settings, args.package, args.output)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        parser.exit(1, 'Offline generation stopped: ' + str(exc) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
