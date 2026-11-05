"""仅管理本实验创建的一个 QEMU，关闭后再计算证据哈希。"""
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time

from app_paths import paths
LAB = paths().resources
RUNS = paths().runs
ANALYSIS = LAB / 'tools'
sys.path.insert(0, str(ANALYSIS))
from menu_live import serial_command


class VM:
    def __init__(self, prefix, capid=False, boot_services=False):
        paths().prepare()
        self.out = Path(tempfile.mkdtemp(prefix=prefix + '-', dir=RUNS))
        self.console = self.out / 'console.log'
        self.process = None
        self.log = None
        self.lock = None
        self.capid = capid
        self.boot_services = boot_services

    def command(self, code, timeout=90):
        return serial_command(self.process, self.console, code, timeout=timeout)

    def close(self):
        result = {'method': 'not-started', 'exit_code': None}
        try:
            if self.process is not None and self.process.poll() is None:
                try:
                    with socket.socket(socket.AF_UNIX) as sock:
                        sock.settimeout(4)
                        self.connect_qmp(sock)
                        with sock.makefile('rwb') as stream:
                            if 'QMP' not in json.loads(stream.readline()):
                                raise RuntimeError('无效 QMP 握手')
                            for name in ('qmp_capabilities', 'quit'):
                                stream.write(json.dumps({'execute': name}).encode() + b'\n')
                                stream.flush()
                                while True:
                                    reply = json.loads(stream.readline())
                                    if 'error' in reply:
                                        raise RuntimeError(str(reply['error']))
                                    if 'return' in reply:
                                        break
                    self.process.wait(timeout=5)
                    result['method'] = 'qmp-quit'
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                    result['qmp_error'] = str(error)
                    try:
                        os.killpg(self.process.pid, signal.SIGTERM)
                        self.process.wait(timeout=5)
                        result['method'] = 'owned-group-term'
                    except ProcessLookupError:
                        pass
                    except subprocess.TimeoutExpired:
                        os.killpg(self.process.pid, signal.SIGKILL)
                        self.process.wait(timeout=3)
                        result['method'] = 'owned-group-kill'
            if self.process is not None:
                result['exit_code'] = self.process.wait(timeout=3)
        finally:
            if self.log:
                self.log.close()
            if self.lock:
                self.lock.close()
            (self.out / 'exit.json').write_text(json.dumps(result, indent=2) + '\n')
        return result
