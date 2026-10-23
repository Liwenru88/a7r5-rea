"""libJit SSH快捷调度：默认仅本机状态，显式执行仍保留阶段门槛。"""
import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
PYTHON = PROJECT / '.venv/bin/python'
PASSWORD = PROJECT / 'a7r5-ssh/ssh-service/fixed-password-input'
RUNS = HERE / 'quick-runs'
sys.path.insert(0, str(HERE))
import tool
import policy


def read_json(path):
    return json.loads(tool.regular(path).read_text())


def require_idle():
    # 查询本机记录；不借助网络超时判断服务已结束，也不自动清除记录。
    with tool.exclusive(PROJECT):
        for path in (HERE / 'PENDING_RECOVERY.json', PROJECT / 'a7r5-exec/PENDING_RECOVERY.json'):
            if path.exists() or path.is_symlink():
                raise PermissionError('存在待恢复或待屏幕确认记录，停止。保留记录并按原会话恢复方案处理。')
        active = HERE / 'ACTIVE_SERVICE.json'
        if active.exists() or active.is_symlink():
            record = read_json(active)
            raise PermissionError('已有活动服务记录：' + record['run_id'] +
                                  '。这不证明此刻仍在监听；禁止重复启动。请先按原包停止/回收；重启后记录过期也不自动删除。')


def check_package(path):
    path = Path(path).absolute()
    manifest = tool.check(path)
    if manifest['coordinator'] != str(HERE) or manifest['project'] != str(PROJECT):
        raise ValueError('包不属于当前工程')
    if manifest['qemu_only'] is not False or manifest['ttl_seconds'] != 0 or manifest['autostart'] is not False:
        raise ValueError('快捷入口只接受不限时、非自启的实机包')
    return path, manifest


def login_command(path, ip=None):
    path, manifest = check_package(path)
    stage = path / '.state/start-once'
    result = read_json(stage / 'result.json')
    screen = read_json(stage / 'screen.json')
    binding = dict(run_id=manifest['run_id'], package=str(path), action='start-once',
                   manifest_sha256=tool.sha(path / 'manifest.json'))
    if (any(result.get(k) != v for k, v in binding.items())
            or result.get('passed') is not True or result.get('host_recovery_verified') is not True
            or screen.get('screen_normal') is not True
            or screen['result_sha256'] != tool.sha(stage / 'result.json')):
        raise ValueError('启动、恢复或屏幕确认未通过，不生成登录命令')
    identity = policy.ready(tool.regular(stage / 'session/ready.bin').read_bytes(), manifest['run_id'], 0)
    public = policy.public_key(tool.regular(stage / 'host-public-key').read_bytes(), identity['public_sha'])
    alias = 'a7r5-libjit-' + manifest['run_id']
    hosts = stage / 'known_hosts'
    if tool.regular(hosts).read_bytes() != alias.encode() + b' ' + public + b'\n':
        raise ValueError('本次可信主机公钥不符')
    return shlex.join(['/usr/bin/ssh', '-F', '/dev/null', '-o', 'HostKeyAlias=' + alias,
                       '-o', 'UserKnownHostsFile=' + str(hosts), '-o', 'GlobalKnownHostsFile=/dev/null',
                       '-o', 'StrictHostKeyChecking=yes', '-o', 'IdentityAgent=none',
                       '-o', 'PubkeyAuthentication=no', '-o', 'PreferredAuthentications=password',
                       '-o', 'NumberOfPasswordPrompts=1', '-o', 'ConnectionAttempts=1',
                       '-o', 'ConnectTimeout=10', '-p', '2222', 'root@' + (ip or 'CAMERA_IPV4')])


