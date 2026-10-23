"""显式网页回退的一帧与正常退出冒烟，不重复完整导航回归。"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    web = load('web', ROOT / 'tools/menu-ui.py')
    session = web.Session()
    server = web.create_server(session)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    def get(path):
        with urllib.request.urlopen(url + path, timeout=10) as response:
            return response.read()
    try:
        token = re.search("const token='([^']+)'", get('/').decode())[1]
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            state = json.loads(get('/status'))
            if state['state'] == 'running':
                break
            if state['state'] == 'failed':
                raise RuntimeError(state)
            time.sleep(.2)
        else:
            raise TimeoutError('网页回退启动超时')
        assert get('/frame.png').startswith(b'\x89PNG')
        request = urllib.request.Request(url + '/command', json.dumps({'action': 'stop', 'key': None}).encode(), headers={
            'Origin': url, 'X-Session-Token': token, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=125) as response:
            assert json.load(response)['ok']
        cleanup = session.close()
        cycles = load('cycles', ROOT / 'tests/check-menu-cycles.py')
        frames, result = cycles.saved_frames(Path(state['run']).name, prefix='live-')
        assert len(frames) == 1
        receipt = {'status': 'verified', 'url': url, 'run': state['run'], 'cleanup': cleanup, 'frames': frames}
        (ROOT / 'logs/desktop-implementation/web-smoke.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt), flush=True)
    finally:
        if session.process.poll() is None:
            session.close()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    main()
