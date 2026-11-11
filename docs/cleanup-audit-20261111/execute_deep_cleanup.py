"""执行第三轮清理：保留现用输入，归档旧实验与重复解包副本。"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import zipfile

from execute_cleanup import ROOT, HERE, digest, save, signature, tree, no_running_jobs, protected_facts

OUT = HERE / 'execution-03-deep'
TARGETS = {
    'a7r5-qemu/runs/native24-aspect-menu-L1hQVI': 'old-qemu',
    'a7r5-qemu/runs/native24-look-closure-DekVA6': 'old-qemu',
    'a7r5-qemu/runs/native24-portrait-Eccxto': 'old-qemu',
    'a7r5-qemu/runs/native24-stalled-look-eLuDNt': 'old-qemu',
    'a7r5-qemu/build/full419-final-04': 'old-qemu',
    'a7r5-qemu/build/full419-final-04-components': 'old-qemu',
    'a7r5-desktop/dist': 'old-desktop',
    'a7r5-fastboot/private/cases/4.18-incident/desktop': 'derived-incident-copy',
    'a7r5-fastboot/private/cases/4.18-incident/release418': 'derived-incident-copy',
    'a7r5-fastboot/private/cases/4.18-wbi-verify/workspace': 'derived-incident-copy',
    'a7r5-fastboot/private/cases/4.18-wbi-verify/readback': 'derived-incident-copy',
    'a7r5-fastboot/private/cases/4.18-wbi-verify/wbi-before.bin': 'derived-incident-copy',
    'a7r5-fastboot/private/cases/4.18-component-audit/rebuild': 'derived-incident-copy',
}


def excluded(relative):
    return (relative == '.git' or relative.startswith('.git/')
            or relative.startswith('docs/cleanup-audit-20261111/')
            or Path(relative).name == '.DS_Store'
            or any(relative == name or relative.startswith(name + '/') for name in TARGETS))


def surviving_files():
    """记录所有保留文件的身份和修改时间；不跟随软链接。"""
    result = {}
    for folder, dirs, files in os.walk(ROOT, followlinks=False):
        base = Path(folder)
        dirs[:] = [d for d in dirs if not excluded(str((base / d).relative_to(ROOT)))]
        for name in files:
            p = base / name
            relative = str(p.relative_to(ROOT))
            if not excluded(relative):
                row = signature(p)
                # 删除另一个硬链接会改变 nlink，但不应改变保留文件内容和身份。
                row.pop('nlink')
                result[relative] = row
    return result


def allocated():
    seen, total = set(), 0
    for folder, _, files in os.walk(ROOT, followlinks=False):
        for name in files:
            s = (Path(folder) / name).lstat()
            key = s.st_dev, s.st_ino
            if key not in seen:
                seen.add(key)
                total += s.st_blocks * 512
    return total


def archive(snapshot):
    rows, objects, omitted = [], {}, []
    destination = OUT / 'retained-evidence.zip'
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3, allowZip64=True) as z:
        for name, item in snapshot.items():
            print('ARCHIVING ' + name, flush=True)
            for relative, original in item['entries'].items():
                p = ROOT / relative
                expected_meta = {k: v for k, v in original.items() if k != 'link'}
                assert signature(p) == expected_meta, relative
                row = dict(path=relative, **original)
                if stat.S_ISDIR(original['mode']):
                    row['disposition'] = 'directory-metadata'
                elif stat.S_ISLNK(original['mode']):
                    row['link'] = os.readlink(p)
                    row['disposition'] = 'symlink-metadata-no-follow'
                else:
                    assert stat.S_ISREG(original['mode']), relative
                    h = digest(p)
                    assert signature(p) == original, relative
                    row['sha256'] = h
                    # 仅丢弃旧模拟客体的可重建容器。故障解包副本全部逐字节归档。
                    if item['group'] == 'old-qemu' and p.suffix.lower() == '.cpio':
                        row['disposition'] = 'rebuildable-old-guest-container-hash-only'
                        omitted.append(dict(path=relative, bytes=original['bytes'], sha256=h))
                    else:
                        row['disposition'] = 'archived-by-content-hash'
                        if h not in objects:
                            z.write(p, 'objects/' + h)
                            assert signature(p) == original, relative
                            objects[h] = original['bytes']
                rows.append(row)
        manifest = dict(schema='r5-cleanup-evidence/2', original_root=str(ROOT),
                        rows=rows, objects=objects, omitted_containers=omitted,
                        note='故障副本完整保存普通文件；旧 QEMU CPIO 仅保留摘要，非完整客体备份。')
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    print('VERIFYING_ARCHIVE', flush=True)
    with zipfile.ZipFile(destination) as z:
        assert json.loads(z.read('manifest.json')) == manifest
        for h, size in objects.items():
            with z.open('objects/' + h) as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == h
            assert z.getinfo('objects/' + h).file_size == size
    return dict(bytes=destination.stat().st_size, sha256=digest(destination),
                object_count=len(objects), source_rows=len(rows),
                omitted_containers=omitted, all_objects_readback_verified=True)


def prepare():
    assert not OUT.exists(), '已有执行记录，不可覆盖'
    no_running_jobs()
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0')
    for raw in tracked:
        if raw:
            relative = os.fsdecode(raw)
            assert not any(relative == p or relative.startswith(p + '/') for p in TARGETS), relative
    # 重查当前执行代码；历史发布材料和故障回放脚本仍按原实验保存。
    tokens = [Path(p).name for p, group in TARGETS.items() if group == 'old-qemu']
    scanned = 0
    for scope in ('a7r5-firmware-features', 'a7r5-qemu', 'a7r5-desktop', 'sony-r5-colorlab'):
        for p in (ROOT / scope).rglob('*'):
            if not p.is_file() or p.is_symlink() or p.suffix not in ('.py', '.sh'):
                continue
            if any(x in p.relative_to(ROOT).parts for x in
                   ('.venv', 'build', 'runs', 'releases', 'verification', 'evidence', 'dist', 'prepared')):
                continue
            if p.stat().st_size > 2 << 20:
                continue
            body = p.read_text(errors='replace')
            assert not any(t in body for t in tokens), '仍有执行引用：' + str(p)
            scanned += 1
    OUT.mkdir()
    snapshot = {}
    for name, group in TARGETS.items():
        p = ROOT / name
        assert p.exists() and not p.is_symlink() and p.resolve().is_relative_to(ROOT)
        assert not any(q.is_symlink() for q in p.parents)
        snapshot[name] = dict(group=group, entries=tree(p))
    save(OUT / 'roots-before.json', snapshot)
    (OUT / 'git-status-before.txt').write_bytes(subprocess.check_output(
        ['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=ROOT))
    save(OUT / 'protected-before.json', protected_facts())
    save(OUT / 'surviving-files-before.json', surviving_files())
    before = allocated()
    result = archive(snapshot)
    save(OUT / 'prepared.json', dict(status='PREPARED_NOT_DELETED', targets=TARGETS,
        script_sha256=digest(Path(__file__)), archive=result, root_allocated_before=before,
        free_before_delete=shutil.disk_usage(ROOT).free, executable_sources_checked=scanned,
        user_authorization='2026-11-11 当前工程占用还是很大，需要把没有用的都删了', camera_io=False))
    print(json.dumps(dict(status='PREPARED', archive=result['bytes'], targets=len(TARGETS))), flush=True)


def execute():
    before = json.loads((OUT / 'prepared.json').read_text())
    assert before['status'] == 'PREPARED_NOT_DELETED' and before['targets'] == TARGETS
    assert before['script_sha256'] == digest(Path(__file__))
    assert before['archive']['sha256'] == digest(OUT / 'retained-evidence.zip')
    assert not (OUT / 'deleted.json').exists()
    no_running_jobs()
    snapshots = json.loads((OUT / 'roots-before.json').read_text())
    for name, item in snapshots.items():
        assert tree(ROOT / name) == item['entries'], '删除前目标变化：' + name
    protected = json.loads((OUT / 'protected-before.json').read_text())
    for name, row in protected.items():
        assert digest(ROOT / name) == row['sha256'], name
    kept = json.loads((OUT / 'surviving-files-before.json').read_text())
    assert surviving_files() == kept, '删除前保留文件发生变化'
    for name in TARGETS:
        p = ROOT / name
        assert tree(p) == snapshots[name]['entries'], name
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        with (OUT / 'deletion-journal.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(path=name, deleted=True, time=time.time())) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        print('DELETED ' + name, flush=True)
    assert all(not (ROOT / p).exists() for p in TARGETS)
    assert surviving_files() == kept, '清理后保留文件发生变化'
    for name, row in protected.items():
        assert digest(ROOT / name) == row['sha256'], name
    assert subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'],
        cwd=ROOT) == (OUT / 'git-status-before.txt').read_bytes()
    after = allocated()
    result = dict(status='CLEANUP_COMPLETED', deleted_paths=list(TARGETS),
                  root_allocated_before=before['root_allocated_before'], root_allocated_after=after,
                  net_root_reduction=before['root_allocated_before'] - after,
                  archive=before['archive'], all_other_files_metadata_unchanged=True,
                  unchanged_surviving_files=len(kept), protected_hashes_unchanged=len(protected),
                  tracked_worktree_unchanged=True, camera_io=False)
    save(OUT / 'deleted.json', result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('archive', 'deleted_paths')}), flush=True)


if __name__ == '__main__':
    {'prepare': prepare, 'execute': execute}[sys.argv[1]]()
