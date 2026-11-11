"""执行已确认的首轮清理；先归档、复核，再按精确清单删除。"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PLAN = HERE / 'cleanup-plan.json'
GROUPS = ('small_disposable_cache', 'rust_rebuild_cache',
          'older_firmware_builds_archive_receipts_first',
          'older_QEMU_builds_archive_receipts_first')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def signature(path):
    s = path.lstat()
    return dict(device=s.st_dev, inode=s.st_ino, mode=s.st_mode,
                bytes=s.st_size, mtime_ns=s.st_mtime_ns, nlink=s.st_nlink,
                allocated=s.st_blocks * 512)


def tree(path):
    result = {}
    paths = [path, *path.rglob('*')] if path.is_dir() else [path]
    for p in paths:
        row = signature(p)
        if stat.S_ISLNK(row['mode']):
            row['link'] = os.readlink(p)
        result[str(p.relative_to(ROOT))] = row
    return result


def no_running_jobs():
    raw = subprocess.check_output(['ps', '-axo', 'pid=,comm=,args='], text=True)
    active = []
    for line in raw.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) < 3:
            continue
        pid, executable, command = fields
        name = Path(executable).name.lower()
        if name.startswith('qemu-system') or name in ('a7r5-desktop', 'cargo', 'rustc'):
            active.append((pid, executable))
        elif 'python' in name and re.search(r'(?:\s|/)(?:compose\.py|pytest|build_capture\.py|build\.py)(?:\s|$)', command):
            active.append((pid, executable))
    assert not active, '存在应先关闭的应用或构建进程：' + repr(active)


def selected_paths(plan):
    chosen, skipped = [], []
    for group in GROUPS:
        for name in plan['categories'][group]['candidate_paths']:
            # 不触碰本轮明确保留的研究运行区，即使其中只是字节码缓存。
            if group == 'small_disposable_cache' and 'runs' in Path(name).parts:
                skipped.append(name)
                continue
            chosen.append((name, group))
    roots = []
    for name, group in sorted(chosen, key=lambda item: len(Path(item[0]).parts)):
        path = ROOT / name
        if any(path.is_relative_to(ROOT / parent) for parent, _ in roots):
            continue
        assert path.exists() and not path.is_symlink(), name
        assert path.resolve().is_relative_to(ROOT) and path != ROOT
        assert not any(p.is_symlink() for p in path.parents)
        for keep in plan['protected']:
            protected = ROOT / keep
            assert not (path == protected or path.is_relative_to(protected)
                        or protected.is_relative_to(path)), name
        roots.append((name, group))
    return roots, skipped


def protected_facts():
    facts = {}
    # 源码与现有用户改动、发布封存和必要输入均单独校验。
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0')
    targets = [ROOT / os.fsdecode(p) for p in tracked if p]
    for folder in ('a7r5-firmware-features/releases',
                   'a7r5-firmware-features/native24-combined/releases',
                   'a7r5-desktop/prepared', 'a7r5-dat-tool/keys'):
        targets.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and not p.is_symlink())
    for p in set(targets):
        if p.is_file() and not p.is_symlink():
            facts[str(p.relative_to(ROOT))] = dict(bytes=p.stat().st_size, sha256=digest(p))
    for folder in ('4.19-full', '4.19-full-repaired-20261111'):
        base = ROOT / 'a7r5-firmware-features/releases' / folder
        for line in (base / 'SHA256SUMS').read_text().splitlines():
            expected, name = line.split('  ', 1)
            assert digest(base / name) == expected, name
    return facts


def rebuildable_container(path):
    name = path.name
    return (name.upper() == 'BODYDATA.DAT' or path.suffix.lower() == '.cpio'
            or (path.suffix.lower() == '.img' and path.stat().st_size >= 64 << 20)
            or re.fullmatch(r'nflasha\d+', name) is not None)


def archive(roots, out):
    rows, blobs, omitted = [], {}, []
    path = out / 'retained-evidence.zip'
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3, allowZip64=True) as z:
        for name, group in roots:
            if group not in GROUPS[2:]:
                continue
            for relative, meta in tree(ROOT / name).items():
                source = ROOT / relative
                row = dict(path=relative, **meta)
                if stat.S_ISDIR(meta['mode']):
                    row['disposition'] = 'directory-metadata'
                elif stat.S_ISLNK(meta['mode']):
                    row['disposition'] = 'symlink-metadata-no-follow'
                else:
                    before = signature(source)
                    h = digest(source)
                    assert signature(source) == before, '归档中来源变化：' + relative
                    row['sha256'] = h
                    if rebuildable_container(source):
                        row['disposition'] = 'rebuildable-container-hash-only'
                        omitted.append(dict(path=relative, bytes=meta['bytes'], sha256=h))
                    else:
                        row['disposition'] = 'archived-by-content-hash'
                        if h not in blobs:
                            z.write(source, 'objects/' + h)
                            assert signature(source) == before, '写归档时来源变化：' + relative
                            blobs[h] = meta['bytes']
                rows.append(row)
        manifest = dict(schema='r5-cleanup-evidence/1', original_root=str(ROOT),
                        preserved='all non-container files, source, objects, AP/CP binaries, resources, logs and receipts',
                        omitted='DAT/CPIO/IMG and nflasha partition containers; hashes and source metadata retained',
                        rows=rows, objects=blobs)
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    # 重新解压读取每个对象，不能只看 ZIP 是否能够打开。
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert json.loads(z.read('manifest.json')) == manifest
        for h, size in blobs.items():
            with z.open('objects/' + h) as f:
                computed = hashlib.file_digest(f, 'sha256').hexdigest()
            assert computed == h and z.getinfo('objects/' + h).file_size == size
    result = dict(zip_sha256=digest(path), zip_bytes=path.stat().st_size,
                  archived_objects=len(blobs), archived_rows=len(rows),
                  omitted_containers=omitted, all_objects_readback_verified=True)
    save(out / 'archive-verification.json', result)
    return result


def prepare(out):
    assert not out.exists()
    no_running_jobs()
    plan = json.loads(PLAN.read_text())
    roots, skipped = selected_paths(plan)
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).split(b'\0')
    for path in (os.fsdecode(p) for p in tracked if p):
        assert not any(path == name or path.startswith(name + '/') for name, _ in roots), path
    # 新增引用应阻止清理；旧历史清单与文档不是执行依赖。
    for scope in ('a7r5-firmware-features', 'a7r5-qemu', 'a7r5-desktop', 'sony-r5-colorlab'):
        for p in (ROOT / scope).rglob('*'):
            if not p.is_file() or p.is_symlink() or p.suffix not in ('.py', '.sh', '.json'):
                continue
            parts = p.relative_to(ROOT).parts
            if any(x in parts for x in ('.venv', 'build', 'runs', 'releases', 'verification',
                                        'evidence', 'node_modules', 'target', 'prepared', 'dist')):
                continue
            if p.stat().st_size > 2 << 20:
                continue
            try:
                text = p.read_text()
            except UnicodeError:
                continue
            for name, group in roots:
                if group not in GROUPS[2:]:
                    continue
                pattern = r'(?<![A-Za-z0-9_-])' + re.escape(Path(name).name) + r'(?![A-Za-z0-9_.-])'
                assert not re.search(pattern, text), '新增执行引用：' + str(p)
    out.mkdir()
    snapshot = {name: dict(group=group, entries=tree(ROOT / name)) for name, group in roots}
    facts = protected_facts()
    save(out / 'protected-before.json', facts)
    status = subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=ROOT)
    (out / 'git-status-before.txt').write_bytes(status)
    save(out / 'roots-before.json', snapshot)
    print('PREPARED_SNAPSHOT roots=' + str(len(roots)) + ' protected_files=' + str(len(facts)), flush=True)
    retained = archive(roots, out)
    # 将本轮保留的约7GiB运行区作为整体保护，防止缓存清理误入。
    keep = [*plan['protected'], *plan['categories']['current_build_keep']['candidate_paths'],
            *plan['categories']['older_QEMU_run_images_archive_evidence_first']['candidate_paths']]
    retained_trees = {name: tree(ROOT / name) for name in keep if (ROOT / name).exists()}
    save(out / 'retained-trees-before.json', retained_trees)
    save(out / 'prepared.json', dict(status='PREPARED_NOT_DELETED', plan_sha256=digest(PLAN),
         archive=retained, skipped_research_run_caches=skipped, roots=roots,
         free_before_delete=shutil.disk_usage(ROOT).free, root=str(ROOT),
         user_authorization='2026-11-11: 清理一下; execute recommended first batch, retain research runs',
         excluded_group='older_QEMU_run_images_archive_evidence_first', camera_io=False))
    print('ARCHIVE_VERIFIED bytes=' + str(retained['zip_bytes']), flush=True)


def execute(out):
    prepared = json.loads((out / 'prepared.json').read_text())
    assert prepared['status'] == 'PREPARED_NOT_DELETED' and prepared['root'] == str(ROOT)
    assert digest(PLAN) == prepared['plan_sha256']
    assert digest(out / 'retained-evidence.zip') == prepared['archive']['zip_sha256']
    assert not (out / 'deleted.json').exists()
    no_running_jobs()
    before = json.loads((out / 'roots-before.json').read_text())
    for name, row in before.items():
        assert tree(ROOT / name) == row['entries'], '删除前目标变化：' + name
    for name, pin in json.loads((out / 'protected-before.json').read_text()).items():
        assert digest(ROOT / name) == pin['sha256'], '删除前保护对象变化：' + name
    released, inodes = 0, set()
    for row in before.values():
        for entry in row['entries'].values():
            key = entry['device'], entry['inode']
            if stat.S_ISREG(entry['mode']) and key not in inodes:
                inodes.add(key)
                released += entry['allocated']
    deleted = []
    for name, row in before.items():
        p = ROOT / name
        assert tree(p) == row['entries'], '目标临时变化：' + name
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        deleted.append(name)
        with (out / 'deletion-journal.jsonl').open('a') as f:
            f.write(json.dumps(dict(path=name, deleted=True, time=time.time())) + '\n')
            f.flush()
            os.fsync(f.fileno())
    assert all(not (ROOT / name).exists() for name in deleted)
    for name, pin in json.loads((out / 'protected-before.json').read_text()).items():
        assert digest(ROOT / name) == pin['sha256'], '清理后保护对象不符：' + name
    for name, old in json.loads((out / 'retained-trees-before.json').read_text()).items():
        assert tree(ROOT / name) == old, '保留目录结构发生变化：' + name
    after_status = subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=ROOT)
    assert after_status == (out / 'git-status-before.txt').read_bytes(), '现有Git工作区状态变化'
    save(out / 'deleted.json', dict(status='CLEANUP_COMPLETED', deleted_paths=deleted,
         removed_allocated_inode_bytes=released, archive_bytes=prepared['archive']['zip_bytes'],
         free_after_delete=shutil.disk_usage(ROOT).free,
         free_gain_since_pre_delete=shutil.disk_usage(ROOT).free-prepared['free_before_delete'],
         protected_files_unchanged=True, retained_directory_trees_unchanged=True,
         tracked_worktree_unchanged=True, research_runs_retained=True, camera_io=False))
    print('CLEANUP_COMPLETED roots=' + str(len(deleted)) + ' removed_allocated_bytes=' + str(released))


if __name__ == '__main__':
    phase, directory = sys.argv[1:]
    output = Path(directory).resolve()
    assert output.parent == HERE and output.name.startswith('execution-')
    {'prepare': prepare, 'execute': execute}[phase](output)
