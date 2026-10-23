"""修复搬迁后的既有开发环境入口；先备份，不安装或升级任何依赖。"""
from pathlib import Path
import hashlib
import json
import re
import tempfile


def main():
    project = Path(__file__).resolve().parents[1]
    directory = project / '.venv/bin'
    activation = (directory / 'activate').read_text()
    old = re.search(r"^VIRTUAL_ENV='([^']+)'$", activation, re.M)
    if not old:
        raise ValueError('未知激活脚本，停止')
    old = old.group(1)
    current = str(project / '.venv')
    changes = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if old.encode() not in data:
            continue
        if data.startswith(('#!' + old + '/bin/python\n').encode()):
            # 相对本启动器寻找 Python，支持中文、空格及后续整体搬迁。
            shim = b'''#!/bin/sh\n\'\'\'exec\' "$(dirname -- "$0")/python" -B "$0" "$@"\n\' \'\'\'\n'''
            changed = shim + data.split(b'\n', 1)[1]
        elif path.name in ('activate', 'activate.bat', 'activate.csh', 'activate.fish', 'activate.nu'):
            changed = data.replace(old.encode(), current.encode())
        else:
            raise ValueError('未核对的旧路径入口: ' + path.name)
        if changed != data:
            changes.append((path, data, changed))
    if not changes:
        print('环境入口无需修复')
        return
    backup = Path(tempfile.mkdtemp(prefix='relocation-', dir=project / 'logs'))
    rows = []
    for path, before, after in changes:
        (backup / path.name).write_bytes(before)
        rows.append({'path': str(path.relative_to(project)),
                     'before': hashlib.sha256(before).hexdigest(),
                     'after': hashlib.sha256(after).hexdigest()})
    # 全部输入检查及备份完成后才改写已确认的开发入口，保留权限。
    for path, before, after in changes:
        if path.read_bytes() != before:
            raise ValueError('入口被其他进程修改，停止: ' + path.name)
        path.write_bytes(after)
    (backup / 'receipt.json').write_text(json.dumps({'old_environment': old,
        'new_environment': current, 'changes': rows}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'changed': len(rows), 'backup': str(backup)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
