"""通过真实 HTTP 控制入口验收固定导航、MENU 重入、空闲冻结和正常退出。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
import time
import urllib.request

LAB=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(LAB/'tools'))
spec=importlib.util.spec_from_file_location('menu_ui',LAB/'tools/menu-ui.py')
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)
spec=importlib.util.spec_from_file_location('cycles',LAB/'tests/check-menu-cycles.py')
cycles=importlib.util.module_from_spec(spec);spec.loader.exec_module(cycles)


def main():
    session=ui.Session();server=ui.create_server(session)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    url=f'http://127.0.0.1:{server.server_port}'
    (session.bridge/'url.txt').write_text(url+'\n')
    print(json.dumps({'url':url,'bridge':str(session.bridge)}),flush=True)
    def get(path):
        with urllib.request.urlopen(url+path,timeout=10) as response:return response.read()
    token=re.search("const token='([^']+)'",get('/').decode())[1]
    def post(action,key=None):
        request=urllib.request.Request(url+'/command',json.dumps({'action':action,'key':key}).encode(),headers={
            'Content-Type':'application/json','Origin':url,'X-Session-Token':token})
        with urllib.request.urlopen(request,timeout=125) as response:
            result=json.load(response);assert result['ok'];return result
    try:
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            status=json.loads(get('/status'))
            if status['state']=='running':break
            if status['state']=='failed':raise RuntimeError(status)
            time.sleep(.5)
        else:raise TimeoutError('原生菜单启动未完成')
        run=Path(status['run']);initial=status['pixel_sha256'];closed=None
        idle_before=hashlib.sha256((run/'console.log').read_bytes()).hexdigest()
        state=json.loads((run/'native-runtime-state.json').read_text())
        assert state['qmp_status']['running'] is False and state['paused_for_input'] is True
        time.sleep(5)
        assert hashlib.sha256((run/'console.log').read_bytes()).hexdigest()==idle_before
        for index in range(8):
            post('key','MENU');status=json.loads(get('/status'))
            if index%2==0:
                assert status['pixel_sha256']!=initial
                closed=closed or status['pixel_sha256'];assert status['pixel_sha256']==closed
            else:assert status['pixel_sha256']==initial
            print('MENU_CYCLE_STEP',index+1,status['sequence'],flush=True)
        navigation=('RIGHT','DOWN','ENTER','UP','LEFT','MENU')
        history=json.loads((LAB/'evidence/history/logs/native-reentry-acceptance.json').read_text())
        # 历史像素只作为独立预期值，路径文字不参与运行。
        expected=history['navigation']
        if isinstance(expected,dict):expected=expected['frames']
        navigation_rows=[]
        for key,reference in zip(navigation,expected[1:],strict=True):
            post('key',key);status=json.loads(get('/status'))
            assert status['pixel_sha256']==reference['pixel_sha256'],(key,status,reference)
            navigation_rows.append({'key':key,'pixel_sha256':status['pixel_sha256']})
            print('NAVIGATION_PASS',key,flush=True)
        post('stop');assert session.process.wait(timeout=20)==0
        frames,result=cycles.saved_frames(run.name,prefix='live-')
        assert len(frames)==15 and result['cleanup']=={'method':'qmp-quit','exit_code':0}
        acceptance={'status':'verified','run':run.name,'bridge':session.bridge.name,
                    'menu_cycles':4,'raw_frames_independently_verified':len(frames),'idle_seconds':5,
                    'navigation':navigation_rows,'cleanup':result['cleanup'],'frames':frames}
        (LAB/'logs/native-acceptance.json').write_text(json.dumps(acceptance,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({k:v for k,v in acceptance.items() if k!='frames'}),flush=True)
    finally:
        if session.process.poll() is None:
            (session.bridge/'cancel').touch();session.process.wait(timeout=100)
        server.shutdown();server.server_close();thread.join();session.log.close()


if __name__=='__main__':main()
