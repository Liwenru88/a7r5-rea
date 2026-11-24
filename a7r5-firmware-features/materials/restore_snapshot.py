"""按固定来源补齐十三项易被忽略的冻结材料；不执行模板、不访问相机。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent / 'firmware-runtime/dependencies/native12-combined/upstream'
CAPSULE = HERE / 'snapshot-repair.json'
COMMIT = '47f8f022628aef8de382a613ea4d11cd51d0a965'
SNAPSHOT = 'c81e5b4681479eccf99224aae820adabaf139df3fb758a1e1927d81787e0ad95'
ALLOWED = {'.gitignore', 'R5FlashWorkbench/engine/templates.json',
           'R5FlashWorkbench/.gitignore', 'firmware/r5/.gitignore',
           'R5FlashWorkbench/engine/filters/R5NATIVE.BIN', 'filters/FUJ_12_v45/R5NATIVE.BIN',
           *(f'publication/{version}/SHA256SUMS' for version in ('4.28', '4.32', '4.34')),
           *(f'R5FlashWorkbench/engine/templates/{name}.so' for name in
             ('capture', 'capture-cleanup', 'trust-blank-512', 'trust-installed-boot-hook'))}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def restore(root=DEFAULT_ROOT, *, capsule=CAPSULE, backup=None, restore_gitignore=False,
            apply=True, source_dir=None, download=False):
    root, capsule = Path(root).absolute(), Path(capsule)
    require(root.is_dir() and not root.is_symlink() and not root.resolve().is_relative_to('/dev'), '冻结源目录无效或为链接')
    snapshot = root / 'UPSTREAM_SNAPSHOT.json'
    require(not snapshot.is_symlink() and digest(snapshot.read_bytes()) == SNAPSHOT, '冻结清单身份不符')
    pins = json.loads(snapshot.read_text())['files']
    require(capsule.stat().st_size <= 300000, '恢复材料超出预算')
    record = json.loads(capsule.read_text())
    require(record['schema'] == 'r5-frozen-snapshot-repair/1' and record['commit'] == COMMIT
            and record['snapshot_sha256'] == SNAPSHOT, '恢复材料版本不符')
    rows = record['files']
    require(len(rows) == len(ALLOWED) and {row['path'] for row in rows} == ALLOWED, '恢复路径集合不符')
    pending, skipped = [], []
    # 所有来源和目标先核对；一个未知二进制即可阻止整批写入。
    for row in rows:
        pin, name = pins[row['path']], row['path']
        require(row['bytes'] == pin['bytes'] and row['sha256'] == pin['sha256'], '恢复材料摘要声明不符 ' + name)
        url = 'https://raw.githubusercontent.com/Hearts-Ace/sony-a7r5-custom-firmware/' + COMMIT + '/' + name
        require(row['url'] == url, '恢复地址不是固定上游提交 ' + name)
        target = root / name
        require(not target.is_symlink() and all(not p.is_symlink() for p in target.parents
                if p == root or p.is_relative_to(root)), '恢复路径含链接 ' + name)
        require(not target.exists() or target.is_file(), '恢复目标不是普通文件 ' + name)
        if target.exists() and target.stat().st_size == pin['bytes'] and digest(target.read_bytes()) == pin['sha256']:
            skipped.append(name)
            continue
        replace = target.exists()
        require(not replace or (name == '.gitignore' and restore_gitignore and backup is not None), '未知前像，拒绝覆盖 ' + name)
        if source_dir is not None:
            source = Path(source_dir).absolute() / name
            require(not source.is_symlink() and all(not p.is_symlink() for p in source.parents), '本地材料路径含链接')
            require(source.is_file() and source.stat().st_size == pin['bytes'], '本地材料长度不符 ' + name)
            data = source.read_bytes()
        elif download:
            with urllib.request.urlopen(url, timeout=30) as response:
                require(response.geturl() == url, '恢复下载发生未批准的重定向')
                data = response.read(pin['bytes'] + 1)
        else:
            raise ValueError('缺少材料，请指定 --source-dir 或显式 --download：' + name)
        require(len(data) == pin['bytes'] and digest(data) == pin['sha256'], '恢复材料摘要不符 ' + name)
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        require(blob == row['sha'], '恢复材料 Git blob 不符 ' + name)
        pending.append((name, target, data, replace))
    if apply and any(row[3] for row in pending):
        backup = Path(backup).absolute()
        require(not backup.exists() and not any(p.is_symlink() for p in backup.parents), '备份目录须全新且无链接')
        require(not backup.is_relative_to(root) and not backup.resolve().is_relative_to('/dev'), '备份不能写入冻结快照或设备路径')
        backup.mkdir(mode=0o700, parents=True)
        shutil.copy2(root / '.gitignore', backup / 'gitignore.before')
    if apply:
        for name, target, data, replace in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            if replace:
                target.write_bytes(data)
            else:
                with target.open('xb') as stream:
                    stream.write(data)
    names = [row[0] for row in pending]
    return dict(schema='r5-snapshot-restoration/1', commit=COMMIT, snapshot_sha256=SNAPSHOT,
                restored=names if apply else [], would_restore=[] if apply else names, skipped=skipped,
                all_material_pins_verified=True, manifest_modified=False, camera_io=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    parser.add_argument('--apply', action='store_true', help='写入已核对的缺失文件；默认只输出计划')
    parser.add_argument('--restore-gitignore', action='store_true')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--source-dir', type=Path, help='从包含同一冻结目录结构的本地副本恢复，无需联网')
    parser.add_argument('--download', action='store_true', help='允许下载固定上游提交；默认不联网')
    args = parser.parse_args()
    print(json.dumps(restore(args.root, apply=args.apply, backup=args.backup,
                             restore_gitignore=args.restore_gitignore, source_dir=args.source_dir,
                             download=args.download), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
