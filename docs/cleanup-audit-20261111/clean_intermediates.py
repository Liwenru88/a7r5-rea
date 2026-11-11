"""删除已核对生成链路的三个 CPIO 中间文件和研究目录内的字节码缓存。"""
import json
from pathlib import Path
import shutil
import subprocess
import time

from execute_cleanup import ROOT, HERE, digest, tree, no_running_jobs, save
from execute_deep_cleanup import surviving_files, allocated

OUT = HERE / 'execution-04-intermediates'
FILES = (
    'a7r5-qemu/build/full419-repaired-20261111-v2/replaced.cpio',
    'a7r5-qemu/build/shutter-dual-20261111-06/replaced.cpio',
    'a7r5-qemu/build/menu417-17-oLYPDW/final/with-observer.cpio',
)
CACHE_ROOTS = (
    'a7r5-qemu/runs/a7r5-lens-af-2qHo9T/default/work',
    'a7r5-qemu/runs/a7r5-lens-af-2qHo9T/runtime/work',
    'a7r5-qemu/runs/verify-17-NqJEIq/runtime/work',
)


def main():
    assert not OUT.exists() or (OUT.is_dir() and not list(OUT.iterdir()))
    no_running_jobs()
    targets = list(FILES)
    for root in CACHE_ROOTS:
        targets.extend(str(p.relative_to(ROOT)) for p in (ROOT / root).rglob('__pycache__')
                       if p.is_dir() and not p.is_symlink())
    if (ROOT / '.local/.DS_Store').is_file():
        targets.append('.local/.DS_Store')
    tracked = set(subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0'))
    for name in targets:
        p = ROOT / name
        assert p.exists() and not p.is_symlink() and not any(q.is_symlink() for q in p.parents)
        assert not any(t == name or t.startswith(name + '/') for t in tracked), name
    # 运行清单只引用最终 menu.cpio；中间文件在构建时重新生成。
    for name in ('full419-repaired-20261111-v2', 'shutter-dual-20261111-06', 'menu417-17-oLYPDW/final'):
        record = json.loads((ROOT / 'a7r5-qemu/build' / name / 'manifest.json').read_text())
        paths = {row['path'] for row in record['files'].values()}
        assert not any(any(path.endswith('/' + f.split('/')[-1]) for path in paths) for f in FILES)
    OUT.mkdir(exist_ok=True)
    before = allocated()
    snapshot = {name: tree(ROOT / name) for name in targets}
    # 用户已确认旧版发布目录由其手动移除；只豁免这一条明确路径。
    previous = json.loads((HERE / 'execution-03-deep/protected-before.json').read_text())
    retired = 'a7r5-firmware-features/releases/4.19-full/'
    protected = {name: row for name, row in previous.items()
                 if not name.startswith(retired) and Path(name).name != '.DS_Store'}
    for name, row in protected.items():
        assert digest(ROOT / name) == row['sha256'], name
    kept = surviving_files()
    kept = {name: row for name, row in kept.items()
            if not any(name == p or name.startswith(p + '/') for p in targets)}
    status = subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=ROOT)
    save(OUT / 'before.json', dict(targets=snapshot, protected=protected,
        intermediate_hashes={name: digest(ROOT / name) for name in FILES},
        cpio_backup='仅保存摘要；对应构建器会从保留种子及源码重新生成'))
    for name in targets:
        p = ROOT / name
        assert tree(p) == snapshot[name], name
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        with (OUT / 'deletion-journal.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(path=name, deleted=True, time=time.time())) + '\n')
    assert surviving_files() == kept, '保留文件变化'
    for name, row in protected.items():
        assert digest(ROOT / name) == row['sha256'], name
    assert subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=no'], cwd=ROOT) == status
    result = dict(status='CLEANUP_COMPLETED', deleted_paths=targets, before=before, after=allocated(),
                  protected_hashes_unchanged=len(protected), remaining_files_metadata_unchanged=len(kept),
                  tracked_worktree_unchanged=True, camera_io=False)
    save(OUT / 'result.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'deleted_paths'}))


if __name__ == '__main__':
    main()
