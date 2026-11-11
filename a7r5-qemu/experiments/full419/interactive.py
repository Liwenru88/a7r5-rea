"""通过 Qt 按钮逐步操作最终客体，完整输出另存日志。"""
import argparse
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--log', type=Path, required=True)
    a = p.parse_args()
    child = subprocess.Popen([sys.executable, '-B', str(HERE / 'qt_research.py'),
                              '--manifest', str(a.manifest.resolve())],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    pending = bytearray()
    rows = []
    with a.log.open('xb') as log:
        def wait():
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                while b'\n' in pending:
                    line, _, rest = pending.partition(b'\n')
                    pending[:] = rest
                    if line.startswith(b'QT_REPLY '):
                        return json.loads(line[9:])
                if select.select([child.stdout], [], [], .1)[0]:
                    data = os.read(child.stdout.fileno(), 65536)
                    if not data and child.poll() is not None:
                        raise RuntimeError('Qt 提前退出，请检查完整日志')
                    pending.extend(data)
                    log.write(data)
                    log.flush()
            raise RuntimeError('Qt 回执超时')
        try:
            first = wait()
            run = Path(first['run'])
            print(json.dumps(first, ensure_ascii=False), flush=True)
            for line in sys.stdin:
                action = line.strip()
                child.stdin.write((action + '\n').encode())
                child.stdin.flush()
                row = wait()
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                if action == 'STOP':
                    code = child.wait(timeout=30)
                    if code:
                        raise RuntimeError('Qt 未正常退出')
                    (run / 'full419-interactive.json').write_text(json.dumps(
                        dict(status='PASS', actions=rows, exit_code=code, camera_io=False),
                        ensure_ascii=False, indent=2) + '\n')
                    return
            raise RuntimeError('未发送 STOP')
        finally:
            if child.poll() is None:
                child.stdin.close()
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=10)


if __name__ == '__main__':
    main()