def status(ip=None):
    active = HERE / 'ACTIVE_SERVICE.json'
    value = dict(offline_only=True, device_requests=0, network_connections=0,
                 live_service_state='未探测，仅显示本机记录',
                 pending_recovery=any(p.exists() or p.is_symlink() for p in
                                      (HERE / 'PENDING_RECOVERY.json', PROJECT / 'a7r5-exec/PENDING_RECOVERY.json')))
    if active.exists() or active.is_symlink():
        value['active_record'] = read_json(active)
        _, manifest = check_package(value['active_record']['package'])
        if (value['active_record']['run_id'] != manifest['run_id']
                or value['active_record']['manifest_sha256'] != tool.sha(Path(manifest['directory']) / 'manifest.json')):
            raise ValueError('活动记录与封包不匹配，不生成连接命令')
        if not value['pending_recovery']:
            value['login_command'] = login_command(value['active_record']['package'], ip)
    else:
        value['active_record'] = None
    return value


def prepare():
    # 编译和口令哈希生成都只在Mac执行，不拷贝明文口令进包。
    import package
    path = HERE / 'packages' / ('quick-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    package.prepare(path, PASSWORD, seconds=0)
    return check_package(path)


def fresh_package(path):
    path, manifest = check_package(path)
    for action in ('load-once', 'start-once'):
        stage = path / '.state' / action
        if stage.exists() or stage.is_symlink():
            raise PermissionError('本包已有' + action + '尝试记录；禁止重跑。保留旧包和锁，按原会话处理。')
    return path, manifest


@contextmanager
def dispatcher_lock():
    # 此锁仅协调快捷入口；客体操作仍使用原工具的共享USB锁及阶段永久锁。
    path = HERE / 'QUICK_DISPATCH.lock'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def run_logged(argv, log):
    with log.open('xb') as output:
        process = subprocess.Popen(argv, stdout=output, stderr=subprocess.STDOUT)
        try:
            code = process.wait()
        except KeyboardInterrupt:
            # 不在USB事务中途杀进程；等待原工具记录失败及解除其资源。
            print('已请求中断，等待原操作器结束并保存记录，不重发请求。', flush=True)
            while process.poll() is None:
                try:
                    process.wait()
                except KeyboardInterrupt:
                    continue
            raise
    print(log.read_text(errors='replace'), end='', flush=True)
    if code != 0:
        raise RuntimeError('子程序退出码' + str(code) + '；查看' + str(log) + '，停止、不重试')


def operation(path, manifest, action, out):
    argv = ['/usr/bin/sudo', '-n', '--', str(PYTHON), '-B', str(path / 'tool.py'), action,
            '--package', str(path), '--device-io', '--accept', tool.phrase(path, action)]
    run_logged(argv, out / (action + '.log'))
    result_path = path / '.state' / action / 'result.json'
    result = read_json(result_path)
    if (result.get('passed') is not True or result.get('host_recovery_verified') is not True
            or any(result.get(k) != v for k, v in dict(run_id=manifest['run_id'], package=str(path),
                     action=action, manifest_sha256=tool.sha(path / 'manifest.json')).items())):
        raise ValueError('本阶段回执、USB恢复或会话绑定不符，停止')


def screen_confirm(path, action, out, ask=input):
    answer = ask('请仅查看相机屏幕；正常请输入 NORMAL（异常或取消则停止，不拔插/重启）：').strip()
    if answer != 'NORMAL':
        raise PermissionError('未确认屏幕正常；保留待确认门槛，不进入下一阶段')
    run_logged([str(PYTHON), '-B', str(path / 'tool.py'), 'confirm-screen', '--package', str(path),
                '--phase', action, '--screen-normal'], out / (action + '-screen.log'))


def start(path=None, ip=None, *, ask=input):
    if sys.platform != 'darwin' or os.geteuid() == 0 or not sys.stdin.isatty():
        raise PermissionError('请在Mac交互终端以普通用户运行；程序会单独请求sudo认证')
    with dispatcher_lock():
        require_idle()
        path, manifest = fresh_package(path) if path is not None else prepare()
        fresh_package(path)
        print('本次包：' + str(path))
        print('阶段：载入3个随机前缀程序→屏幕确认→一次libJit启动→屏幕确认。')
        print('固定库：/tmp/jiritsu/libJit.so；存在固定路径覆盖、持久残留及恢复受限风险。')
        print('监听0.0.0.0:2222，不限时；保留原始视图终端/SCP。不写预加载、不DEBUG、不自启、不操作SD卡。')
        print('请确认稳定独立供电、海量存储USB、屏幕正常；过程中保持连接、不移动卡或重启。')
        expected = 'START-' + manifest['run_id'][:8]
        if ask('接受并开始这一次尝试请输入 ' + expected + '：').strip() != expected:
            raise PermissionError('未批准；只完成本机准备，没有访问相机')
        if any(p.is_symlink() for p in (RUNS, *RUNS.parents)):
            raise ValueError('快捷日志目录存在链接，停止')
        RUNS.mkdir(mode=0o700, exist_ok=True)
        out = RUNS / manifest['run_id']
        out.mkdir(mode=0o700)
        tool.save(out / 'authorization.json', dict(source='local_terminal_explicit_phrase', run_id=manifest['run_id'],
                  package=str(path), manifest_sha256=tool.sha(path / 'manifest.json'), phases=['load-once', 'start-once'],
                  target_ipv4_for_printing_only=ip, ttl_seconds=0, autostart=False, automatic_retry=False,
                  preload_written=False, debug=False, script_sha256=tool.sha(Path(__file__))))
        result = dict(passed=False, package=str(path), run_id=manifest['run_id'], log_directory=str(out),
                      automatic_retry=False, ssh_network_connections=0, service_stop_requested=False)
        step = 'sudo认证'
        began = time.monotonic()
        try:
            print('请仅在本机sudo提示中输入Mac密码，不写入口令参数或日志。', flush=True)
            subprocess.run(['/usr/bin/sudo', '-v'], check=True)  # 密码只由系统终端接收。
            require_idle()
            fresh_package(path)
            for action in ('load-once', 'start-once'):
                step = action
                print('执行：' + action + '；日志：' + str(out), flush=True)
                operation(path, manifest, action, out)
                step = action + '屏幕确认'
                screen_confirm(path, action, out, ask)
            result.update(passed=True, login_command=login_command(path, ip),
                          note='READY/USB/屏幕门槛通过；未自动登录SSH或重做终端/SCP验收，不代表网络已验证')
        except (Exception, KeyboardInterrupt) as exc:
            result.update(failure=type(exc).__name__ + ': ' + str(exc), failed_step=step)
        finally:
            result['elapsed_seconds'] = round(time.monotonic() - began, 3)
            tool.save(out / 'result.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result['passed']:
            raise RuntimeError('本次执行中断，保留包/锁/日志；不继续、不重试、不自动恢复')
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('status', 'prepare', 'start'), default='status')
    parser.add_argument('--package', type=Path, help='指定尚未执行过的新包；不重用旧包永久锁')
    parser.add_argument('--ip', type=lambda s: str(ipaddress.IPv4Address(s)), help='仅用于打印登录命令，不探测网络')
    parser.add_argument('--execute', action='store_true', help='只对start有效；仍需终端显式批准和屏幕确认')
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.execute and args.action != 'start':
        parser.error('--execute仅适用于start')
    if args.package is not None and args.action != 'start':
        parser.error('--package仅适用于start')
    if args.action == 'status':
        result = status(args.ip)
    elif args.action == 'prepare':
        path, manifest = prepare()
        result = dict(offline_only=True, package=str(path), run_id=manifest['run_id'], ttl_seconds=0, device_requests=0)
    elif not args.execute:
        result = dict(offline_only=True, device_requests=0, plan=['prepare-or-check', 'load-once', 'screen', 'start-once', 'screen'],
                      execute_hint='./a7r5-ssh/quick-ssh.sh start --execute', current=status(args.ip))
    else:
        start(args.package, args.ip)
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print('执行停止：' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
