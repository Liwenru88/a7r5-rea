"""不启动 VM 的 HTTP 边界与原控制请求派发回归。"""
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error

spec=importlib.util.spec_from_file_location('menu_ui',Path(__file__).with_name('menu-ui.py'))
ui=importlib.util.module_from_spec(spec);spec.loader.exec_module(ui)


class HTTPBoundary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
        (self.path/'status.json').write_text(json.dumps({'state':'running','sequence':1}))
        self.session=ui.Session.__new__(ui.Session)
        self.session.bridge=self.path;self.session.lock=threading.Lock()
        self.session.process=type('OwnedProcess',(),{'poll':lambda s:None})()
        self.server=ui.create_server(self.session)
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.url=f'http://127.0.0.1:{self.server.server_port}'
        page=urllib.request.urlopen(self.url).read().decode()
        self.token=re.search("const token='([^']+)'",page)[1]

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def post(self,body,**headers):
        base={'Content-Type':'application/json','Origin':self.url,'X-Session-Token':self.token}
        base.update(headers)
        req=urllib.request.Request(self.url+'/command',json.dumps(body).encode(),headers=base)
        try:
            with urllib.request.urlopen(req,timeout=5) as r:return r.status,json.loads(r.read())
        except urllib.error.HTTPError as r:return r.code,json.loads(r.read())

    def test_cross_origin_and_missing_session_cannot_dispatch(self):
        for headers in ({'Origin':'https://example.invalid'},{'X-Session-Token':''},{'Host':'example.invalid'}):
            self.assertEqual(self.post({'action':'key','key':'UP'},**headers)[0],403)
        self.assertFalse((self.path/'request.json').exists())

    def test_unknown_keys_extra_fields_and_shell_text_cannot_dispatch(self):
        for body in ({'action':'key','key':'UP; reboot'},{'action':'shell','key':'uname'},
                     {'action':'key','key':'UP','command':'anything'}, {'action':'key','key':['UP']}):
            self.assertEqual(self.post(body)[0],400)
        self.assertFalse((self.path/'request.json').exists())

    def test_busy_and_failed_session_reject_new_keys(self):
        self.session.lock.acquire()
        self.assertEqual(self.post({'action':'key','key':'UP'})[0],409)
        self.session.lock.release()
        (self.path/'status.json').write_text(json.dumps({'state':'failed'}))
        self.assertEqual(self.post({'action':'key','key':'UP'})[0],409)
        self.assertFalse((self.path/'request.json').exists())

    def test_navigation_dispatch_is_one_atomic_structured_request(self):
        received=[]
        def worker():
            p=self.path/'request.json';deadline=time.monotonic()+3
            while not p.exists() and time.monotonic()<deadline:time.sleep(.005)
            r=json.loads(p.read_text());received.append(r)
            (self.path/('reply-'+r['id']+'.json')).write_text('{"ok":true,"sequence":2}')
        t=threading.Thread(target=worker);t.start()
        self.assertEqual(self.post({'action':'key','key':'LEFT'}),(200,{'ok':True,'sequence':2}))
        t.join();self.assertEqual(len(received),1)
        self.assertEqual(set(received[0]),{'id','action','key'})
        self.assertRegex(received[0]['id'],'^[0-9a-f]{32}$')

    def test_only_fixed_http_resources_are_exposed(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(self.url+'/../../README.md')
        self.assertEqual(context.exception.code,404)


if __name__=='__main__':unittest.main()
