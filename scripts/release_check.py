#!/usr/bin/env python3
"""检查 Git 候选文件，可导出只含已检查源码的副本；不提交、不上传。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

PRIVATE_HEADER = re.compile(rb'(?m)^-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----\r?$')
# 用户明确授权公开这一份研究身份；路径或内容变化都不自动放行。
PUBLIC_RESEARCH_KEYS = {
    'a7r5-dat-tool/keys/research-signing-private.pem':
        '3c64a0897fca201a1480e4d504719f354d1362ce05e1dcfc83efede9daeb405e',
}
# 用户明确授权纳入仓库的跨机通用依赖；仅按精确路径与 SHA-256 放行。
PORTABLE_COMMON_BINARIES = {
    'a7r5-exec/sdk/libc-2.25.so':
        'f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9',
    'a7r5-ssh/ssh-service/original-view/vendor/sftp-server.arm64':
        '621e0f8b6aaaedddbbd1e31dd01b2bae551b70af11d508b7fee66a491348f76e',
    'a7r5-fastboot/host/configure_fastboot_usb':
        '4543ed2b5f50cef4122e22a608dec6abff0f7d59c782e0c31003de32fada7595',
    'a7r5-fastboot/host/read_fastboot_usb':
        'f2b74e69dcc4be489e76bf14a2e0aeaef32ddbc19f2c8b80d417f9052f3a84bb',
    'a7r5-fastboot/assets/fastboot.bin':
        '330ac322bd0e40a7bb4974f69a2667e7d59a25e59c1322339690f30a3ceadbdc',
    'a7r5-fastboot/assets/pyserial-3.5-py2.py3-none-any.whl':
        'c4451db6ba391ca6ca299fb3ec7bae67a5c55dde170964c7a14ceefec02f2cf0',
    'a7r5-fastboot/assets/uart_boot.ino.uf2':
        '40554314f62bc5c22d6d22246b42988a79bb8f9a5089942fda7fbfb85e1d4dcd',
    'a7r5-fastboot/assets/bridge-verification.json':
        'b1e0e5b4b32a6c541c9103d1ae678eba6acc06e9ea5bd1c3e9eda0479391476c',
}
PASSWORD_HASH = re.compile(rb'\$6\$(?:rounds=\d+\$)?[./A-Za-z0-9]{1,16}\$[./A-Za-z0-9]{80,86}')
FORBIDDEN_DIRS = {'.venv', '__pycache__', '.pytest_cache', 'target', 'prepared', 'dist',
                  'packages', 'terminal-packages', 'runs', 'quick-runs', 'verification', 'logs', '.local'}
FORBIDDEN_SUFFIXES = {'.img', '.dat', '.cpio', '.dtb', '.bin', '.so', '.dylib', '.a', '.o', '.elf',
                      '.zip', '.deb', '.rpm', '.dmg', '.pkg'}


def candidates(root):
    """使用真正的 Git 忽略规则；已有仓库也检查被错误跟踪的忽略文件。"""
    root = Path(root).resolve()
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    with tempfile.TemporaryDirectory(prefix='a7r5-git-check-') as folder:
        if (root/'.git').exists():
            prefix = ['git', '-C', str(root)]
        else:
            metadata = Path(folder)/'metadata'
            subprocess.run(['git', 'init', '--bare', '--quiet', str(metadata)], check=True, env=env)
            prefix = ['git', '--git-dir='+str(metadata), '--work-tree='+str(root)]
        raw = subprocess.run([*prefix, '-c', 'core.excludesFile='+os.devnull, 'ls-files',
                              '-z', '--cached', '--others', '--exclude-standard'],
                             check=True, capture_output=True, env=env).stdout
    return sorted(set(os.fsdecode(p) for p in raw.split(b'\0') if p))


def inspect(root, names):
    """只报告路径和问题类型，不输出凭据内容。"""
    errors = []
    records = []
    for name in names:
        relative = Path(name)
        path = root/relative
        if relative.is_absolute() or '..' in relative.parts or path.is_symlink():
            errors.append(dict(path=name, reason='不接受链接或越界路径'))
            continue
        if any((root/Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts))):
            errors.append(dict(path=name, reason='父目录含链接'))
            continue
        if not path.is_file():
            errors.append(dict(path=name, reason='候选文件不存在'))
            continue
        if path.stat().st_size > 10*1024*1024:
            errors.append(dict(path=name, reason='超过项目源码文件大小门槛10MiB'))
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        allowed_common = PORTABLE_COMMON_BINARIES.get(name) == digest
        if name in PORTABLE_COMMON_BINARIES and not allowed_common:
            errors.append(dict(path=name, reason='白名单通用文件摘要变化，须重新确认'))
        if (set(relative.parts) & FORBIDDEN_DIRS
                or (relative.suffix.lower() in FORBIDDEN_SUFFIXES and not allowed_common)
                or relative.parts[0] == 'a7r5-firmware-images'
                or any(p.startswith('ATTEMPT_LOCK') or p.endswith('.app') for p in relative.parts)
                or relative.name in {'client-key', 'host_ecdsa', 'fixed-password-input', 'ACTIVE_SERVICE.json', 'PENDING_RECOVERY.json', 'ACTIVE_SESSION.lock'}):
            errors.append(dict(path=name, reason='本地材料或运行记录进入候选集'))
        allowed_key = PUBLIC_RESEARCH_KEYS.get(name) == digest
        if name in PUBLIC_RESEARCH_KEYS and not allowed_key:
            errors.append(dict(path=name, reason='公开研究私钥内容变化，须重新确认发布身份'))
        if PRIVATE_HEADER.search(raw) and not allowed_key:
            errors.append(dict(path=name, reason='包含私钥正文'))
        if PASSWORD_HASH.search(raw):
            errors.append(dict(path=name, reason='包含固定口令哈希，需人工排除或改为测试时生成'))
        if re.search(rb'/Users/'+rb'[A-Za-z0-9_.-]+/', raw):
            errors.append(dict(path=name, reason='包含开发机用户绝对路径'))
        # 拒绝无扩展名伪装的 ELF/Mach-O；白名单通用依赖与图标等源码资源不受影响。
        if not allowed_common and raw[:4] in (b'\x7fELF', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xca\xfe\xba\xbe'):
            errors.append(dict(path=name, reason='包含本机或客体可执行二进制'))
        records.append(dict(path=name, bytes=len(raw), sha256=digest))
    return records, errors


def export(root, destination, records):
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('导出目录必须不存在')
    if destination == root or root in destination.parents:
        raise ValueError('导出目录必须位于工程外')
    if any(p.is_symlink() for p in destination.parents):
        raise ValueError('导出目录不能经过链接；macOS 请使用 /private/tmp 而非 /tmp')
    # 检查与复制间发生修改时停止，不交付不匹配的源码副本。
    for row in records:
        if hashlib.sha256((root/row['path']).read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('候选文件在检查后发生变化: '+row['path'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.a7r5-export-', dir=destination.parent) as folder:
        staged = Path(folder)/'source'
        staged.mkdir()
        for row in records:
            source = root/row['path']
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row['sha256']:
                raise ValueError('复制前摘要变化: '+row['path'])
            target = staged/row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            target.chmod(source.stat().st_mode & 0o777)
            if hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('导出摘要不一致: '+row['path'])
        staged.rename(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report', type=Path)
    parser.add_argument('--export', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    records, errors = inspect(root, candidates(root))
    report = dict(status='failed' if errors else 'passed', files=len(records),
                  bytes=sum(r['bytes'] for r in records), errors=errors, manifest=records,
                  authorized_public_research_keys=[r['path'] for r in records
                      if PUBLIC_RESEARCH_KEYS.get(r['path']) == r['sha256']],
                  camera_IO=False, uploaded=False,
                  scope='当前 Git 候选集；不扫描既有 Git 历史，不替代完整秘密扫描或授权审查')
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'manifest'}, ensure_ascii=False, indent=2))
    if errors:
        return 1
    if args.export:
        export(root, args.export, records)
        print('已导出检查通过的源码副本；未创建提交或远端')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
