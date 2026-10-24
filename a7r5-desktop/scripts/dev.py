"""按源码摘要缓存开发应用，离线构建、自检后启动，不生成交付安装包。"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT.parent / '.local/studio-dev'
BASE = ROOT / 'prepared/engine'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_inputs():
    paths = []
    for directory in ('engine', 'web', 'src-tauri/src', 'src-tauri/icons'):
        paths.extend(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts
                     and p.suffix not in ('.pyc', '.pyo') and p.name != '.DS_Store')
    paths.extend(ROOT / name for name in (
        'src-tauri/Cargo.toml', 'src-tauri/Cargo.lock', 'src-tauri/build.rs',
        'src-tauri/tauri.conf.json', 'scripts/dev.py', 'scripts/prepare.py',
        'sources/trust/libjit-trust.c', 'sources/trust/capture_gate.c', 'sources/trust/capture_control.h',
        'sources/trust/work_probe.c', 'sources/trust/native_gate.c', 'sources/trust/sector_core.inc',
        'sources/trust/capture_cleanup.c',
        'sources/trust/sha256.h'))
    return sorted(paths)


def revision(paths):
    values = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    values['prepared/integrity.json'] = sha(BASE / 'integrity.json')
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def verify_base():
    manifest = json.loads((BASE / 'integrity.json').read_text())
    if not manifest.get('files'):
        raise ValueError('运行材料清单为空，请按开发构建说明重新准备')
    for name, expected in manifest['files'].items():
        path = BASE / name
        if not path.resolve().is_relative_to(BASE.resolve()):
            raise ValueError('运行材料清单含有越界路径')
        if path.stat().st_size != expected['bytes'] or sha(path) != expected['sha256']:
            raise ValueError(f'运行材料校验失败：{name}，请按开发构建说明重新准备')


def seal(engine, manifest_target):
    files = {str(p.relative_to(engine)): dict(sha256=sha(p), bytes=p.stat().st_size)
             for p in sorted(engine.rglob('*'))
             if p.is_file() and p != engine / 'integrity.json'}
    manifest = engine / 'integrity.json'
    manifest.write_text(json.dumps(dict(schema=1, files=files), ensure_ascii=False, indent=2) + '\n')
    manifest_target.write_text(sha(manifest) + '\n')


def rebuild_capture(mirror):
    # 只在新缓存中编译维护模板，避免新控制路径误用旧的持久工作区载荷。
    spec = importlib.util.spec_from_file_location('desktop_capture_build', mirror/'scripts/prepare.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.capture_payload()
    builder.trust_payload()


def selfcheck(app):
    # 自检禁止网络、IOKit与设备文件访问；GUI在自检通过后另行启动。
    policy = ('(version 1)(allow default)(deny network*)(deny iokit-open)'
              '(deny file-read* file-write* '
              '(require-all (subpath "/dev") (require-not (literal "/dev/null"))))')
    result = subprocess.run([
        '/usr/bin/sandbox-exec', '-p', policy,
        str(app / 'Contents/MacOS/a7r5-desktop'), '--selfcheck',
    ], check=True, capture_output=True, text=True)
    value = json.loads(result.stdout.splitlines()[-1])
    if value.get('ok') is not True or value.get('camera_IO') is not False or value.get('USB_enumerated') is not False:
        raise ValueError('离线自检回执不完整')
    print('离线自检通过：未枚举 USB、未连接相机。', flush=True)
    return value


def build(paths, key):
    cargo = shutil.which('cargo')
    if cargo is None:
        candidate = Path.home() / '.cargo/bin/cargo'
        if candidate.is_file():
            cargo = str(candidate)
    if cargo is None:
        raise RuntimeError('未找到 Rust cargo，请先准备开发环境；脚本不会自动安装依赖')
    verify_base()
    work = Path(tempfile.mkdtemp(prefix=f'{key[:12]}-', dir=CACHE))
    mirror = work / 'source'
    for path in paths:
        target = mirror / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    engine = mirror / 'prepared/engine'
    shutil.copytree(BASE, engine, symlinks=False, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo'))
    # 源码覆盖仅发生在新建缓存内，原 prepared 和历史应用保持原样。
    shutil.copytree(mirror / 'engine', engine, dirs_exist_ok=True)
    rebuild_capture(mirror)
    seal(engine, mirror / 'src-tauri/engine.sha256')
    if revision(paths) != key:
        raise RuntimeError('构建期间源码发生变化，请重新运行；此次缓存不启用')
    env = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='14.0')
    # Finder 启动的终端不一定已把 Rust 工具目录放进 PATH。
    env['PATH'] = str(Path(cargo).parent) + os.pathsep + env.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')
    env.pop('CARGO_BUILD_TARGET', None)
    target_dir = ROOT / 'src-tauri/target'
    print('正在离线编译客户端，首次运行可能需要几分钟…', flush=True)
    subprocess.run([
        cargo, 'build', '--offline', '--locked', '--manifest-path',
        str(mirror / 'src-tauri/Cargo.toml'), '--target-dir', str(target_dir),
        '--bin', 'a7r5-desktop',
    ], env=env, check=True)
    app = work / 'A7R5 Studio.app'
    contents = app / 'Contents'
    mac = contents / 'MacOS'
    mac.mkdir(parents=True)
    (contents / 'Resources').mkdir()
    shutil.copy2(target_dir / 'debug/a7r5-desktop', mac / 'a7r5-desktop')
    shutil.move(str(engine), str(contents / 'Resources/engine'))
    (contents / 'Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleName='A7R5 Studio', CFBundleDisplayName='A7R5 Studio 开发版',
        CFBundleIdentifier='local.a7r5.studio', CFBundleExecutable='a7r5-desktop',
        CFBundlePackageType='APPL', CFBundleShortVersionString='0.1.0',
        CFBundleVersion='1', LSMinimumSystemVersion='14.0', NSHighResolutionCapable=True,
    )))
    subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    return app


def backup(app, data=None):
    """通过固定助手和终端sudo执行一次备份，保留与GUI一致的任务记录。"""
    data = Path(data) if data is not None else Path.home()/'Library/Application Support/local.a7r5.studio'
    if data.absolute() != data.resolve():
        raise ValueError('任务目录不接受符号链接')
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (data/'application.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('请先正常退出正在运行的客户端，再执行终端备份') from None
        run = uuid.uuid4().hex
        tasks = data/'tasks';tasks.mkdir(exist_ok=True, mode=0o700)
        folder = tasks/run;folder.mkdir(mode=0o700)
        def write(name, value):
            fd = os.open(folder/name, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
        write('request.json', dict(kind='backup', run_id=run))
        initial = dict(id=run, kind='backup', created=int(time.time()), running=True,
                       directory=str(folder), message='等待终端管理员授权；仅执行备份，不更新信任')
        write('status.json', initial)
        print(f'备份任务：{folder}\n请输入这台Mac的登录密码；执行中保持相机供电与连接。', flush=True)
        try:
            subprocess.run(['/usr/bin/sudo', '--', str(app/'Contents/MacOS/a7r5-desktop'),
                            '--privileged-task', str(folder/'request.json')], check=False)
        finally:
            receipt = folder/'privileged-result.json'
            value = json.loads(receipt.read_text()) if receipt.is_file() else dict(
                task_complete=False, can_replug=False,
                error='授权或助手未返回完整结果；保留连接和任务现场，不自动重试')
            write('result.json', value)
            write('status-finished.json', dict(initial, running=False, result=value,
                  interrupted=not receipt.is_file()))
            os.replace(folder/'status-finished.json', folder/'status.json')
        if value.get('backup_complete') is True:
            print('完整备份已通过长度与摘要校验：'+str(value['backup_file']), flush=True)
        if value.get('task_complete') is not True:
            raise RuntimeError(value.get('error', '备份未完成，请保留现场，不重试'))
        if value.get('backup_complete') is not True:
            print('完整备份已通过长度与摘要校验：'+str(value['backup_file']), flush=True)
        if value.get('trust_state') == 'unsupported':
            print('当前分区前像未适配，备份保留；未执行信任更新。', flush=True)
        if value.get('USB_recovered') is not True:
            print('MSC恢复尚未确认，请保持连接并检查相机屏幕。', flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--selfcheck', action='store_true', help='仅准备缓存并离线自检，不打开客户端')
    modes.add_argument('--backup', action='store_true', help='终端授权执行一次备份，不打开GUI或更新信任')
    args = parser.parse_args(argv)
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('当前开发入口仅支持 macOS Apple Silicon')
    if not (BASE / 'integrity.json').is_file():
        raise RuntimeError('缺少 prepared/engine 运行材料，请先按 a7r5-desktop/README.md 准备')
    os.umask(0o077)
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (CACHE / 'build.lock').open('a') as lock:
        print('检查开发缓存（如有其他编译正在进行，将等待其结束）…', flush=True)
        fcntl.flock(lock, fcntl.LOCK_EX)
        paths = source_inputs()
        key = revision(paths)
        ready = CACHE / f'{key}.json'
        if ready.is_file():
            app = Path(json.loads(ready.read_text())['app'])
            if not app.resolve().is_relative_to(CACHE.resolve()) or not app.is_dir():
                raise ValueError('开发缓存索引无效；请保留现场并检查缓存')
            print('源码未变化，复用开发缓存。', flush=True)
        else:
            app = build(paths, key)
        proof = selfcheck(app)
        if not ready.exists():
            ready.write_text(json.dumps(dict(app=str(app), revision=key, selfcheck=proof), ensure_ascii=False, indent=2) + '\n')
    print(f'开发运行目录：{app}', flush=True)
    if args.backup:
        backup(app)
    elif not args.selfcheck:
        print('正在打开客户端；设备操作仍需在界面中手动发起。若旧客户端正在运行，请先正常退出旧客户端。', flush=True)
        subprocess.run(['/usr/bin/open', '-a', str(app)], check=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'启动失败：{error}', file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError):
            print(error.stdout or '', file=sys.stderr)
            print(error.stderr or '', file=sys.stderr)
        sys.exit(1)
