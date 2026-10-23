"""桌面与网页共用的独占会话；只接受固定控制协议。"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from app_paths import paths, worker_executable
from platform_backend import require_backend
from control_actions import ACTION_SPECS

KEYS = ('UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'MENU')


class EmulatorSession:
    def __init__(self):
        require_backend()
        self.paths = paths().prepare()
        self.backend = 'native'
        self.bridge = self.paths.runs / ('ui-' + uuid.uuid4().hex)
        self.bridge.mkdir(mode=0o700)
        self.lock = threading.Lock()
        self.closing = threading.Event()
        self.log = (self.bridge / 'launcher.log').open('wb')
        arguments = ['--without-bluetooth', '--software-gpe', '--capid', '--boot-services',
                     '--gui-trace', '--apply-menu', '--live-bridge', str(self.bridge)]
        if getattr(sys, 'frozen', False) or '__compiled__' in globals():
            command = [worker_executable(), '--worker', 'app', *arguments]
        else:
            command = [sys.executable, '-B', str(self.paths.resources / 'tools/probe-app.py'), *arguments]
        try:
            self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT)
        except BaseException:
            self.log.close()
            raise

    def status(self):
        file = self.bridge / 'status.json'
        value = json.loads(file.read_text()) if file.exists() else {'state': 'starting', 'sequence': 0}
        if self.process.poll() is not None and value['state'] not in ('stopped', 'failed'):
            value.update(state='failed', error='工作进程提前退出；请查看 launcher.log')
        return value

    def command(self, request, timeout=120):
        structured = None
        if isinstance(request, dict) and request.get('action') == 'input':
            from input_registry import InputRegistry
            structured = dict(request)
            key = InputRegistry.load().resolve(request, context=self.status().get('input_context', 'unknown'))
            request = {'action': 'key', 'key': key}
        if not isinstance(request, dict) or set(request) != {'action', 'key'}:
            raise ValueError('请求结构不符')
        action, key = request['action'], request['key']
        if not ((action == 'key' and isinstance(key, str) and (key in KEYS or (structured and key in ACTION_SPECS))) or
                (action in ('stop','initial_setup') and key is None)):
            raise ValueError('仅接受已验证按键或退出')
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('当前操作尚未完成')
        try:
            if getattr(self, 'closing', threading.Event()).is_set() or self.status()['state'] != 'running':
                raise BlockingIOError('虚拟器尚未就绪或正在关闭')
            request = dict(request, id=uuid.uuid4().hex)
            pending = self.bridge / 'request.json'
            if pending.exists():
                raise FileExistsError('已有未处理请求')
            temporary = self.bridge / ('request-' + request['id'] + '.part')
            with temporary.open('x') as stream:
                json.dump(request, stream)
            temporary.replace(pending)
            reply = self.bridge / ('reply-' + request['id'] + '.json')
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if reply.exists():
                    result = json.loads(reply.read_text())
                    if result.get('ok') is not True:
                        raise RuntimeError('工作进程拒绝本次请求')
                    if structured:
                        with (self.bridge / 'input-actions.jsonl').open('a') as stream:
                            stream.write(json.dumps({'request': structured, 'id': request['id'],
                                                     'result': result, 'release': 'paired-command-checked' if structured['event'] in ('tap','pad') else 'not-a-held-key',
                                                     'semantics':structured['event']}) + '\n')
                    return result
                if self.status()['state'] in ('failed', 'stopped'):
                    raise RuntimeError('虚拟器停止，未重试')
                time.sleep(.01)
            self.cancel()
            raise TimeoutError('本次操作超时，已请求停止，未重试')
        finally:
            self.lock.release()

    def cancel(self):
        self.closing.set()
        if self.process.poll() is None:
            (self.bridge / 'cancel').touch(exist_ok=True)

    def close(self, timeout=180):
        """取消可与正在执行的请求并行；只有退出回执才能确认完成。"""
        self.cancel()
        try:
            worker_exit = self.process.wait(timeout=timeout)
            receipt = {'worker_exit_code': worker_exit}
            (self.bridge / 'host-exit.json').write_text(json.dumps(receipt, indent=2) + '\n')
            started = self.bridge / 'owned-run'
            if not started.exists():
                started = self.bridge / 'started'
            if not started.exists():
                if self.process.returncode == 0:
                    raise RuntimeError('缺少本次虚拟器目录回执')
                raise RuntimeError('启动失败，请查看 launcher.log；没有声明正常退出')
            run = Path(started.read_text().strip())
            if run.resolve().parent != self.bridge.parent.resolve() or run.is_symlink():
                raise ValueError('退出回执目录越界')
            result = json.loads((run / 'exit.json').read_text())
            receipt['qemu_cleanup'] = result
            (self.bridge / 'host-exit.json').write_text(json.dumps(receipt, indent=2) + '\n')
            if worker_exit != 0:
                raise RuntimeError('工作进程退出异常：' + str(worker_exit) + '；QEMU 回执见 host-exit.json')
            if result != {'method': 'qmp-quit', 'exit_code': 0}:
                raise RuntimeError('未取得正常 QMP 退出回执：' + str(result))
            return result
        finally:
            if self.process.poll() is not None:
                self.log.close()

    def frame(self):
        """状态前后相同且摘要匹配时才交给界面，避免显示旧帧。"""
        state = self.status()
        if not state.get('sequence'):
            return None
        png = (self.bridge / 'frame.png').read_bytes()
        if state != self.status() or hashlib.sha256(png).hexdigest() != state.get('png_sha256'):
            return None
        return state, png
